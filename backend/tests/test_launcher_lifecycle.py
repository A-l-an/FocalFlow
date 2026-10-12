"""Offline launcher supervision, safe cleanup and operator errors; no real ADB/API."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import re
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = Path(os.environ.get('FOCALFLOW_LAUNCHER_SOURCE', str(Path(__file__).resolve().parents[1] / 'tools/manual_testing/manual_test.py')))
def load():
    spec=importlib.util.spec_from_file_location('manual_launcher_under_test', str(SOURCE))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ConsoleTests(unittest.TestCase):
    def test_reason_code_and_event_id_are_safe_and_deduplicated(self):
        module=load()
        self.assertTrue(hasattr(module,'ConsoleEvents'), 'launcher lacks sanitized stage/cause rendering')
        console=module.ConsoleEvents()
        event={'event':'call_failure','time_utc':'2026-10-12T15:00:03Z','event_id':8,
               'stage':'chat','call_number':1,'error_code':'NETWORK_ERROR','cause_code':'PROXY_ERROR',
               'message':'https://PRIVATE_URL?token=PRIVATE_TOKEN','error_class':'PRIVATE_URL'}
        lines=console.consume(event)
        rendered=' '.join(lines)
        for wanted in ('15:00:03','chat','NETWORK_ERROR','PROXY_ERROR','#8','代理'):
            self.assertIn(wanted,rendered)
        self.assertNotIn('PRIVATE',rendered)
        self.assertEqual(console.consume(dict(event,event='reply_sent',error_code='NETWORK_ERROR',success_reply=False)),[])
        self.assertEqual(console.failures,1)
        self.assertIn('LIVE_CALL_LIMIT',' '.join(console.consume(dict(event,event_id=9,error_code='LIVE_CALL_LIMIT'))))

    def test_role_is_not_ready_proof_and_ready_control_does_not_count_failure(self):
        console=load().ConsoleEvents()
        console.consume({'event':'protocol_received','protocol_type':'ROLE'})
        self.assertFalse(console.connected,'ROLE reception alone does not prove protocol readiness')
        lines=console.consume({'event':'session_ready_sent','protocol_type':'SESSION_READY','event_id':2,'time_utc':'2026-10-13T01:00:00Z'})
        self.assertTrue(console.connected)
        self.assertTrue(lines)
        self.assertEqual(console.failures,0)
        self.assertEqual(console.counts,{'chat':0,'tts':0})

    def test_whitelist_discards_hostile_stage_error_and_cause(self):
        module=load();self.assertTrue(hasattr(module,'ConsoleEvents'))
        line=' '.join(module.ConsoleEvents().consume({'event':'call_failure','stage':'PRIVATE_URL',
            'error_code':'https://PRIVATE_TOKEN','cause_code':'PRIVATE_TOKEN','time_utc':'PRIVATE_URL'}))
        self.assertNotIn('PRIVATE',line)

class NetworkPreflightTests(unittest.TestCase):
    def session(self, failure=None):
        from unittest.mock import MagicMock
        session=MagicMock();session.trust_env=True
        session.merge_environment_settings.return_value={
            'proxies':{'https':'http://synthetic.proxy:7890'},'stream':True,
            'verify':'synthetic_ca.pem','cert':None}
        response=MagicMock();response.status_code=405
        if failure is not None:session.get.side_effect=failure
        else:session.get.return_value=response
        return session,response
    def test_dns_failure_is_content_free_and_honors_request_route(self):
        import socket
        from requests.exceptions import ConnectionError
        from unittest.mock import patch
        module=load()
        error=ConnectionError('PRIVATE_HOST_TOKEN');error.__cause__=socket.gaierror(8,'PRIVATE_HOST_TOKEN')
        session,response=self.session(error)
        with patch('requests.Session',return_value=session), \
                patch.object(module.socket,'getaddrinfo',side_effect=socket.gaierror(8,'PRIVATE_HOST_TOKEN')):
            result=module.probe_chat_endpoint('https://PRIVATE_HOST/chat?key=PRIVATE_TOKEN')
        self.assertEqual(result,{'reachable':False,'cause_code':'DNS_ERROR'})
        self.assertTrue(session.get.called, 'probe must use same proxy selection as production')
        self.assertNotIn('PRIVATE',json.dumps(result))
    def test_http_success_uses_proxy_ca_and_never_netrc_credentials(self):
        import socket
        from unittest.mock import patch
        module=load();session,response=self.session()
        with patch('requests.Session',return_value=session), \
                patch.object(module.socket,'getaddrinfo',side_effect=socket.gaierror(8,'PRIVATE_HOST_TOKEN')):
            result=module.probe_chat_endpoint('https://synthetic.invalid/chat')
        self.assertEqual(result,{'reachable':True,'layers':'HTTP_ONLY','http_status':405})
        options=session.get.call_args.kwargs
        self.assertEqual(options['proxies'],{'https':'http://synthetic.proxy:7890'})
        self.assertEqual(options['verify'],'synthetic_ca.pem')
        self.assertFalse(session.trust_env,'netrc credentials are never loaded for probe')
        self.assertNotIn('auth',options);self.assertNotIn('headers',options)
        self.assertEqual(response.close.call_count,1)

class ApprovedModelConfigTests(unittest.TestCase):
    def test_explicit_model_selection_is_preserved_and_malformed_id_rejected(self):
        spec=importlib.util.spec_from_file_location('runtime_under_test',str(SOURCE.with_name('live_backend.py')))
        runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
        values={'FOCALFLOW_CHAT_API_URL':'https://api.openai.com/v1/chat/completions',
            'FOCALFLOW_CHAT_API_TOKEN':'synthetic-no-key','FOCALFLOW_CHAT_MODEL':'synthetic-approved-luna',
            'OPENAI_BASE_URL':'https://api.openai.com/v1','OPENAI_API_KEY':'synthetic-no-key',
            'OPENAI_TTS_MODEL':'gpt-4o-mini-tts','OPENAI_TTS_VOICE':'nova'}
        text='\n'.join(k+'='+v for k,v in values.items())
        self.assertEqual(runtime.parse_config(text)['FOCALFLOW_CHAT_MODEL'],'synthetic-approved-luna')
        for model in ('bad/model','bad:model','bad model',''):
            changed=dict(values,FOCALFLOW_CHAT_MODEL=model)
            with self.assertRaises(ValueError):runtime.parse_config('\n'.join(k+'='+v for k,v in changed.items()))

class GuardianTests(unittest.TestCase):
    def setup_case(self, folder, mode):
        module=load();self.assertTrue(hasattr(module,'run_guardian'), 'launcher lacks independent operator-liveness guardian')
        root=Path(folder);(root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':True}))
        state=root/'a11y.txt';state.write_text('other.reader/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService:other.switch/.Service:com.android.talkback/com.google.android.marvin.talkback.TalkBackService')
        adb=root/'fake_adb.py'
        adb.write_text('#!'+sys.executable+'\n'+'''import sys
from pathlib import Path
root=Path(__file__).parent
args=sys.argv[1:]
if args[:2]!=['-s','synthetic']: raise SystemExit(9)
args=args[2:]
if args==['shell','settings','get','secure','enabled_accessibility_services']: print((root/'a11y.txt').read_text())
elif args[:5]==['shell','settings','put','secure','enabled_accessibility_services']: (root/'a11y.txt').write_text(args[5])
else: raise SystemExit(10)
''');adb.chmod(0o700)
        worker=root/'worker.py';worker.write_text('''import os,signal,time
from pathlib import Path
root=Path(__file__).parent
(root/'worker.pid').write_text(str(os.getpid()))
signal.signal(signal.SIGTERM,signal.SIG_IGN)
while True: time.sleep(.05)
''')
        control=root/'controller.py';control.write_text('''import importlib.util,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[2]);source=sys.argv[1]
spec=importlib.util.spec_from_file_location('launcher',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
r,w=os.pipe()
code="import importlib.util,sys;spec=importlib.util.spec_from_file_location('launcher',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);raise SystemExit(m.run_guardian(__import__('pathlib').Path(sys.argv[2]),int(sys.argv[3]),[sys.executable,sys.argv[4]],adb=sys.argv[5],stop_grace=.2))"
g=subprocess.Popen([sys.executable,'-B','-c',code,source,str(root),str(r),str(root/'worker.py'),str(root/'fake_adb.py')],pass_fds=(r,),start_new_session=True)
os.close(r);(root/'guardian.pid').write_text(str(g.pid))
while True: time.sleep(.05)
''')
        parent=subprocess.Popen([sys.executable,'-B',str(control),str(SOURCE),str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+5
        while not (root/'worker.pid').exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue((root/'worker.pid').exists(),'synthetic worker started')
        worker_pid=int((root/'worker.pid').read_text())
        guardian_pid=int((root/'guardian.pid').read_text())
        try:
            if mode=='parent_kill': parent.kill();parent.wait(timeout=2)
            else: os.kill(worker_pid,signal.SIGKILL)
            deadline=time.monotonic()+5
            while not (root/'guardian-cleanup.json').exists() and time.monotonic()<deadline: time.sleep(.02)
            self.assertTrue((root/'guardian-cleanup.json').exists(),'guardian completed bounded cleanup')
            report=json.loads((root/'guardian-cleanup.json').read_text())
            self.assertEqual(report['phone_cleanup'],'DISABLED')
            self.assertEqual(state.read_text(),'other.reader/.Service:other.switch/.Service','other accessibility services preserved')
            with self.assertRaises(ProcessLookupError): os.kill(worker_pid,0)
        finally:
            if parent.poll() is None: parent.kill();parent.wait(timeout=2)
            for pid in (guardian_pid,worker_pid):
                try: os.kill(pid,signal.SIGKILL)
                except ProcessLookupError: pass

    def test_parent_sigkill_stops_stubborn_child_and_preserves_other_services(self):
        with tempfile.TemporaryDirectory(prefix='focalflow-guardian-parent-') as folder:self.setup_case(folder,'parent_kill')
    def test_child_sigkill_triggers_safe_phone_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='focalflow-guardian-child-') as folder:self.setup_case(folder,'child_kill')
    def test_startup_failure_cleans_target_only(self):
        module=load();self.assertTrue(hasattr(module,'run_guardian'))
        with tempfile.TemporaryDirectory(prefix='focalflow-guardian-startup-') as folder:
            root=Path(folder);(root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':True}))
            # Exact executable boundary; credentials and devices are absent.
            adb=root/'fake_adb.py';state=root/'a11y.txt';state.write_text('other/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService')
            adb.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\np=Path(__file__).parent/"a11y.txt"\nif "get" in sys.argv: print(p.read_text())\nelse: p.write_text(sys.argv[-1])\n');adb.chmod(0o700)
            r,w=os.pipe()
            try: result=module.run_guardian(root,r,['/nonexistent-synthetic-worker'],adb=str(adb),stop_grace=.2)
            finally:os.close(r);os.close(w)
            self.assertEqual(result,1);self.assertEqual(state.read_text(),'other/.Service')

class GuardianOwnershipTests(unittest.TestCase):
    def process_case(self, mode, accelerated=False):
        with tempfile.TemporaryDirectory(prefix='focalflow-guardian-owned-') as folder:
            root=Path(folder);(root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':True}))
            state=root/'a11y.txt';state.write_text('other/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService')
            adb=root/'fake_adb.py';adb.write_text('#!'+sys.executable+'\n'+"import sys\nfrom pathlib import Path\np=Path(__file__).parent/'a11y.txt'\nif 'get' in sys.argv:print(p.read_text())\nelse:p.write_text(sys.argv[-1])\n");adb.chmod(0o700)
            descendant=root/'descendant.py';descendant.write_text("import signal,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nPath(__file__).with_suffix('.ready').touch()\nwhile True:time.sleep(.02)\n")
            worker=root/'worker.py';worker.write_text("import os,subprocess,sys,time\nfrom pathlib import Path\nr=Path(__file__).parent\np=subprocess.Popen([sys.executable,'-B',str(r/'descendant.py')])\nwhile not (r/'descendant.ready').exists():time.sleep(.01)\n(r/'descendant.pid').write_text(str(p.pid))\n(r/'worker.pid').write_text(str(os.getpid()))\nwhile not (r/'STOP').exists():time.sleep(.02)\n")
            r,w=os.pipe()
            code="import importlib.util,sys;from pathlib import Path;s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            if accelerated:code+="clock=m.time.monotonic;m.time.monotonic=lambda:clock()*2000;"
            code+="raise SystemExit(m.run_guardian(Path(sys.argv[2]),int(sys.argv[3]),[sys.executable,'-B',sys.argv[4]],adb=sys.argv[5],stop_grace=.05))"
            guardian=subprocess.Popen([sys.executable,'-B','-c',code,str(SOURCE),str(root),str(r),str(worker),str(adb)],pass_fds=(r,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            os.close(r)
            unrelated=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],start_new_session=True)
            worker_pid=None;descendant_pid=None
            try:
                deadline=time.monotonic()+4
                while not (root/'worker.pid').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue((root/'worker.pid').exists(),'real worker/descendant started')
                worker_pid=int((root/'worker.pid').read_text());descendant_pid=int((root/'descendant.pid').read_text())
                if mode=='kill_leader':os.kill(worker_pid,signal.SIGKILL)
                elif mode=='normal_stop':os.close(w);w=None
                if mode=='wall':
                    deadline=time.monotonic()+1.2
                    while not (root/'guardian-cleanup.json').exists() and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue((root/'guardian-cleanup.json').exists(),'guardian total wall deadline includes blocked startup and cleanup')
                guardian.wait(timeout=4)
                report=json.loads((root/'guardian-cleanup.json').read_text())
                self.assertEqual(report['phone_cleanup'],'DISABLED');self.assertEqual(state.read_text(),'other/.Service')
                if mode=='wall':self.assertEqual(report['reason'],'wall_limit')
                elif mode=='normal_stop':self.assertEqual(report['runner_exit'],0,'cooperative leader exits before descendant cleanup')
                deadline=time.monotonic()+2
                alive=True
                while time.monotonic()<deadline:
                    try:os.kill(descendant_pid,0)
                    except ProcessLookupError:alive=False;break
                    time.sleep(.02)
                self.assertFalse(alive,'owned descendant must not survive guardian exit')
                self.assertIsNone(unrelated.poll(),'unrelated process group stays alive')
            finally:
                if w is not None:os.close(w)
                if guardian.poll() is None:
                    try:guardian.wait(timeout=2)
                    except subprocess.TimeoutExpired:guardian.kill();guardian.wait(timeout=2)
                if worker_pid:
                    try:os.killpg(worker_pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                if descendant_pid:
                    try:os.kill(descendant_pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                unrelated.kill();unrelated.wait(timeout=2)

    def test_killed_leader_still_cleans_owned_descendant_group(self):self.process_case('kill_leader')
    def test_normal_stop_cleans_descendants_after_cooperative_leader_exit(self):self.process_case('normal_stop')
    def test_guardian_wall_limit_is_independent_of_startup_watchdog(self):self.process_case('wall',accelerated=True)

class GuardianCleanupFailureTests(unittest.TestCase):
    def test_group_stop_failure_still_cleans_phone_reverse_and_writes_safe_report(self):
        module=load()
        with tempfile.TemporaryDirectory(prefix='focalflow-guardian-stop-failure-') as folder:
            root=Path(folder);(root/'target.json').write_text(json.dumps({'serial':'synthetic','had_reverse':False}))
            state=root/'a11y.txt';state.write_text('other/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService')
            adb=root/'fake_adb.py';adb.write_text('#!'+sys.executable+'\n'+"import sys\nfrom pathlib import Path\nr=Path(__file__).parent\np=r/'a11y.txt'\nif 'get' in sys.argv:print(p.read_text())\nelif 'put' in sys.argv:p.write_text(sys.argv[-1])\nelif 'reverse' in sys.argv:(r/'reverse-removed').touch()\nelse:raise SystemExit(9)\n");adb.chmod(0o700)
            def fail_owned_group(*args):raise PermissionError(1,'SYNTHETIC_PRIVATE_GROUP_SECRET')
            module.signal_owned_group=fail_owned_group
            r,w=os.pipe()
            try:
                try:result=module.run_guardian(root,r,[sys.executable,'-B','-c','pass'],adb=str(adb),stop_grace=.05)
                except Exception:self.fail('stop failure skipped required phone/reverse/report cleanup')
            finally:os.close(r);os.close(w)
            report=json.loads((root/'guardian-cleanup.json').read_text())
            self.assertEqual(result,1)
            self.assertEqual(report['runner_cleanup'],'UNVERIFIED')
            self.assertEqual(report['phone_cleanup'],'DISABLED')
            self.assertEqual(state.read_text(),'other/.Service')
            self.assertTrue((root/'reverse-removed').exists())
            self.assertNotIn('PRIVATE',json.dumps(report))

class LauncherMainTests(unittest.TestCase):
    def build_case(self, root, reachable, stop_failure=False):
        import hashlib
        module=load();copy=root/'manual_test.py'
        config=root/'providers.env';config.write_text('synthetic non-secret fixture');config.chmod(0o600)
        runtime=root/'live_backend.py';runtime.write_text("""import json,os,time
