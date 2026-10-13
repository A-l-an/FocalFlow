"""Offline TTS error boundaries using the installed SDK and HTTPX transport."""
import contextlib
import errno
import io
import logging
import socket
import ssl
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

from MobileAgent import api
from MobileAgent.failure import CallBudget, DeadlineExceeded, FailurePolicy, OperationError
from MobileAgent.protocol import Cancelled


PRIVATE = 'synthetic-private-url-header-body-token'


class Body(httpx.SyncByteStream):
    def __init__(self, error=None, close_error=None):
        self.error, self.close_error = error, close_error
        self.reads = self.closes = 0

    def __iter__(self):
        self.reads += 1
        yield b'synthetic-audio'
        if self.error is not None:
            raise self.error

    def close(self):
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


class TTSNetworkErrorTests(unittest.TestCase):
    @contextlib.contextmanager
    def boundary(self, *, request_error=None, body=None, status=200, on_request=None,
                 playback_error=None, close_error=None):
        """Replace only network I/O and native playback; keep SDK ownership real."""
        state = {'requests': [], 'clients': [], 'played': [], 'paths': [], 'options': []}
        body = body if body is not None else Body()
        real_http, real_sdk = openai.DefaultHttpxClient, openai.OpenAI

        def handler(request):
            state['requests'].append(request)
            if on_request is not None:
                on_request()
            if request_error is not None:
                raise request_error
            return httpx.Response(status, request=request, stream=body)

        class Transport(httpx.MockTransport):
            def close(self):
                super().close()
                if close_error is not None:
                    raise close_error

        def http_factory(**kwargs):
            client = real_http(transport=Transport(handler), **kwargs)
            state['clients'].append(client)
            return client

        def sdk_factory(**kwargs):
            state['options'].append(kwargs)
            return real_sdk(base_url='https://offline.test/v1', **kwargs)

        def play(path, guard=None):
            state['paths'].append(Path(path))
            state['played'].append(Path(path).read_bytes())
            if playback_error is not None:
                raise playback_error

        with patch.object(openai, 'DefaultHttpxClient', http_factory), \
             patch.object(openai, 'OpenAI', sdk_factory), \
             patch.object(api, 'play_audio_file', play):
            try:
                yield state
            finally:
                self.assertEqual(len(state['requests']), 1, 'TTS must not retry')
                self.assertTrue(all(client.is_closed for client in state['clients']))
                self.assertTrue(all(not path.exists() for path in state['paths']))

    def tts(self, **kwargs):
        api.text2audio('synthetic text', API_TOKEN='nonfunctional-test-token', **kwargs)

    def assert_failure(self, failure, code, cause=None):
        self.assertEqual(failure.stage, 'tts')
        self.assertEqual(failure.code, code)
        self.assertEqual(getattr(failure, 'cause_code', None), cause)
        self.assertNotIn(PRIVATE, str(failure))
        self.assertNotIn(PRIVATE, ''.join(traceback.format_exception(
            type(failure), failure, failure.__traceback__)))

    def test_sdk_wrapped_read_timeout_is_network_timeout_without_retry(self):
        with self.boundary(request_error=httpx.ReadTimeout(PRIVATE)) as state:
            with self.assertRaises(OperationError) as raised:
                self.tts(policy=FailurePolicy(attempts=3))
        self.assert_failure(raised.exception, 'NETWORK_TIMEOUT', 'READ_TIMEOUT')
        self.assertIsInstance(raised.exception.__context__, openai.APITimeoutError)
        self.assertEqual(state['played'], [])
        self.assertEqual(state['options'][0]['max_retries'], 0)
        self.assertEqual(state['requests'][0].extensions['timeout'],
                         {'connect': 5.0, 'read': 30.0, 'write': 30.0, 'pool': 5.0})

    def test_stream_read_timeout_closes_response_without_playing_partial_audio(self):
        body = Body(httpx.ReadTimeout(PRIVATE))
        with self.boundary(body=body) as state:
            with self.assertRaises(OperationError) as raised:
                self.tts()
        self.assert_failure(raised.exception, 'NETWORK_TIMEOUT', 'READ_TIMEOUT')
        self.assertEqual(body.closes, 1)
        self.assertEqual(state['played'], [])

    def test_network_and_proxy_causes_at_request_and_stream_boundaries(self):
        for boundary in ('request', 'stream'):
            for kind, inner, code, cause in (
                (httpx.ConnectTimeout, None, 'NETWORK_TIMEOUT', 'CONNECT_TIMEOUT'),
                (httpx.ProxyError, None, 'NETWORK_ERROR', 'PROXY_ERROR'),
                (httpx.ConnectError, OSError(errno.ECONNREFUSED, PRIVATE), 'NETWORK_ERROR', 'CONNECTION_REFUSED'),
                (httpx.ReadError, OSError(errno.ECONNRESET, PRIVATE), 'NETWORK_ERROR', 'CONNECTION_RESET'),
                (httpx.ConnectError, socket.gaierror(-2, PRIVATE), 'NETWORK_ERROR', 'DNS_ERROR'),
                (httpx.ConnectError, ssl.SSLError(PRIVATE), 'NETWORK_ERROR', 'TLS_ERROR'),
                (httpx.RemoteProtocolError, None, 'NETWORK_ERROR', 'CONNECTION_ERROR'),
            ):
                with self.subTest(boundary=boundary, kind=kind.__name__, cause=cause):
                    error = kind(PRIVATE)
                    error.__cause__ = inner
                    body = Body(error if boundary == 'stream' else None)
                    with self.boundary(body=body, request_error=error if boundary == 'request' else None) as state:
                        with self.assertRaises(OperationError) as raised:
                            self.tts()
                    self.assert_failure(raised.exception, code, cause)
                    self.assertEqual(state['played'], [])
                    self.assertEqual(body.closes, 1 if boundary == 'stream' else 0)

    def test_unspecified_sdk_and_httpx_timeouts_have_safe_timeout_cause(self):
        request = httpx.Request('POST', 'https://offline.test/v1/audio/speech')
        for error in (openai.APITimeoutError(request), httpx.TimeoutException(PRIVATE),
                      httpx.WriteTimeout(PRIVATE), httpx.PoolTimeout(PRIVATE)):
            with self.subTest(kind=type(error).__name__), self.boundary(body=Body(error)):
                with self.assertRaises(OperationError) as raised:
                    self.tts()
            self.assert_failure(raised.exception, 'NETWORK_TIMEOUT', 'TIMEOUT')

    def test_sdk_connection_error_is_network_error(self):
        error = openai.APIConnectionError(message=PRIVATE, request=httpx.Request('POST', 'https://offline.test'))
        with self.boundary(body=Body(error)):
            with self.assertRaises(OperationError) as raised:
                self.tts()
        self.assert_failure(raised.exception, 'NETWORK_ERROR', 'CONNECTION_ERROR')

    def test_response_hook_error_has_priority_over_sdk_connection_wrapper(self):
        for status in (302, 429, 503):
            body = Body(httpx.ReadTimeout(PRIVATE))
            with self.subTest(status=status), self.boundary(status=status, body=body) as state:
                with self.assertRaises(OperationError) as raised:
                    self.tts()
            self.assert_failure(raised.exception, 'HTTP_ERROR')
            self.assertEqual(raised.exception.status, status)
            self.assertEqual(body.reads, 0)
            self.assertGreaterEqual(body.closes, 1)
            self.assertEqual(state['played'], [])

    def test_cancel_and_deadline_take_priority_over_sdk_network_wrapper(self):
        for interruption in (Cancelled('synthetic cancelled'), DeadlineExceeded()):
            for via_hook in (False, True):
                active = []
                class Guard:
                    def check(self):
                        if active:
                            raise interruption
                    def remaining(self):
                        self.check()
                        return 120
                with self.subTest(kind=type(interruption).__name__, via_hook=via_hook):
                    body = Body()
                    with self.boundary(body=body, status=503,
                                       request_error=None if via_hook else httpx.ReadTimeout(PRIVATE),
                                       on_request=lambda: active.append(True)) as state:
                        with self.assertRaises(type(interruption)) as raised:
                            self.tts(guard=Guard())
                    self.assertIs(raised.exception, interruption)
                    self.assertEqual(body.reads, 0)
                    self.assertEqual(state['played'], [])

    def test_explicit_stream_control_errors_are_preserved(self):
        for error in (Cancelled('synthetic cancelled'), DeadlineExceeded(), OperationError('tts', 'RESPONSE_LIMIT')):
            body = Body(error)
            with self.subTest(kind=type(error).__name__), self.boundary(body=body):
                with self.assertRaises(type(error)) as raised:
                    self.tts()
            self.assertIs(raised.exception, error)
            self.assertEqual(body.closes, 1)

    def test_non_network_errors_and_type_name_lookalikes_stay_provider_errors(self):
        for boundary in ('request', 'stream'):
            for kind in (RuntimeError, httpx.DecodingError, httpx.LocalProtocolError, httpx.UnsupportedProtocol,
                         type('ReadTimeout', (RuntimeError,), {}), type('ProxyError', (RuntimeError,), {})):
                with self.subTest(boundary=boundary, kind=kind.__name__):
                    error = kind(PRIVATE)
                    with self.boundary(request_error=error if boundary == 'request' else None,
                                       body=Body(error if boundary == 'stream' else None)):
                        with self.assertRaises(OperationError) as raised:
                            self.tts()
                    self.assert_failure(raised.exception, 'PROVIDER_ERROR')

    def test_network_cause_ignores_fake_types_and_non_os_errno(self):
        for boundary in ('request', 'stream'):
            for name in ('ReadTimeout', 'ProxyError', 'SSLError', 'NameResolutionError', 'TimeoutError'):
                with self.subTest(boundary=boundary, name=name):
                    inner = type(name, (RuntimeError,), {})(PRIVATE)
                    inner.errno = errno.ECONNREFUSED
                    error = httpx.ConnectError(PRIVATE)
                    error.__cause__ = inner
                    with self.boundary(request_error=error if boundary == 'request' else None,
                                       body=Body(error if boundary == 'stream' else None)):
                        with self.assertRaises(OperationError) as raised:
                            self.tts()
                    self.assert_failure(raised.exception, 'NETWORK_ERROR', 'CONNECTION_ERROR')

    def test_nested_sdk_wrappers_follow_real_network_type(self):
        request = httpx.Request('POST', 'https://offline.test')
        for inner, code, cause in ((httpx.ReadTimeout(PRIVATE), 'NETWORK_TIMEOUT', 'READ_TIMEOUT'),
                                   (RuntimeError(PRIVATE), 'PROVIDER_ERROR', None)):
            with self.subTest(inner=type(inner).__name__):
                error = openai.APIConnectionError(request=request)
                error.__cause__ = inner
                with self.boundary(request_error=error):
                    with self.assertRaises(OperationError) as raised:
                        self.tts()
                self.assert_failure(raised.exception, code, cause)

    def test_network_cause_follows_only_the_active_exception_chain(self):
        for mode, cause in (('explicit', 'CONNECTION_ERROR'), ('suppressed', 'CONNECTION_ERROR'),
                            ('context', 'CONNECTION_REFUSED')):
            with self.subTest(mode=mode):
                error = httpx.ConnectError(PRIVATE)
                error.__context__ = OSError(errno.ECONNREFUSED, PRIVATE)
                if mode == 'explicit':
                    error.__cause__ = RuntimeError(PRIVATE)
                elif mode == 'suppressed':
                    error.__suppress_context__ = True
                with self.boundary(body=Body(error)):
                    with self.assertRaises(OperationError) as raised:
                        self.tts()
                self.assert_failure(raised.exception, 'NETWORK_ERROR', cause)

    def test_audio_errors_including_httpx_types_stay_provider_errors(self):
        for kind in (RuntimeError, ValueError, httpx.ReadTimeout, httpx.ProxyError):
            body = Body()
            with self.subTest(kind=kind.__name__), self.boundary(body=body, playback_error=kind(PRIVATE)) as state:
                with self.assertRaises(OperationError) as raised:
                    self.tts()
            self.assert_failure(raised.exception, 'PROVIDER_ERROR')
            self.assertEqual(state['played'], [b'synthetic-audio'])
            self.assertEqual(body.closes, 1)

    def test_client_cleanup_failure_cannot_replace_network_failure_or_leak_text(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), \
                 self.boundary(request_error=httpx.ReadTimeout(PRIVATE), close_error=RuntimeError(PRIVATE)):
                with self.assertRaises(OperationError) as raised:
                    self.tts()
        finally:
            root.removeHandler(handler)
        self.assert_failure(raised.exception, 'NETWORK_TIMEOUT', 'READ_TIMEOUT')
        self.assertIn('HTTP cleanup failed: RuntimeError', output.getvalue())
        self.assertNotIn(PRIVATE, output.getvalue())

    def test_request_deadline_still_expires_at_120_seconds(self):
        for elapsed in (119.0, 120.0):
            now = [0.0]
            def make_budget(policy, guard):
                return CallBudget(policy, guard, clock=lambda: now[0])
            with self.subTest(elapsed=elapsed), patch.object(api, 'CallBudget', make_budget), \
                 self.boundary(request_error=httpx.ReadTimeout(PRIVATE), on_request=lambda: now.__setitem__(0, elapsed)):
                with self.assertRaises(OperationError) as raised:
                    self.tts()
            if elapsed == 119.0:
                self.assert_failure(raised.exception, 'NETWORK_TIMEOUT', 'READ_TIMEOUT')
            else:
                self.assertIsInstance(raised.exception, DeadlineExceeded)


if __name__ == '__main__':
    unittest.main()
