"""SESSION_READY control admission uses no provider and writes outside control lock."""
import json
import unittest
from examples import offline_demo as demo
from run import MobileAgentStateMachine, UIListener

class SessionReadyTests(unittest.TestCase):
    def test_role_has_exact_correlated_ready_without_business_calls(self):
        calls, sent, locked = [], [], []
        agent=MobileAgentStateMachine(chat=lambda *a:calls.append('chat'),tts=lambda *a:calls.append('tts'),
            voice=lambda *a:calls.append('voice'),beep=lambda:calls.append('beep'))
        listener=None
        def output(message):
            locked.append(listener._condition._is_owned());sent.append(json.loads(message))
        listener=UIListener(agent,send=output)
        context=dict(demo.CONTEXT,snapshotSeq=0)
        listener._process_message(json.dumps(demo.message('ROLE','first-role',context,PID='synthetic',TaskID='task')))
        self.assertEqual(sent,[dict(type='SESSION_READY',protocolVersion=1,context=context,requestId='first-role')])
        self.assertEqual(calls,[]);self.assertEqual(locked,[False])
        listener._process_message(json.dumps(demo.message('ROLE','duplicate',context,PID='synthetic',TaskID='task')))
        self.assertEqual(len(sent),1,'old/repeated role cannot produce another READY')
        newer=dict(context,taskEpoch=context['taskEpoch']+1)
        listener._process_message(json.dumps(demo.message('ROLE','new-role',newer,PID='synthetic',TaskID='next')))
        self.assertEqual(sent[-1],dict(type='SESSION_READY',protocolVersion=1,context=newer,requestId='new-role'))
        self.assertEqual(calls,[])

    def test_old_ready_blocked_on_writer_cannot_send_or_close_new_task(self):
        import threading
        sent=[];locks=[];listener=None
        def output(frame):locks.append(listener._condition._is_owned());sent.append(json.loads(frame))
        listener=UIListener(MobileAgentStateMachine(),send=output)
        original_connection=listener._connection
        first=dict(demo.CONTEXT,snapshotSeq=0);newer=dict(first,taskEpoch=first['taskEpoch']+1)
        def role(ctx,request):listener._process_message(json.dumps(demo.message('ROLE',request,ctx,PID='synthetic',TaskID='task')))
        listener._send_lock.acquire()
        old=threading.Thread(target=role,args=(first,'old-role'));new=threading.Thread(target=role,args=(newer,'new-role'))
        try:
            old.start()
            with listener._condition:self.assertTrue(listener._condition.wait_for(lambda:listener._context==first,2))
            new.start()
            with listener._condition:self.assertTrue(listener._condition.wait_for(lambda:listener._context==newer,2))
        finally:listener._send_lock.release()
        old.join(2);new.join(2)
        self.assertFalse(old.is_alive() or new.is_alive())
        self.assertEqual(sent,[dict(type='SESSION_READY',protocolVersion=1,context=newer,requestId='new-role')])
        self.assertEqual(locks,[False]);self.assertIs(listener._connection,original_connection)