from pathlib import Path
ART=None
TARGET=None
def parse_config(text):return {'FOCALFLOW_CHAT_API_URL':'https://synthetic.invalid/chat'}
def live_main():
 (ART/'worker.pid').write_text(str(os.getpid()))
 (ART/'proxy.json').write_text(json.dumps({key:os.environ.get(key) for key in ('HTTPS_PROXY','NO_PROXY')}))
 (ART/'live-events.jsonl').write_text(json.dumps({'event':'runner_ready','event_id':1,'time_utc':'2026-10-12T15:00:00Z'})+'\\n')
 while not (ART/'STOP').exists():time.sleep(.05)
 return 0
""")
        state=root/'a11y.txt';state.write_text('other/.Service:com.android.talkback/com.google.android.accessibility.talkback.TalkBackService')
        adb=root/'fake_adb.py';adb.write_text('#!'+sys.executable+'\n'+"""import sys
from pathlib import Path
p=Path(__file__).parent/'a11y.txt'
a=sys.argv[1:]
if a==['devices']:print('List of devices attached\\nsynthetic\\tdevice')
elif a[-2:]==['reverse','--list']:pass
elif 'get' in a:print(p.read_text())
elif 'put' in a:p.write_text(a[-1])
else:pass
""");adb.chmod(0o700)
        source=SOURCE.read_text()
        # Inject paths before module execution/function defaults bind, and fail
        # closed if the entry-point layout changes. Never use real ADB/config.
        assignments = {
            'SOURCE': 'Path('+repr(str(SOURCE.resolve().parents[2]))+')',
            'BASE': 'Path('+repr(str(root))+')',
            'PYTHON': repr(sys.executable),
            'CONFIG': 'Path('+repr(str(config))+')',
            'ADB': repr(str(adb)),
            'RUNNER_SHA': repr(hashlib.sha256(runtime.read_bytes()).hexdigest()),
        }
        for name, expression in assignments.items():
            replacement = name+' = '+expression
            source, changed = re.subn(r'^'+name+r' = .+$', lambda match: replacement, source, flags=re.M)
            self.assertEqual(changed, 1, 'synthetic '+name+' injection must apply exactly once')
            self.assertIn(replacement, source)
        if stop_failure: source=source.replace('def signal_owned_group(child, number):', "def signal_owned_group(child, number):\n    raise PermissionError(1, 'SYNTHETIC_PRIVATE_GROUP_SECRET')")
        if not reachable: source=source.replace("time.sleep(0.1)","time.sleep(1.0)")
        copy.write_text(source)
        # Only the external socket probe is replaced in every child process. Main,
        # pipe ownership, process launch and cleanup are unchanged production code.
        (root/'sitecustomize.py').write_text("""import socket
