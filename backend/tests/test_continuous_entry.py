"""Normal/manual entry contracts; synthetic calls and native fixtures, never live services."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from MobileAgent.failure import OperationError


BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
TOOLS = BACKEND/'tools/manual_testing'


def load(name):
    spec = importlib.util.spec_from_file_location('continuous_' + name, str(TOOLS/(name+'.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModeTests(unittest.TestCase):
    def test_budget_contract_and_strict_modes(self):
        runtime = load('live_backend')
        self.assertEqual(runtime.limits_for_mode('manual'), (600, 24, 12))
        self.assertEqual(runtime.limits_for_mode('normal'), (None, None, None))
        for value in ('daily', '', 'NORMAL', None, True, [], 1):
            with self.subTest(mode=repr(value)), self.assertRaisesRegex(RuntimeError, '^UNKNOWN_ARGUMENT$'):
                runtime.limits_for_mode(value)

    def test_both_entry_parsers_reject_invalid_duplicate_or_missing_modes(self):
        for name in ('manual_test', 'live_backend'):
            module = load(name)
            for args in (['--mode'], ['--mode', 'daily'], ['--mode', 'normal', '--mode', 'manual']):
                with self.subTest(module=name, args=args), self.assertRaisesRegex(RuntimeError, '^UNKNOWN_ARGUMENT$'):
                    module.mode_arguments(args)
            self.assertEqual(module.mode_arguments([]), ('manual', []))
            self.assertEqual(module.mode_arguments(['--mode', 'normal', '--check']), ('normal', ['--check']))

    def test_guardian_cli_transmits_normal_to_child_and_guardian(self):
        launcher = load('manual_test')
        with patch.object(sys, 'argv', ['launcher', '--guardian', '/synthetic/session', '123', '--mode', 'normal']), \
                patch.object(launcher, 'run_guardian', return_value=17) as guardian:
            self.assertEqual(launcher.main(), 17)
        args, kwargs = guardian.call_args
        self.assertEqual(kwargs['mode'], 'normal')
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2][-4:], ['--child', '/synthetic/session', '--mode', 'normal'])

    def test_child_cli_transmits_normal_to_runtime(self):
        launcher = load('manual_test')
        runtime = SimpleNamespace(parse_config=lambda text: {}, live_main=lambda **kwargs: kwargs['mode'])
        with patch.object(sys, 'argv', ['launcher', '--child', '/synthetic/session', '--mode', 'normal']), \
                patch.object(launcher, 'preflight', return_value=runtime), \
                patch.object(launcher, 'CONFIG', SimpleNamespace(read_text=lambda: 'synthetic fixture')), \
                patch.object(launcher, 'network_preflight', return_value=None):
            self.assertEqual(launcher.main(), 'normal')
        self.assertEqual(runtime.ART, Path('/synthetic/session'))

    def test_invalid_launcher_mode_rejected_before_device_or_configuration_boundaries(self):
        launcher = load('manual_test')
        with patch.object(sys, 'argv', ['launcher', '--mode', 'invalid']), \
                patch.object(launcher.subprocess, 'run', side_effect=AssertionError('device boundary reached')), \
                patch.object(launcher, 'runner_module', side_effect=AssertionError('configuration boundary reached')):
            with self.assertRaisesRegex(RuntimeError, '^UNKNOWN_ARGUMENT$'):
                launcher.main()

    def test_normal_console_has_no_manual_budget_hint(self):
        console = load('manual_test').ConsoleEvents(mode='normal')
        text = ' '.join(console.consume({'event': 'call_failure', 'stage': 'chat', 'error_code': 'LIVE_CALL_LIMIT'}))
        self.assertNotIn('10 分钟', text)
        self.assertNotIn('/24', text)
        self.assertNotIn('/12', text)
        self.assertNotIn('本轮调用上限', text)

    def test_guardian_budget_load_failure_reports_static_start_failed_and_keeps_cleanup(self):
        launcher = load('manual_test')
        for error, expected_code in ((RuntimeError('RUNNER_CHANGED'), 'RUNNER_CHANGED'),
                                     (OSError(2, 'SYNTHETIC_PRIVATE_PATH_TOKEN'), 'START_FAILED')):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                (root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':False}))
                r,w=os.pipe()
                try:
                    with patch.object(launcher, 'runner_module', side_effect=error), \
                            patch.object(launcher.subprocess, 'Popen', side_effect=AssertionError('child started before integrity check')), \
                            patch.object(launcher, 'disable_phone_service', return_value='DISABLED') as cleanup, \
                            patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as reverse:
                        self.assertEqual(launcher.run_guardian(root,r,['synthetic-worker'],adb='synthetic-adb',mode='normal'),1)
                    self.assertEqual(cleanup.call_args.args,('synthetic','synthetic-adb'))
                    self.assertEqual(reverse.call_args.args[0],['synthetic-adb','-s','synthetic','reverse','--remove','tcp:9998'])
                    report=json.loads((root/'guardian-cleanup.json').read_text())
                    self.assertEqual(report['reason'],'start_failed')
                    self.assertEqual(report['phone_cleanup'],'DISABLED')
                    self.assertEqual(report['runner_cleanup'],'STOPPED')
                    event=json.loads((root/'live-events.jsonl').read_text())
                    self.assertEqual(event['event'],'runner_failure')
                    self.assertEqual(event['error_code'],expected_code)
                    self.assertNotIn('PRIVATE',json.dumps(event))
                finally:
                    os.close(r);os.close(w)

    def test_runner_changed_console_has_explicit_integrity_hint(self):
        text=' '.join(load('manual_test').ConsoleEvents(mode='normal').consume(
            {'event':'runner_failure','error_code':'RUNNER_CHANGED','message':'SYNTHETIC_PRIVATE_PATH'}))
        self.assertIn('RUNNER_CHANGED',text)
        self.assertIn('校验',text)
        self.assertNotIn('PRIVATE',text)


class CallBudgetTests(unittest.TestCase):
    def wrapped(self, mode):
        runtime = load('live_backend')
        _, chat_limit, tts_limit = runtime.limits_for_mode(mode)
        calls = []
        def chat(*args, **kwargs):
            calls.append('chat')
            return 'synthetic answer'
        def tts(*args, **kwargs):
            calls.append('tts')
            return 'synthetic audio'
        fake = SimpleNamespace(inference_chat=chat, text2audio=tts, OperationError=OperationError)
        counts = runtime.install_call_wrappers(fake, lambda *args, **kwargs: None, 'synthetic-model',
                                              chat_limit=chat_limit, tts_limit=tts_limit)
        return fake, counts, calls

    def test_normal_calls_cross_old_chat_and_tts_limits_and_keep_counts(self):
        fake, counts, calls = self.wrapped('normal')
        for _ in range(26):
            self.assertEqual(fake.inference_chat([], 'synthetic-request', 'synthetic-url', 'synthetic-token'), 'synthetic answer')
        for _ in range(14):
            self.assertEqual(fake.text2audio('synthetic text'), 'synthetic audio')
        self.assertEqual(counts, {'chat': 26, 'tts': 14})
        self.assertEqual(calls, ['chat']*26 + ['tts']*14)

    def test_manual_call_limits_remain_enforced_before_another_external_call(self):
        fake, counts, calls = self.wrapped('manual')
        for _ in range(24):
            fake.inference_chat([], 'synthetic', 'synthetic-url', 'synthetic-token')
        with self.assertRaises(OperationError) as chat:
            fake.inference_chat([], 'synthetic', 'synthetic-url', 'synthetic-token')
        for _ in range(12):
            fake.text2audio('synthetic text')
        with self.assertRaises(OperationError) as tts:
            fake.text2audio('synthetic text')
        self.assertEqual(chat.exception.code, 'LIVE_CALL_LIMIT')
        self.assertEqual(tts.exception.code, 'LIVE_CALL_LIMIT')
        self.assertEqual(counts, {'chat': 24, 'tts': 12})
        self.assertEqual(calls, ['chat']*24 + ['tts']*12)


class ShellEntryTests(unittest.TestCase):
    def test_normal_shell_is_executable_and_works_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root/'synthetic-python'
            fake.write_text('#!'+sys.executable+'\nimport json,os,sys\nprint(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd()}))\n')
            fake.chmod(0o700)
            result = subprocess.run([str(REPO/'scripts/run.sh'), '--check'], cwd=root,
                                    env={'PATH':os.environ['PATH'], 'FOCALFLOW_PYTHON':str(fake)},
                                    capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {'args':['-B','tools/manual_testing/manual_test.py','--mode','normal','--check'], 'cwd':str(BACKEND)})


class RuntimeModeTests(unittest.TestCase):
    def start(self, root, mode):
        values = {'FOCALFLOW_CHAT_API_URL':'https://synthetic.invalid/chat',
                  'FOCALFLOW_CHAT_API_TOKEN':'synthetic-no-key', 'FOCALFLOW_CHAT_MODEL':'synthetic-model',
                  'OPENAI_BASE_URL':'https://api.openai.com/v1', 'OPENAI_API_KEY':'synthetic-no-key',
                  'OPENAI_TTS_MODEL':'gpt-4o-mini-tts', 'OPENAI_TTS_VOICE':'nova'}
        config = root/'fixture-config.env'
        config.write_text('\n'.join(key+'='+value for key,value in values.items()))
        config.chmod(0o600)
        (root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':True}))
        driver = root/'runtime-fixture.py'
        driver.write_text('''import importlib.util,sys,threading,time,types
from pathlib import Path
root=Path(__file__).parent
spec=importlib.util.spec_from_file_location('runtime',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.ART=root;m.TARGET=root/'target.json';m.CONFIG=root/'fixture-config.env'
fake=types.ModuleType('run');fake.OperationError=RuntimeError;fake.adb_path='/NONEXISTENT_SYNTHETIC_ADB'
fake.BURGER_PRESET=object()
def forbidden(*a,**k):raise AssertionError('unexpected model/audio/ADB work')
fake.inference_chat=forbidden;fake.text2audio=forbidden
class Agent:
 def __init__(self,*,task_preset):
  assert task_preset is fake.BURGER_PRESET
  (root/'burger-preset').touch()
class Listener:
 def __init__(self,*a):
  self._server=None;self.closed=threading.Event();self.acquire=forbidden
  self._process_message=lambda *a,**k:None;self._send_to=lambda *a,**k:None
 def ensure_adb_reverse(self,*a):pass
 def run_server(self,*a):
  (root/'runtime-live').touch()
  self.closed.wait(4)
  assert self.closed.is_set(), 'runtime watchdog/STOP did not stop fixture'
 def stop_worker(self):self.closed.set()
fake.MobileAgentStateMachine=Agent;fake.UIListener=Listener;sys.modules['run']=fake
real=time.monotonic;origin=real()
raise SystemExit(m.live_main(mode=sys.argv[2],clock=lambda:(real()-origin)*2000))
''')
        return subprocess.Popen([sys.executable,'-B',str(driver),str(TOOLS/'live_backend.py'),mode],
                                env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def await_live(self, process, root):
        deadline = time.monotonic()+2
        while not (root/'runtime-live').exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertTrue((root/'runtime-live').exists())

    def test_normal_runtime_crosses_old_wall_and_remains_live_until_stop_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);process=self.start(root,'normal')
            try:
                self.await_live(process,root)
                time.sleep(.45)  # More than 600 injected seconds; no benchmark or ten-minute wait.
                self.assertIsNone(process.poll())
                events=[json.loads(line) for line in (root/'live-events.jsonl').read_text().splitlines()]
                self.assertEqual(events[0]['mode'],'normal')
                self.assertIsNone(events[0]['wall_seconds'])
                self.assertIsNone(events[0]['chat_limit'])
                self.assertIsNone(events[0]['tts_limit'])
                self.assertTrue((root/'burger-preset').exists())
                (root/'STOP').touch();process.wait(timeout=3)
                self.assertEqual(process.returncode,0)
                events=[json.loads(line) for line in (root/'live-events.jsonl').read_text().splitlines()]
                self.assertTrue(any(e.get('reason')=='stop_file' for e in events))
                self.assertFalse(any(e.get('reason')=='wall_limit' for e in events))
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=2)

    def test_manual_runtime_retains_old_wall_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);process=self.start(root,'manual')
            try:
                self.await_live(process,root);process.wait(timeout=3)
                self.assertEqual(process.returncode,0)
                events=[json.loads(line) for line in (root/'live-events.jsonl').read_text().splitlines()]
                self.assertEqual((events[0]['wall_seconds'],events[0]['chat_limit'],events[0]['tts_limit']),(600,24,12))
                self.assertTrue(any(e.get('reason')=='wall_limit' for e in events))
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=2)

    def test_normal_runtime_signals_still_stop_without_business_work(self):
        for number in (signal.SIGINT,signal.SIGHUP):
            with self.subTest(signal=number),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);process=self.start(root,'normal')
                try:
                    self.await_live(process,root);process.send_signal(number);process.wait(timeout=3)
                    self.assertEqual(process.returncode,0)
                    events=[json.loads(line) for line in (root/'live-events.jsonl').read_text().splitlines()]
                    self.assertTrue(any(e.get('reason')=='signal' for e in events))
                    self.assertFalse(any(e['event'].startswith('call_') for e in events))
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)


class GuardianModeTests(unittest.TestCase):
    def case(self, mode, child_exit=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':True}))
            state=root/'a11y.txt';state.write_text('other/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService')
            adb=root/'fake-adb'
            adb.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\np=Path(__file__).parent/"a11y.txt"\nassert sys.argv[1:3]==["-s","synthetic"]\nif "get" in sys.argv:print(p.read_text())\nelif "put" in sys.argv:p.write_text(sys.argv[-1])\nelse:raise SystemExit(10)\n')
            adb.chmod(0o700)
            worker=root/'worker.py'
            worker.write_text('import os,time\nfrom pathlib import Path\nr=Path(__file__).parent\n(r/"worker.pid").write_text(str(os.getpid()))\nwhile not (r/"STOP").exists():time.sleep(.01)\n')
            r,w=os.pipe()
            driver='import importlib.util,sys,time;from pathlib import Path;s=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);real=time.monotonic;origin=real();raise SystemExit(m.run_guardian(Path(sys.argv[2]),int(sys.argv[3]),[sys.executable,"-B",sys.argv[4]],adb=sys.argv[5],stop_grace=.05,mode=sys.argv[6],clock=lambda:(real()-origin)*2000))'
            guardian=subprocess.Popen([sys.executable,'-B','-c',driver,str(TOOLS/'manual_test.py'),str(root),str(r),str(worker),str(adb),mode],
                                      pass_fds=(r,),env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'},
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            os.close(r)
            unrelated=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(5)'],start_new_session=True)
            try:
                deadline=time.monotonic()+2
                while not (root/'worker.pid').exists() and guardian.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((root/'worker.pid').exists())
                pid=int((root/'worker.pid').read_text())
                if mode=='normal':
                    time.sleep(.45)
                    self.assertIsNone(guardian.poll())
                    if child_exit:os.kill(pid,signal.SIGKILL)
                    else:os.close(w);w=None
                guardian.wait(timeout=3)
                report=json.loads((root/'guardian-cleanup.json').read_text())
                self.assertEqual(report['runner_cleanup'],'STOPPED')
                self.assertEqual(report['phone_cleanup'],'DISABLED')
                self.assertEqual(state.read_text(),'other/.Service')
                self.assertEqual(report['reason'],'child_exit' if child_exit else 'operator_exit' if mode=='normal' else 'wall_limit')
                self.assertIsNone(unrelated.poll())
            finally:
                if w is not None:os.close(w)
                if guardian.poll() is None:guardian.kill();guardian.wait(timeout=2)
                unrelated.kill();unrelated.wait(timeout=2)

    def test_normal_guardian_survives_old_wall_then_eof_cleans(self):self.case('normal')
    def test_manual_guardian_retains_wall_stop(self):self.case('manual')
    def test_normal_child_death_still_cleans(self):self.case('normal',child_exit=True)


class NormalLauncherTests(unittest.TestCase):
    def test_normal_main_transmits_mode_and_cleans_on_both_signals(self):
        from tests.test_launcher_lifecycle import LauncherMainTests
        for number in (signal.SIGINT,signal.SIGHUP):
            with self.subTest(signal=number),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                process,state=LauncherMainTests.build_case(self,root,True,launch_mode='normal')
                try:
                    deadline=time.monotonic()+3;directory=None
                    while time.monotonic()<deadline and process.poll() is None:
                        matches=list(root.glob('manual-tests/*/worker.pid'))
                        if matches:directory=matches[0].parent;break
                        time.sleep(.01)
                    self.assertIsNotNone(directory)
                    self.assertEqual(json.loads((directory/'worker-mode.json').read_text()),{'mode':'normal'})
                    process.send_signal(number);out,err=process.communicate(timeout=10)
                    self.assertEqual(process.returncode,0,out+err)
                    self.assertEqual(state.read_text(),'other/.Service')
                    self.assertEqual(json.loads((directory/'guardian-cleanup.json').read_text())['runner_cleanup'],'STOPPED')
                    self.assertIn('持续运行',out)
                    self.assertNotIn('10 分钟',out)
                    self.assertNotIn('/24',out);self.assertNotIn('/12',out)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)


if __name__ == '__main__':
    unittest.main()
