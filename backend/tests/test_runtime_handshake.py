"""Control READY observation is separate from UI/business replies."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

class RuntimeHandshakeTests(unittest.TestCase):
    def test_ready_emits_control_event_only_after_successful_send(self):
        path=Path(__file__).resolve().parents[1]/'tools/manual_testing/live_backend.py'
        spec=importlib.util.spec_from_file_location('handshake_runtime',str(path));runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
        events=[];result=object()
        listener=SimpleNamespace(_process_message=lambda *a,**k:None,_send_to=lambda *a,**k:result,acquire=lambda *a,**k:None)
        runtime.observe_listener(listener,SimpleNamespace(),lambda event,**kw:events.append((event,kw)))
        obj=dict(type='SESSION_READY',protocolVersion=1,context={'snapshotSeq':0},requestId='synthetic')
        self.assertIs(listener._send_to(None,obj),result)
        self.assertEqual(events[-1][0],'session_ready_sent')
        self.assertEqual(events[-1][1]['protocol_type'],'SESSION_READY')
        self.assertNotIn('success_reply',events[-1][1])
        self.assertNotIn('reply_outcome',events[-1][1])
        self.assertEqual(events[-1][1]['phone_applied'],'unobserved')
        def failed(*a,**k):raise OSError('synthetic send failure')
        listener=SimpleNamespace(_process_message=lambda *a,**k:None,_send_to=failed,acquire=lambda *a,**k:None)
        runtime.observe_listener(listener,SimpleNamespace(),lambda event,**kw:events.append((event,kw)))
        before=len(events)
        with self.assertRaises(OSError):listener._send_to(None,obj)
        self.assertEqual(len(events),before,'failed ACK send cannot claim session readiness')