class ProbeSocket:
 def __enter__(self):return self
 def __exit__(self,*a):return False
"""+('socket.getaddrinfo=lambda *a,**k:[]\nsocket.create_connection=lambda *a,**k:ProbeSocket()\n' if reachable else "def failed(*a,**k):raise socket.gaierror(8,'PRIVATE_HOST_TOKEN')\nsocket.getaddrinfo=failed\n"))
        with (root/'sitecustomize.py').open('a') as site:
            site.write("""import requests
class Response:
 status_code=405
 def close(self):pass
class Session:
 trust_env=True
 def merge_environment_settings(self,*a):return {'proxies':{},'stream':True,'verify':True,'cert':None}
 def get(self,*a,**kw):
"""+('  return Response()\n' if reachable else "  e=requests.exceptions.ConnectionError('PRIVATE_HOST_TOKEN');e.__cause__=socket.gaierror(8,'PRIVATE_HOST_TOKEN');raise e\n")+" def close(self):pass\nrequests.Session=Session\n")
        process=subprocess.Popen([sys.executable,'-B',str(copy)],env=dict(os.environ,PYTHONPATH=str(root),HTTPS_PROXY='http://synthetic.proxy:8877',NO_PROXY='synthetic.local'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        return process,state

    def test_dns_startup_failure_is_printed_even_if_runner_exits_before_poll(self):
        with tempfile.TemporaryDirectory(prefix='focalflow-main-dns-') as folder:
            process,state=self.build_case(Path(folder),False)
            output,error=process.communicate(timeout=10)
            self.assertEqual(process.returncode,1)
            self.assertIn('DNS_ERROR',output)
            self.assertIn('域名无法解析',output)
            self.assertIn('聊天 0/24',output)
            self.assertIn('失败 1',output)
            self.assertNotIn('PRIVATE',output+error)
            self.assertEqual(state.read_text(),'other/.Service')

    def test_main_stop_failure_reports_unverified_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory(prefix='focalflow-main-stop-failure-') as folder:
            root=Path(folder);process,state=self.build_case(root,True,stop_failure=True)
            try:
                deadline=time.monotonic()+5
                while not list(root.glob('manual-tests/*/worker.pid')) and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(list(root.glob('manual-tests/*/worker.pid')))
                process.send_signal(signal.SIGINT);output,error=process.communicate(timeout=10)
                self.assertEqual(process.returncode,1)
                self.assertIn('GROUP_STOP_FAILED',output)
                self.assertNotIn('电脑端已停止',output)
                self.assertNotIn('PRIVATE',output+error)
                self.assertEqual(state.read_text(),'other/.Service')
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=2)

    def test_normal_ctrlc_and_hangup_cleanup_through_real_main(self):
        for signum in (signal.SIGINT,signal.SIGHUP):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory(prefix='focalflow-main-stop-') as folder:
                root=Path(folder);process,state=self.build_case(root,True)
                deadline=time.monotonic()+5;directory=None
                while time.monotonic()<deadline:
                    matches=list(root.glob('manual-tests/*/worker.pid'))
                    if matches:directory=matches[0].parent;break
                    time.sleep(.02)
                try:
                    self.assertIsNotNone(directory,'actual main child is live')
                    self.assertEqual(json.loads((directory/'proxy.json').read_text()), {'HTTPS_PROXY':'http://synthetic.proxy:8877','NO_PROXY':'synthetic.local'})
                    process.send_signal(signum);output,error=process.communicate(timeout=10)
                    self.assertEqual(process.returncode,0)
                    self.assertEqual(state.read_text(),'other/.Service')
                    self.assertEqual(json.loads((directory/'guardian-cleanup.json').read_text())['phone_cleanup'],'DISABLED')
                    self.assertIn('手机 FocalFlow 无障碍服务已关闭',output)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=2)

if __name__=='__main__':unittest.main()
