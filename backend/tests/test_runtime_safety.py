"""Synthetic checks against real runtime modules; never call live providers."""
import contextlib
import importlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'SYNTHETIC_PRIVATE_PAYLOAD_03'
from examples import offline_demo as demo
from MobileAgent.failure import OperationError
from requests import exceptions as request_errors


class ExternalBoundary(BaseException):
    """Not swallowed by the legacy provider retry loop."""


class RuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.external_calls = 0
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.bind', 'socket.getaddrinfo', 'os.system'):
            self.stack.enter_context(patch(target, self.forbid_external))

    def forbid_external(self, *args, **kwargs):
        self.external_calls += 1
        raise ExternalBoundary('unexpected external boundary')

    def tearDown(self):
        self.assertEqual(self.external_calls, 0)

    def test_fresh_import_and_collection_have_no_optional_io_or_files(self):
        script = r'''
import builtins, importlib, logging, os, pathlib, socket, subprocess, sys
class Forbidden(BaseException): pass
calls = []
def forbid(*args, **kwargs):
    calls.append('external')
    raise Forbidden()
for name in ('connect', 'connect_ex', 'bind'):
    setattr(socket.socket, name, forbid)
socket.getaddrinfo = forbid
subprocess.Popen = forbid
os.system = forbid
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'whisper', 'modelscope', 'dashscope', 'sounddevice', 'soundfile', 'scipy', 'numpy', 'openai', 'PIL'}:
        raise Forbidden('optional dependency imported eagerly: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
before = list(logging.getLogger().handlers)
try:
    runtime = importlib.import_module('run')
    importlib.import_module('MobileAgent.api')
    importlib.import_module('MobileAgent.controller')
    importlib.import_module('test')
    agent = runtime.MobileAgentStateMachine()
    listener = runtime.UIListener(agent)
    assert agent.state == 'waiting'
    assert logging.getLogger().handlers == before
    assert list(pathlib.Path('.').iterdir()) == []
    assert calls == []
except BaseException as exc:
    print(type(exc).__name__ + ': ' + str(exc))
    sys.exit(1)
print('real imports and default construction: external_calls=0; new_files=0')
'''
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT),
               'PYTHONDONTWRITEBYTECODE': '1'}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', script], cwd=directory,
                                    env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('external_calls=0', result.stdout)

    def runtime(self):
        self.stack.enter_context(patch("subprocess.Popen", self.forbid_external))
        return importlib.import_module('run')

    @contextlib.contextmanager
    def capture(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        previous = root.level
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                yield output
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)

    def test_real_decision_parser_with_injected_services_keeps_payload_private(self):
        runtime = self.runtime()
        calls = []
        def chat(messages, model):
            calls.append(('chat', model))
            return '### Thought ###' + MARKER + '### Output ###' + MARKER
        def tts(text):
            calls.append(('tts', text))
        agent = runtime.MobileAgentStateMachine(chat=chat, tts=tts,
                                               voice=self.forbid_external, beep=self.forbid_external)
        agent.curScreenIntro = MARKER
        agent.subtask = MARKER
        agent.ui_layout_info_filtered = {}
        from examples.offline_demo import load_tree
        agent.ui_layout_info_original = load_tree()
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'synthetic.png'
            image.write_bytes(b'synthetic-image-bytes')
            agent.screenshot_file = str(image)
            with self.capture() as output:
                with self.assertRaises(runtime.ValidationError):
                    agent.generate_decision()
        self.assertFalse(hasattr(agent, 'relevantAreaList'))
        self.assertFalse(hasattr(agent, 'thought'))
        self.assertEqual([call[0] for call in calls], ['tts', 'chat'])
        self.assertNotIn(MARKER, output.getvalue())
        self.assertNotIn('JSONDecodeError', output.getvalue())

    def test_listener_error_status_and_all_output_channels_are_private(self):
        runtime = self.runtime()
        agent = runtime.MobileAgentStateMachine(chat=self.forbid_external,
                    tts=self.forbid_external, voice=self.forbid_external, beep=self.forbid_external)
        sent = []
        def acquire(*args, **kwargs):
            raise RuntimeError(MARKER)
        listener = runtime.UIListener(agent, acquire=acquire, send=sent.append)
        with self.capture() as output:
            listener._process_message(json.dumps({'type': MARKER, 'payload': MARKER}))
            listener._process_message(MARKER)
            demo.admit_context(listener)
            listener._process_message(json.dumps(demo.message('REQUEST_UI_UPDATE', 'synthetic-request', interaction={'text': MARKER})))
            listener._process_message(json.dumps(demo.message('REQUEST_TALK', 'synthetic-talk', baseRequestId='synthetic-request')))
        self.assertEqual(len(sent), 2)
        for message in sent:
            obj = json.loads(message)
            self.assertIn(obj['error'], ('RuntimeError', 'INVALID_BASE_OR_BUSY'))
            self.assertNotIn(MARKER, message)
        self.assertEqual(json.loads(sent[0])['requestId'], 'synthetic-request')
        self.assertNotIn(MARKER, output.getvalue())
        self.assertIn('RuntimeError', output.getvalue())

    def test_provider_failure_keeps_exception_and_response_body_private(self):
        api = importlib.import_module('MobileAgent.api')
        attempts = []
        def post(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError(MARKER)
            raise ExternalBoundary('end synthetic retry observation')
        with patch.dict(sys.modules, {'requests': SimpleNamespace(post=post, exceptions=request_errors)}):
            with self.capture() as output:
                with self.assertRaises(OperationError) as rejected:
                    api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'offline-test-token')
        self.assertEqual(len(attempts), 1)
        self.assertNotIn(MARKER, output.getvalue())
        self.assertEqual(rejected.exception.code, 'PROVIDER_ERROR')
        self.assertNotIn(MARKER, str(rejected.exception))

    def test_missing_live_chat_config_fails_before_provider_import(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, 'FOCALFLOW_CHAT_API_URL'):
            runtime.MobileAgentStateMachine().chat([], 'gpt-4')

    def test_acquisition_reuses_owned_temporary_snapshot_without_archiving(self):
        import shlex
        controller = importlib.import_module('MobileAgent.controller')
        def run_command(command, **kwargs):
            parts = shlex.split(command) if isinstance(command, str) else command
            if 'pull' in parts:
                target = Path(parts[-1])
                target.write_bytes(demo.snapshot_text(json.dumps(demo.load_tree())).encode() if target.suffix == '.json' else b'synthetic-image')
            return SimpleNamespace(returncode=0, stderr=MARKER, stdout='')
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            os.chdir(directory)
            try:
                with patch.object(controller.subprocess, 'run', run_command), \
                     patch.object(controller.subprocess, 'check_output', return_value='/synthetic/virtual_tree_current.json'), \
                     patch.object(controller.time, 'sleep'):
                    with self.capture() as output:
                        first = controller.get_screenshot_and_ui_elements('adb', 'synthetic-user', 'synthetic-task', 1, expected_context=demo.CONTEXT)
                        second = controller.get_screenshot_and_ui_elements('adb', 'synthetic-user', 'synthetic-task', 2, expected_context=demo.CONTEXT)
                self.assertEqual(first, second)
                self.assertTrue(all(Path(path).is_file() for path in second))
                self.assertFalse(Path('user_data').exists())
                self.assertNotIn(MARKER, output.getvalue())
            finally:
                os.chdir(previous)

    def test_tts_uses_owned_temporary_file_and_removes_it(self):
        api = importlib.import_module('MobileAgent.api')
        paths = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def iter_bytes(self, **kwargs):
                return iter([b'synthetic-audio'])
        def create(**kwargs):
            return Response()
        client = SimpleNamespace(close=lambda: None, audio=SimpleNamespace(speech=SimpleNamespace(
            with_streaming_response=SimpleNamespace(create=create))))
        def play(path):
            paths.append(Path(path))
            self.assertEqual(Path(path).read_bytes(), b'synthetic-audio')
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, {'openai': SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=lambda **kw: client)}), \
                 patch.object(api, '__file__', str(Path(directory) / 'api.py')), \
                 patch.object(api, 'play_audio_file', play):
                api.text2audio(MARKER, API_TOKEN='nonfunctional-test-token')
            self.assertEqual(len(paths), 1)
            self.assertFalse(paths[0].exists())
            self.assertNotEqual(paths[0].parent, Path(directory))

    def test_voice_recording_temporary_lifetime_and_private_transcript(self):
        api = importlib.import_module('MobileAgent.api')
        paths = []
        data = SimpleNamespace(size=16000)
        def write(path, rate, audio):
            Path(path).write_bytes(b'x' * 1100)
        def transcribe(**kwargs):
            paths.append(Path(kwargs['audio']))
            self.assertTrue(paths[-1].exists())
            return {'text': MARKER}
        modules = {
            'numpy': SimpleNamespace(abs=lambda value: value, max=lambda value: 1000),
            'sounddevice': SimpleNamespace(query_devices=lambda: [
                {'name': MARKER, 'max_input_channels': 1}], rec=lambda *a, **k: data, wait=lambda: None),
            'scipy': SimpleNamespace(),
            'scipy.io': SimpleNamespace(wavfile=SimpleNamespace(write=write)),
        }
        with patch.dict(sys.modules, modules), \
             patch.object(api.subprocess, 'Popen', return_value=None), \
             patch.object(api.subprocess, 'run', return_value=None):
            with self.capture() as output:
                result = api.get_voice(SimpleNamespace(transcribe=transcribe), MARKER)
        self.assertEqual(result, MARKER)
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())
        self.assertNotIn(MARKER, output.getvalue())

    def test_provider_invalid_response_body_is_private(self):
        api = importlib.import_module('MobileAgent.api')
        attempts = []
        response = SimpleNamespace(status_code=200, close=lambda: None,
                                   iter_content=lambda **kwargs: iter([json.dumps({'private': MARKER}).encode()]))
        def post(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return response
            raise ExternalBoundary('end synthetic retry observation')
        with patch.dict(sys.modules, {'requests': SimpleNamespace(post=post, exceptions=request_errors)}):
            with self.capture() as output:
                with self.assertRaises(OperationError) as rejected:
                    api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'offline-test-token')
        self.assertEqual(len(attempts), 1)
        self.assertNotIn(MARKER, output.getvalue())
        self.assertEqual(rejected.exception.code, 'INVALID_RESPONSE')
        self.assertNotIn(MARKER, str(rejected.exception))

    def test_acquisition_error_never_prints_adb_stderr(self):
        controller = importlib.import_module('MobileAgent.controller')
        with patch.object(controller.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stderr=MARKER, stdout=MARKER)):
            with self.capture() as output:
                with self.assertRaises(RuntimeError):
                    controller.get_screenshot_and_ui_elements('adb', 'user', 'task', 1, expected_context=demo.CONTEXT)
        self.assertNotIn(MARKER, output.getvalue())

    def test_default_voice_loads_model_only_on_use_and_reuses_it(self):
        runtime = self.runtime()
        loaded = []
        supplied = []
        model = object()
        def load_model(name):
            loaded.append(name)
            return model
        def record(voice_model, prompt):
            supplied.append(voice_model)
            return 'synthetic transcript'
        with patch.dict(sys.modules, {
                'torch': SimpleNamespace(manual_seed=lambda seed: None),
                'whisper': SimpleNamespace(load_model=load_model)}), \
             patch.object(runtime, 'get_voice', record):
            agent = runtime.MobileAgentStateMachine()
            self.assertEqual(loaded, [])
            agent.voice(agent.v2t_model, 'synthetic prompt')
            agent.voice(agent.v2t_model, 'synthetic prompt')
        self.assertEqual(loaded, ['base'])
        self.assertEqual(supplied, [model, model])

    def test_failed_screencap_still_cleans_owned_remote_file(self):
        controller = importlib.import_module('MobileAgent.controller')
        commands = []
        def run_command(command, **kwargs):
            commands.append(command)
            if 'pull' in command and command[-1].endswith('.json'):
                Path(command[-1]).write_text(demo.snapshot_text(json.dumps(demo.load_tree())))
            return SimpleNamespace(returncode=1 if 'screencap' in command else 0,
                                   stderr=MARKER, stdout='')
        with patch.object(controller.subprocess, 'run', run_command):
            with self.capture() as output:
                with self.assertRaises(OperationError):
                    controller.get_screenshot_and_ui_elements('adb', 'user', 'task', 1, expected_context=demo.CONTEXT)
        self.assertTrue(any(command[1:4] == ['shell', 'rm', '-f'] for command in commands))
        self.assertNotIn(MARKER, output.getvalue())

    def test_remote_cleanup_failure_is_an_explicit_acquisition_error(self):
        import shlex
        controller = importlib.import_module('MobileAgent.controller')
        def run_command(command, **kwargs):
            parts = shlex.split(command) if isinstance(command, str) else command
            if 'pull' in parts:
                Path(parts[-1]).write_bytes(demo.snapshot_text(json.dumps(demo.load_tree())).encode() if parts[-1].endswith('.json') else b'synthetic-image')
            return SimpleNamespace(returncode=1 if 'rm' in parts else 0,
                                   stderr=MARKER, stdout='')
        with patch.object(controller.subprocess, 'run', run_command), \
             patch.object(controller.subprocess, 'check_output', return_value='/synthetic/tree.json'), \
             patch.object(controller.time, 'sleep'):
            with self.capture() as output:
                with self.assertRaises(OperationError):
                    controller.get_screenshot_and_ui_elements('adb', 'user', 'task', 1, expected_context=demo.CONTEXT)
        self.assertIn('cleanup', output.getvalue())
        self.assertNotIn(MARKER, output.getvalue())


if __name__ == '__main__':
    unittest.main()
