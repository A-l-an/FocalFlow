"""Real production listener on random loopback ports; no model, ADB or user data."""
import errno
import importlib.util
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
import unittest

from MobileAgent.failure import FailurePolicy
from MobileAgent.protocol import Work
from run import UIListener


TOOLS = Path(__file__).resolve().parents[1] / 'tools/manual_testing'
PRIVATE = 'SYNTHETIC_PRIVATE_HOST_PATH_TOKEN'


def load_tool(name):
    spec = importlib.util.spec_from_file_location('restart_' + name, str(TOOLS / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServerRestartTests(unittest.TestCase):
    def listener(self):
        def forbidden(*args, **kwargs):
            self.fail('unexpected acquisition or business work')
        return UIListener(SimpleNamespace(policy=FailurePolicy()), acquire=forbidden)

    def start(self, listener, port):
        done = threading.Event()
        errors = []
        def serve():
            try:
                listener.run_server(port)
            except Exception as error:
                errors.append(error)
            finally:
                done.set()
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        return worker, done, errors

    def ready(self, listener, done, errors):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            server = listener._server
            if server is not None:
                try:
                    port = server.getsockname()[1]
                    if port:
                        peer = socket.create_connection(('127.0.0.1', port), timeout=.1)
                        peer.settimeout(2)
                        return port, peer
                except OSError:
                    pass
            if done.is_set():
                self.fail('listen failed errno=%s' % ([getattr(error, 'errno', None) for error in errors],))
            time.sleep(.005)
        self.fail('production listener readiness timeout')

    def stop(self, listener, worker):
        listener.stop_worker()
        worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_real_server_active_close_allows_five_immediate_restarts(self):
        port = 0
        for cycle in range(5):
            with self.subTest(cycle=cycle):
                listener = self.listener()
                closed = threading.Event()
                # Substitute only protocol/business handling; real run_server binds,
                # listens, selects and accepts. Force the server side to close first.
                def active_close(client):
                    try:
                        client.settimeout(2)
                        client.shutdown(socket.SHUT_WR)
                        self.assertEqual(client.recv(1), b'')
                    finally:
                        client.close()
                        closed.set()
                listener.read_connection = active_close
                worker, done, errors = self.start(listener, port)
                try:
                    port, peer = self.ready(listener, done, errors)
                    with peer:
                        self.assertEqual(peer.recv(1), b'')
                        peer.shutdown(socket.SHUT_WR)
                        self.assertTrue(closed.wait(2))
                finally:
                    self.stop(listener, worker)
                self.assertEqual(errors, [])

    def test_active_listener_is_rejected_and_never_taken_over(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reserved.bind(('127.0.0.1', 0))
            reserved.listen(1)
            reserved.settimeout(2)
            port = reserved.getsockname()[1]
            listener = self.listener()
            worker, done, errors = self.start(listener, port)
            try:
                self.assertTrue(done.wait(2))
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], OSError)
                self.assertEqual(errors[0].errno, errno.EADDRINUSE)
                with socket.create_connection(('127.0.0.1', port), timeout=2):
                    client, _ = reserved.accept()
                    client.close()
            finally:
                self.stop(listener, worker)

    def test_stop_closes_idle_connection_cancels_owned_work_and_joins_threads(self):
        listener = self.listener()
        worker, done, errors = self.start(listener, 0)
        peer = None
        try:
            port, peer = self.ready(listener, done, errors)
            deadline = time.monotonic() + 2
            while listener.client is None and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertIsNotNone(listener.client)
            request = {'protocolVersion': 1,
                       'context': {'sessionId': '00000000-0000-4000-8000-000000000099',
                                   'taskEpoch': 1, 'snapshotSeq': 1},
                       'requestId': 'synthetic-stop'}
            work = Work(listener, request, listener.client, ('synthetic', 'task'))
            with listener._condition:
                listener._active = work
            self.stop(listener, worker)
            self.assertEqual(peer.recv(1), b'')
            self.assertTrue(work.cancelled.is_set())
            self.assertIsNone(listener._server)
            self.assertIsNone(listener.client)
            self.assertTrue(listener._stopping)
            for thread in (listener._worker, listener._reply_worker):
                self.assertTrue(thread is None or not thread.is_alive())
            self.assertEqual(errors, [])
        finally:
            if peer is not None:
                peer.close()
            self.stop(listener, worker)


class PortErrorTests(unittest.TestCase):
    def test_only_address_in_use_errno_maps_to_fixed_port_error(self):
        runner = load_tool('live_backend')
        result = runner.error_metadata(OSError(errno.EADDRINUSE, PRIVATE, PRIVATE))
        self.assertEqual(result['error_code'], 'PORT_IN_USE')
        self.assertNotIn(PRIVATE, str(result))
        for code in (errno.EACCES, errno.EBADF, errno.ECONNREFUSED, None):
            with self.subTest(errno=code):
                result = runner.error_metadata(OSError(code, PRIVATE, PRIVATE))
                self.assertNotEqual(result.get('error_code'), 'PORT_IN_USE')
                self.assertNotIn(PRIVATE, str(result))

    def test_console_port_failure_hint_is_static_and_does_not_claim_network_failure(self):
        console = load_tool('manual_test').ConsoleEvents()
        lines = console.consume({'event': 'runner_failure', 'stage': 'runner', 'event_id': 1,
                                 'error_code': 'PORT_IN_USE', 'error_message': PRIVATE,
                                 'host': PRIVATE, 'path': PRIVATE})
        text = ' '.join(lines)
        self.assertIn('PORT_IN_USE', text)
        self.assertIn('端口', text)
        self.assertIn('占用', text)
        self.assertNotIn(PRIVATE, text)
        self.assertNotIn('网络', text)
        self.assertEqual(console.failures, 1)
        self.assertEqual(console.counts, {'chat': 0, 'tts': 0})


if __name__ == '__main__':
    unittest.main()
