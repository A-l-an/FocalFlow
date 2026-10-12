"""Offline failures/deadlines against the real production boundaries."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class FailureBoundaryTests(unittest.TestCase):
    def test_default_provider_failure_does_not_retry(self):
        from MobileAgent import api
        calls = []
        class StopObservation(BaseException): pass
        def post(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) > 1: raise StopObservation()
            raise RuntimeError('synthetic private detail')
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
            try: api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'offline-test-token')
            except BaseException: pass
        self.assertEqual(len(calls), 1, 'default must never issue an automatic second paid call')

    def test_live_adb_pull_has_finite_timeout(self):
        from MobileAgent import controller
        calls = []
        def run(*args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(returncode=1)
        with patch.object(controller.subprocess, 'run', run):
            with self.assertRaises(RuntimeError): controller.pull_transport_snapshot('synthetic adb')
        self.assertEqual(calls[0].get('timeout'), 10)

import contextlib
import io
import json
import socket
import threading
import tempfile
from pathlib import Path
from requests import exceptions as network_errors
from MobileAgent.failure import FailurePolicy, OperationError, DeadlineExceeded
from MobileAgent.protocol import Cancelled
from examples import offline_demo as demo
from tests import test_freshness as freshness


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else [b'{"choices":[{"message":{"content":"synthetic answer"}}]}']
        self.closed = 0
        self.headers = {'Content-Type': 'audio/mpeg'}
    def iter_content(self, chunk_size):
        if chunk_size != 1: raise AssertionError('trickle-safe requests read boundary')
        return iter(self.body)
    def close(self): self.closed += 1


class ProviderLifecycleTests(unittest.TestCase):
    def call(self, post, **kwargs):
        from MobileAgent import api
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
            return api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'offline-test-token', **kwargs)

    def test_policy_rejects_invalid_timeout_and_retry_values(self):
        for field in ('connect', 'read', 'request', 'adb', 'write', 'frame', 'backoff'):
            for value in (0, -1, True, float('nan'), float('inf'), '5'):
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaises(ValueError): FailurePolicy(**{field: value})
        for value in (0, 4, True, 1.5):
            with self.assertRaises(ValueError): FailurePolicy(attempts=value)

    def test_retry_is_explicit_bounded_and_limited_to_retryable_status(self):
        for status in (401, 403, 422, 429, 500, 503):
            with self.subTest(status=status):
                first, second = Response(status), Response()
                calls, waits = [], []
                def post(*args, **kwargs):
                    calls.append(kwargs)
                    return first if len(calls) == 1 else second
                if status in (429, 500, 503):
                    self.assertEqual(self.call(post, policy=FailurePolicy(attempts=3), wait=waits.append), 'synthetic answer')
                    self.assertEqual(len(calls), 2); self.assertEqual(waits, [0.5])
                    self.assertEqual(second.closed, 1)
                else:
                    with self.assertRaises(OperationError) as error:
                        self.call(post, policy=FailurePolicy(attempts=3), wait=waits.append)
                    self.assertEqual(error.exception.status, status)
                    self.assertEqual(error.exception.code, 'HTTP_ERROR')
                    self.assertEqual(len(calls), 1); self.assertEqual(waits, [])
                self.assertEqual(first.closed, 1)
                self.assertEqual(calls[0]['timeout'], (5, 30))
                self.assertTrue(calls[0]['stream'])
                self.assertEqual(calls[0]['json']['temperature'], 0.0)
                self.assertEqual(calls[0]['json']['max_tokens'], 2048)
                self.assertEqual(calls[0]['json']['seed'], 1234)

    def test_exact_luna_payload_preserves_text_images_and_legacy_models(self):
        from MobileAgent import api
        content = [
            {'type': 'text', 'text': 'synthetic image question'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,c3ludGhldGlj'}},
        ]
        messages = [['system', 'synthetic instruction'], ['user', content]]
        for model in ('gpt-6-luna', 'gpt-4o', 'gpt-6-luna-other'):
            with self.subTest(model=model):
                captured = []
                response = Response()
                def post(*args, **kwargs):
                    captured.append(kwargs['json'])
                    return response
                with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
                    result = api.inference_chat(messages, model, 'https://offline.test/chat', 'offline-test-token')
                self.assertEqual(result, 'synthetic answer')
                self.assertEqual(len(captured), 1)
                wanted = {
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': 'synthetic instruction'},
                        {'role': 'user', 'content': [
                            {'type': 'text', 'text': 'synthetic image question'},
                            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,c3ludGhldGlj'}},
                        ]},
                    ],
                }
                if model == 'gpt-6-luna':
                    wanted.update(max_completion_tokens=2048, reasoning_effort='none')
                else:
                    wanted.update(max_tokens=2048, temperature=0.0, seed=1234)
                self.assertEqual(captured[0], wanted)
                self.assertEqual(response.closed, 1)
                self.assertEqual(messages[1][1][1]['image_url']['url'], 'data:image/png;base64,c3ludGhldGlj')

    def test_default_and_explicit_network_attempt_limits(self):
        for attempts in (1, 3):
            calls, waits = [], []
            def post(*args, **kwargs):
                calls.append(1)
                raise network_errors.Timeout('SYNTHETIC_PRIVATE_URL_TOKEN')
            with self.assertRaises(OperationError) as error:
                self.call(post, policy=FailurePolicy(attempts=attempts), wait=waits.append)
            self.assertEqual(len(calls), attempts)
            self.assertEqual(len(waits), attempts - 1)
            self.assertEqual(error.exception.code, 'NETWORK_TIMEOUT')
            self.assertNotIn('PRIVATE', str(error.exception))
            self.assertTrue(error.exception.__suppress_context__)

    def test_network_error_preserves_only_safe_type_derived_cause(self):
        import errno
        import ssl
        cases = [
            (network_errors.ProxyError('PRIVATE_URL_TOKEN'), 'PROXY_ERROR'),
            (network_errors.SSLError('PRIVATE_URL_TOKEN'), 'TLS_ERROR'),
            (network_errors.ConnectTimeout('PRIVATE_URL_TOKEN'), 'CONNECT_TIMEOUT'),
            (network_errors.ReadTimeout('PRIVATE_URL_TOKEN'), 'READ_TIMEOUT'),
            (socket.gaierror(-2, 'PRIVATE_URL_TOKEN'), 'DNS_ERROR'),
            (ConnectionRefusedError(errno.ECONNREFUSED, 'PRIVATE_URL_TOKEN'), 'CONNECTION_REFUSED'),
            (ConnectionResetError(errno.ECONNRESET, 'PRIVATE_URL_TOKEN'), 'CONNECTION_RESET'),
            (OSError(errno.ENETUNREACH, 'PRIVATE_URL_TOKEN'), 'NETWORK_UNREACHABLE'),
            (ssl.SSLError('PRIVATE_URL_TOKEN'), 'TLS_ERROR'),
        ]
        for cause, wanted in cases:
            with self.subTest(cause=wanted):
                outer = network_errors.ConnectionError('PRIVATE_URL_TOKEN')
                outer.__cause__ = cause
                def post(*args, **kwargs): raise outer
                with self.assertRaises(OperationError) as error:
                    self.call(post)
                self.assertEqual(error.exception.code, 'NETWORK_ERROR')
                self.assertEqual(getattr(error.exception, 'cause_code', None), wanted)
                self.assertNotIn('PRIVATE', str(error.exception))

    def test_malformed_body_is_not_retried_and_always_closed(self):
        for body in (b'not-json-PRIVATE', b'{"private":"PRIVATE"}', b'{"choices":[]}', b'{"choices":[{"message":{"content":""}}]}'):
            response = Response(body=[body]); calls = []
            def post(*args, **kwargs): calls.append(1); return response
            with self.assertRaises(OperationError) as error:
                self.call(post, policy=FailurePolicy(attempts=3), wait=lambda _: self.fail('invalid response retried'))
            self.assertEqual(error.exception.code, 'INVALID_RESPONSE')
            self.assertEqual(response.closed, 1); self.assertEqual(calls, [1])
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_trickle_and_oversized_body_are_bounded(self):
        now, pieces = [0.0], []
        def trickle():
            for index in range(100):
                now[0] += 0.4; pieces.append(index); yield b' '
        response = Response(body=trickle())
        with self.assertRaises(DeadlineExceeded):
            self.call(lambda *a, **k: response, policy=FailurePolicy(request=1), clock=lambda: now[0])
        self.assertEqual(len(pieces), 3); self.assertEqual(response.closed, 1)
        huge = Response(body=[b'x' * (1024 * 1024 + 1)])
        with self.assertRaises(OperationError) as error: self.call(lambda *a, **k: huge)
        self.assertEqual(error.exception.code, 'RESPONSE_LIMIT'); self.assertEqual(huge.closed, 1)

    def test_cancelled_backoff_cannot_retry(self):
        cancelled = threading.Event(); calls = []
        class Guard:
            def check(self):
                if cancelled.is_set(): raise Cancelled('cancelled')
            def remaining(self): self.check(); return 120
        response = Response(429)
        def post(*args, **kwargs): calls.append(1); return response
        with self.assertRaises(Cancelled):
            self.call(post, policy=FailurePolicy(attempts=3), guard=Guard(), wait=lambda _: cancelled.set())
        self.assertEqual(calls, [1]); self.assertEqual(response.closed, 1)

    def test_tts_sdk_has_no_layered_retries_and_bounded_iterator(self):
        from MobileAgent import api
        options, played, closed = [], [], []
        class Audio:
            def __enter__(self): return self
            def __exit__(self, *args): closed.append('response')
            def iter_bytes(self, chunk_size):
                self_chunk = chunk_size
                if self_chunk is not None: raise AssertionError('must observe SDK partial chunks')
                yield b'audio'
        client = SimpleNamespace(close=lambda: closed.append('client'), audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=lambda **kw: Audio()))))
        def create(**kwargs): options.append(kwargs); return client
        with patch.dict('sys.modules', {'openai': SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=create)}), patch.object(api, 'play_audio_file', lambda path: played.append(Path(path).read_bytes())):
            api.text2audio('synthetic', API_TOKEN='nonfunctional-test-token')
        self.assertEqual(options[0]['max_retries'], 0)
        self.assertEqual(options[0]['timeout'].connect, 5)
        self.assertEqual(options[0]['timeout'].read, 30)
        self.assertEqual(played, [b'audio']); self.assertEqual(closed, ['response', 'client'])

    def test_tts_empty_or_oversized_audio_never_plays(self):
        from MobileAgent import api
        for body, code in (([], 'EMPTY_AUDIO'), ([b'x' * (32 * 1024 * 1024 + 1)], 'RESPONSE_LIMIT')):
            class Audio:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def iter_bytes(self, **kwargs): return iter(body)
            client = SimpleNamespace(close=lambda: None, audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=lambda **kw: Audio()))))
            with patch.dict('sys.modules', {'openai': SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=lambda **kw: client)}), patch.object(api, 'play_audio_file', side_effect=AssertionError('invalid TTS played')):
                with self.assertRaises(OperationError) as error: api.text2audio('synthetic', API_TOKEN='nonfunctional-test-token')
            self.assertEqual(error.exception.code, code)

    def test_voice_missing_device_is_an_explicit_failure(self):
        from MobileAgent import api
        with patch.dict('sys.modules', {'numpy': SimpleNamespace(), 'sounddevice': SimpleNamespace(query_devices=lambda: []),
                'scipy': SimpleNamespace(), 'scipy.io': SimpleNamespace(wavfile=SimpleNamespace())}):
            with self.assertRaises(OperationError) as error: api.get_voice(None)
        self.assertEqual(error.exception.code, 'NO_DEVICE')

    def test_adb_failed_pull_removes_stale_local_output_and_has_timeout(self):
        from MobileAgent import controller
        import subprocess
        path = Path(controller._runtime_path('snapshot.json')); path.write_text('synthetic stale')
        with patch.object(controller.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['private'], 10)):
            with self.assertRaises(OperationError) as error: controller.pull_transport_snapshot('synthetic adb')
        self.assertEqual(error.exception.code, 'TIMEOUT'); self.assertFalse(path.exists())


class SocketLifecycleTests(unittest.TestCase):
    def harness(self):
        test = freshness.ReaderFreshnessTests(); test.setUp()
        self.addCleanup(test.cleanup_reader); self.addCleanup(test.directory.cleanup)
        return test

    def test_request_deadline_invalidates_blocked_model_and_next_request_succeeds(self):
        test = self.harness(); now = [0.0]
        test.listener.clock = lambda: now[0]; test.listener.policy = FailurePolicy(request=1)
        old = test.begin(); now[0] = 2
        test.listener.expire_requests()
        reply = test.read()
        self.assertEqual(reply['error'], 'DEADLINE_EXCEEDED'); self.assertEqual(reply['requestId'], 'A')
        self.assertTrue(old.cancelled.is_set())
        test.release.set(); self.assertTrue(old.done.wait(2))
        test.ctx['snapshotSeq'] += 1; test.send('INVALIDATE_CONTEXT'); test.wait_context(); test.write_snapshot()
        test.send('REQUEST_UI_UPDATE', 'after-timeout')
        self.assertIn('payload', test.read()); self.assertTrue(test.listener._active.done.wait(2))

    def test_queue_wait_counts_toward_request_budget(self):
        test = self.harness(); now = [0.0]
        test.listener.clock = lambda: now[0]; test.listener.policy = FailurePolicy(request=1)
        old = test.begin(); test.send('REQUEST_UI_UPDATE', 'queued')
        with test.listener._condition:
            self.assertTrue(test.listener._condition.wait_for(lambda: test.listener._pending is not None and test.listener._pending.request_id == 'queued', timeout=2))
        now[0] = 2; test.listener.expire_requests(); replies = [test.read(), test.read()]
        self.assertEqual({reply['requestId'] for reply in replies}, {'A', 'queued'})
        self.assertTrue(all(reply['error'] == 'DEADLINE_EXCEEDED' for reply in replies))
        self.assertIsNone(test.listener._pending); self.assertEqual(test.calls, ['chat'])
        test.release.set(); self.assertTrue(old.done.wait(2))

    def test_real_reader_accepts_split_utf8_and_coalesced_frames(self):
        test = self.harness(); test.block = False
        packet = (json.dumps(demo.message('REQUEST_UI_UPDATE', 'utf8', test.ctx, interaction={'text': '中文'}), ensure_ascii=False) + '\n').encode()
        boundary = packet.index('中'.encode()) + 1
        test.peer.sendall(packet[:boundary]); test.peer.sendall(packet[boundary:])
        self.assertIn('payload', test.read()); self.assertTrue(test.listener._active.done.wait(2))
        self.assertEqual(test.agent.action_history, ['中文'])
        test.agent.chat = lambda *args: '### Thought ### keep ### Mode ### A ### Displayed UI ###'
        packets = b''.join((json.dumps(demo.message('REQUEST_TALK', name, test.ctx, baseRequestId=base)) + '\n').encode() for name, base in [('bad-base', 'unknown'), ('good-base', 'utf8')])
        test.peer.sendall(packets)
        replies = [test.read(), test.read()]
        self.assertEqual({reply['requestId'] for reply in replies}, {'bad-base', 'good-base'})
        self.assertEqual(next(r for r in replies if r['requestId'] == 'good-base')['status'], 'NO_OP')

    def test_malformed_truncated_oversized_and_first_byte_deadline_close_connection(self):
        for data, end in ((b'\xff\n', True), (b'{"type":', True), (b'x' * 65537, False), (b'{', False)):
            test = self.harness()
            test.listener.policy = FailurePolicy(frame=0.03)
            test.peer.sendall(data)
            if end: test.peer.shutdown(socket.SHUT_WR)
            test.readers[0].join(1)
            self.assertFalse(test.readers[0].is_alive())
            self.assertIsNone(test.listener._context)
            self.assertIsNone(test.listener._pending)
            test.cleanup_reader()

    def test_error_response_backpressure_keeps_worker_alive_across_reconnect(self):
        test = self.harness(); test.listener.policy = FailurePolicy(write=0.03, request=1)
        server = test.listener._connection; server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        while True:
            try: server.send(b'x' * 4096)
            except BlockingIOError: break
        exceptions = []
        def fail(*args): raise RuntimeError('synthetic provider failure')
        test.agent.chat = fail
        with patch.object(threading, 'excepthook', lambda args: exceptions.append(args.exc_type.__name__)):
            test.send('REQUEST_UI_UPDATE', 'failed-provider')
            with test.listener._condition:
                self.assertTrue(test.listener._condition.wait_for(lambda: test.listener._active is not None, timeout=2))
                work = test.listener._active
            self.assertTrue(work.done.wait(2)); test.listener._worker.join(0.05)
            self.assertTrue(test.listener._worker.is_alive(), 'error send failure must not kill serial worker')
            self.assertEqual(exceptions, [])
            test.peer.close(); test.readers[0].join(1)
            test.peer = test.connect(); test.ctx = dict(test.ctx, sessionId='00000000-0000-4000-8000-000000000088')
            test.establish(); test.write_snapshot()
            calls = []
            def valid(*args):
                calls.append(1)
                return test.responses[('planning', 'decision', 'classification')[(len(calls) - 1) % 3]]
            test.agent.chat = valid; test.send('REQUEST_UI_UPDATE', 'after-reconnect')
            self.assertIn('payload', test.read()); self.assertEqual(len(calls), 3)

    def test_stop_wakes_idle_reader(self):
        test = self.harness()
        test.listener.stop_worker(); test.readers[0].join(1)
        self.assertFalse(test.readers[0].is_alive())
        self.assertFalse(test.listener._worker.is_alive())
        self.assertFalse(test.listener._reply_worker.is_alive())

    def test_backpressured_write_times_out_without_corrupting_next_frame(self):
        test = self.harness(); test.listener.policy = FailurePolicy(write=0.03)
        server = test.listener._connection
        server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        # A large synthetic body forces a partial write, then timeout and close.
        errors = []
        def send():
            try: test.listener._send_to(server, {'type': 'synthetic', 'padding': 'x' * 1000000})
            except OSError: errors.append('closed')
        thread = threading.Thread(target=send); thread.start(); thread.join(1)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, ['closed'])
        self.assertIsNone(test.listener._context)

class SDKErrorBodyTests(unittest.TestCase):
    def test_real_sdk_rejects_non2xx_without_reading_body_and_keeps_interruptions(self):
        import httpx
        import openai
        from MobileAgent import api
        real_openai, real_http = openai.OpenAI, openai.DefaultHttpxClient
        for mode, status in ((m, s) for m in ('http_error', 'cancelled', 'expired') for s in (302, 429, 500)):
            with self.subTest(mode=mode, status=status):
                interrupted = threading.Event(); stats = {'bytes': 0, 'close': 0}
                class Guard:
                    def check(self):
                        if interrupted.is_set():
                            if mode == 'cancelled': raise Cancelled('synthetic cancelled')
                            if mode == 'expired': raise DeadlineExceeded()
                    def remaining(self): self.check(); return 120
                class Body(httpx.SyncByteStream):
                    def __iter__(self):
                        for _ in range(34):
                            stats['bytes'] += 1024 * 1024
                            yield b'x' * (1024 * 1024)
                    def close(self): stats['close'] += 1
                def handler(request):
                    if mode != 'http_error': interrupted.set()
                    return httpx.Response(status, headers={'location': 'https://offline.test/target'} if status == 302 else {}, stream=Body(), request=request)
                transport = httpx.MockTransport(handler)
                def http_factory(**kwargs): return real_http(transport=transport, **kwargs)
                def sdk_factory(**kwargs):
                    if 'http_client' not in kwargs: kwargs['http_client'] = real_http(transport=transport)
                    return real_openai(**kwargs)
                with patch.object(openai, 'DefaultHttpxClient', http_factory), patch.object(openai, 'OpenAI', sdk_factory), patch.object(api, 'play_audio_file', side_effect=AssertionError('error body cannot play')):
                    with self.assertRaises({'http_error': OperationError, 'cancelled': Cancelled, 'expired': DeadlineExceeded}[mode]) as error:
                        api.text2audio('synthetic', API_TOKEN='nonfunctional-test-token', guard=Guard())
                self.assertEqual(stats['bytes'], 0, 'SDK must not eagerly read an error body')
                self.assertGreaterEqual(stats['close'], 1)
                if mode == 'http_error':
                    self.assertEqual(error.exception.code, 'HTTP_ERROR'); self.assertEqual(error.exception.status, status)

class RequestsRedirectTests(unittest.TestCase):
    def test_real_requests_rejects_redirect_before_response_next_reads_body(self):
        import requests
        from MobileAgent import api
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                stats = {'sent': 0, 'bytes': 0, 'close': 0}
                class Raw(io.BytesIO):
                    def read(self, count=-1):
                        value = super().read(count); stats['bytes'] += len(value); return value
                    def close(self): stats['close'] += 1; super().close()
                def send(adapter, request, **kwargs):
                    stats['sent'] += 1
                    response = requests.Response(); response.request = request; response.url = request.url
                    response.status_code = 302; response.headers['location'] = 'https://offline.test/target'
                    response.raw = Raw(b'x' * (2 * 1024 * 1024)); return response
                with patch.object(requests.adapters.HTTPAdapter, 'send', send), patch.dict('os.environ', {'FOCALFLOW_LEGACY_TTS_API_URL': 'https://offline.test/tts'}):
                    with self.assertRaises(OperationError) as error:
                        if legacy: api.text2audio_old('synthetic', API_TOKEN='nonfunctional-test-token')
                        else: api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'nonfunctional-test-token')
                self.assertEqual(error.exception.code, 'HTTP_ERROR'); self.assertEqual(error.exception.status, 302)
                self.assertEqual(stats['sent'], 1)
                self.assertEqual(stats['bytes'], 0, 'Response.next must not eagerly consume a redirect body')
                self.assertGreaterEqual(stats['close'], 1)
