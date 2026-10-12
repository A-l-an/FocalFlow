"""Synthetic production admission/reader cancellation regressions."""
import json
import unittest
from run import MobileAgentStateMachine, UIListener


class FreshnessTests(unittest.TestCase):
    def test_missing_context_never_acquires_or_sends(self):
        calls, sent = [], []
        def acquire(*args, **kwargs):
            calls.append('acquire')
            raise RuntimeError('synthetic')
        listener = UIListener(MobileAgentStateMachine(), acquire=acquire, send=sent.append)
        listener._process_message(json.dumps({'type': 'REQUEST_UI_UPDATE', 'requestId': 'legacy'}))
        self.assertEqual(calls, [])
        self.assertEqual(sent, [])

import contextlib
import io
import socket
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from examples import offline_demo as demo
from MobileAgent.protocol import Cancelled, read_snapshot


class ReaderFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='focalflow-freshness-')
        self.addCleanup(self.directory.cleanup)
        self.tree_path = Path(self.directory.name) / 'snapshot.json'
        self.image = Path(self.directory.name) / 'image.png'
        self.image.write_bytes((demo.FIXTURES / 'synthetic.png').read_bytes())
        self.ctx = dict(demo.CONTEXT)
        self.write_snapshot()
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls, self.speeches = [], []
        self.responses = demo.load_responses()
        self.block = True
        self.stage = 0
        def chat(messages, model):
            self.calls.append('chat')
            if self.block:
                self.block = False
                self.entered.set()
                if not self.release.wait(3):
                    raise RuntimeError('test gate timed out')
                if not self.agent.guard.cancelled.is_set(): self.stage += 1
                return self.responses['planning']
            stage = ('planning', 'decision', 'classification')[self.stage % 3]
            self.stage += 1
            return self.responses[stage]
        def acquire(*args, **kwargs):
            return str(self.image), str(self.tree_path)
        from MobileAgent.task_presets import BURGER_PRESET
        preset = BURGER_PRESET if self._testMethodName == 'test_burger_task_keeps_goal_and_choices_across_screens_and_cancelled_work' else None
        self.agent = MobileAgentStateMachine(task_preset=preset, chat=chat, tts=self.speeches.append,
            voice=lambda *args: 'synthetic voice', beep=lambda: self.calls.append('beep'))
        self.listener = UIListener(self.agent, acquire=acquire)
        self.peers, self.readers = [], []
        self.peer = self.connect()
        self.addCleanup(self.cleanup_reader)
        self.establish()

    def cleanup_reader(self):
        self.release.set()
        for peer in self.peers:
            peer.close()
        for reader in self.readers:
            reader.join(2)
        self.listener.stop_worker()

    def connect(self):
        peer, server = socket.socketpair()
        peer.settimeout(3)
        reader = threading.Thread(target=self.listener.read_connection, args=(server,), daemon=True)
        reader.start()
        self.peers.append(peer); self.readers.append(reader)
        return peer

    def write_snapshot(self):
        self.tree_path.write_text(demo.snapshot_text(json.dumps(demo.load_tree()), self.ctx))

    def send(self, kind, request_id='control', **fields):
        self.peer.sendall((json.dumps(demo.message(kind, request_id, self.ctx, **fields)) + '\n').encode())

    def wait_context(self):
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(lambda: self.listener._context == self.ctx, timeout=2))

    def establish(self):
        current = self.ctx
        self.ctx = dict(current, snapshotSeq=0)
        self.send('ROLE', PID='synthetic', TaskID='task')
        self.wait_context()
        self.assertEqual(self.read(), dict(type='SESSION_READY',protocolVersion=1,context=self.ctx,requestId='control'))
        self.ctx = current
        self.send('INVALIDATE_CONTEXT')
        self.wait_context()

    def begin(self, request_id='A'):
        self.send('REQUEST_UI_UPDATE', request_id, interaction={'text': request_id})
        self.assertTrue(self.entered.wait(2))
        return self.listener._active

    def read(self):
        data = b''
        while not data.endswith(b'\n'):
            data += self.peer.recv(1)
        return json.loads(data)

    def assert_silent(self):
        import select
        self.assertEqual(select.select([self.peer], [], [], 0)[0], [])

    def test_ordinary_successor_waits_for_active_chain(self):
        self.block = False
        original = self.agent.chat
        def held(messages, model):
            if not self.entered.is_set():
                self.entered.set()
                self.assertTrue(self.release.wait(3))
            return original(messages, model)
        self.agent.chat = held
        old = self.begin()
        self.send('REQUEST_UI_UPDATE', 'B')
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'B', timeout=2))
        self.assertIs(self.listener._active, old, 'queued successor must not take active ownership')
        self.assertFalse(old.cancelled.is_set())
        self.release.set()
        self.assertEqual([self.read()['requestId'], self.read()['requestId']], ['A', 'B'])
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(len(self.agent.subtask_history), 2)

    def test_success_is_delivered_only_after_beep_and_survives_next_capture(self):
        self.block = False
        beep_entered, beep_release = threading.Event(), threading.Event()
        self.addCleanup(beep_release.set)
        def beep():
            if not beep_entered.is_set():
                beep_entered.set()
                self.assertTrue(beep_release.wait(3))
        self.agent.beep = beep
        self.send('REQUEST_UI_UPDATE', 'A')
        self.assertTrue(beep_entered.wait(2))
        self.assert_silent()  # A response is terminal, not an early state-machine notification.
        beep_release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        self.ctx['snapshotSeq'] += 1
        self.send('INVALIDATE_CONTEXT'); self.wait_context(); self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'B')
        self.assertEqual(self.read()['requestId'], 'B')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(len(self.agent.subtask_history), 2)

    def test_success_history_survives_context_advance_inside_send_return(self):
        self.block = False
        delivered = threading.Event()
        original = self.listener._send_to
        def send_and_advance(connection, obj, guard=None):
            original(connection, obj, guard)
            if obj.get('requestId') == 'A' and 'payload' in obj:
                self.ctx = dict(self.ctx, snapshotSeq=self.ctx['snapshotSeq'] + 1)
                self.listener._process_message(json.dumps(demo.message('INVALIDATE_CONTEXT', 'next-capture', self.ctx)), connection)
                delivered.set()
        self.listener._send_to = send_and_advance
        self.send('REQUEST_UI_UPDATE', 'A')
        self.assertEqual(self.read()['requestId'], 'A')
        self.assertTrue(delivered.wait(2))
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(len(self.agent.subtask_history), 1, 'delivered success cannot roll back at send return')
        self.assertIsNotNone(self.agent.ui_layout_info_focused)
        self.write_snapshot(); self.send('REQUEST_UI_UPDATE', 'B')
        self.assertEqual(self.read()['requestId'], 'B')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(len(self.agent.subtask_history), 2)

    def hold_success_send_return(self):
        self.block = False
        delivered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = self.listener._send_to
        def held(connection, obj, guard=None):
            original(connection, obj, guard)
            if obj.get('requestId') == 'A' and 'payload' in obj:
                delivered.set()
                self.assertTrue(release.wait(3))
        self.listener._send_to = held
        self.send('REQUEST_UI_UPDATE', 'A')
        self.assertIn('payload', self.read())
        self.assertTrue(delivered.wait(2))
        return self.listener._active, release

    def test_delivered_success_admits_talk_before_worker_returns(self):
        work, release = self.hold_success_send_return()
        self.assertFalse(work.done.is_set(), 'test holds physical worker return after delivery')
        self.agent.chat = lambda *args: self.responses['talk']
        self.send('REQUEST_TALK', 'after-success', baseRequestId='A')
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None, timeout=1),
                'valid Talk after delivered success must be admitted to pending')
            self.assertEqual(self.listener._pending.request_id, 'after-success')
        self.assert_silent()
        release.set()
        response = self.read()
        self.assertEqual(response['requestId'], 'after-success')
        self.assertIn('payload', response)
        self.assertTrue(self.listener._active.done.wait(2))

    def test_delivered_success_cannot_expire_before_worker_returns(self):
        work, release = self.hold_success_send_return()
        self.listener.clock = lambda: work.deadline + 1
        self.listener.expire_requests()
        self.assertEqual(self.listener._base, (self.ctx, 'A'), 'delivered base survives watchdog')
        self.assertFalse(work.cancelled.is_set())
        self.assert_silent()
        release.set()
        self.assertTrue(work.done.wait(2))
        self.assertEqual(len(self.agent.subtask_history), 1)

    def test_reader_cancels_blocked_model_and_only_new_snapshot_commits(self):
        old = self.begin()
        self.ctx['snapshotSeq'] += 1
        self.send('INVALIDATE_CONTEXT'); self.wait_context()
        self.assertTrue(old.cancelled.is_set())
        self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'B', interaction={'text': 'B'})
        self.release.set()
        reply = self.read()
        self.assertEqual(reply['requestId'], 'B')
        self.assertEqual(reply['context'], self.ctx)
        self.assertIn('payload', reply)
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, ['A', 'B'])
        self.assertEqual(self.calls.count('chat'), 4)
        self.assert_silent()

    def test_same_context_successor_runs_after_old_model_returns(self):
        old = self.begin()
        self.send('REQUEST_UI_UPDATE', 'B')
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(lambda: self.listener._pending is not None and self.listener._pending.request_id == 'B', timeout=2))
        self.assertFalse(old.cancelled.is_set())
        self.assertEqual(self.listener._pending.request_id, 'B')
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        self.assertEqual(self.read()['requestId'], 'B')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assert_silent()

    def test_overwritten_pending_request_keeps_accepted_interaction(self):
        old = self.begin()
        self.send('REQUEST_UI_UPDATE', 'B', interaction={'text': 'B'})
        self.send('REQUEST_UI_UPDATE', 'C', interaction={'contentDescription': 'C'})
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'C', timeout=2))
        self.assertFalse(old.cancelled.is_set())
        self.assertEqual(self.agent.action_history, ['A'], 'reader must not mutate worker history')
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        reply = self.read()
        self.assertEqual(reply['requestId'], 'C')
        self.assertIn('payload', reply)
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, ['A', 'B', 'C'])
        self.assertEqual(self.calls.count('chat'), 6)
        self.assert_silent()

    def test_rejected_frames_do_not_record_facts_and_repeated_actions_survive(self):
        self.begin()
        self.send('REQUEST_UI_UPDATE', 'A', interaction={'text': 'duplicate'})
        self.send('REQUEST_UI_UPDATE', 'bad request id', interaction={'text': 'invalid'})
        stale = demo.message('REQUEST_UI_UPDATE', 'stale', dict(self.ctx, snapshotSeq=0),
                             interaction={'text': 'stale'})
        self.peer.sendall((json.dumps(stale) + '\n').encode())
        self.send('REQUEST_TALK', 'busy', baseRequestId='A', interaction={'text': 'talk'})
        self.assertEqual(self.read()['error'], 'INVALID_BASE_OR_BUSY')
        self.send('REQUEST_UI_UPDATE', 'nontext', interaction={'text': {'invalid': 'shape'}})
        self.send('REQUEST_UI_UPDATE', 'B', interaction={'text': 'A'})
        self.send('REQUEST_UI_UPDATE', 'C')
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'C', timeout=2))
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        self.assertEqual(self.read()['requestId'], 'C')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, ['A', 'A'])
        self.assertEqual(self.calls.count('chat'), 6)
        self.assert_silent()

    def test_latest_pending_slot_is_bounded_during_blocked_provider(self):
        old = self.begin()
        for number in range(20):
            self.send('REQUEST_UI_UPDATE', 'queued-%d' % number)
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(lambda: self.listener._pending is not None and self.listener._pending.request_id == 'queued-19', timeout=2))
            self.assertIsNot(self.listener._pending, self.listener._active)
            self.assertFalse(old.cancelled.is_set())
        self.assertEqual(self.calls, ['chat'])
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        self.assertEqual(self.read()['requestId'], 'queued-19')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.calls.count('chat'), 6)
        self.assert_silent()

    def test_interaction_utf8_capacity_rejects_before_replacing_current_work(self):
        self.begin()
        action = '汉' * 10000
        self.send('REQUEST_UI_UPDATE', 'B', interaction={'text': action})
        self.ctx['snapshotSeq'] += 1
        self.send('INVALIDATE_CONTEXT'); self.wait_context(); self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'C', interaction={'text': action})
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'C', timeout=2))
            current = self.listener._pending
        self.send('REQUEST_UI_UPDATE', 'overflow', interaction={'text': '汉' * 2000})
        import select
        self.assertTrue(select.select([self.peer], [], [], 0.5)[0], 'capacity rejection must not wait for the model')
        rejection = self.read()
        self.assertEqual(rejection.get('error'), 'INTERACTION_HISTORY_LIMIT')
        self.assertNotIn('payload', rejection)
        self.assertNotIn('汉', json.dumps(rejection, ensure_ascii=False))
        self.assertIs(self.listener._pending, current)
        self.assertFalse(current.cancelled.is_set())
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'C')
        self.assertTrue(current.done.wait(2))
        self.assertEqual(self.agent.action_history, ['A', action, action])
        self.ctx = dict(self.ctx, taskEpoch=2)
        self.establish(); self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'restart', interaction={'text': action})
        self.assertEqual(self.read()['requestId'], 'restart')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, [action])
        self.assert_silent()

    def test_interaction_count_capacity_survives_snapshot_changes(self):
        self.begin()
        for index in range(255):
            self.ctx['snapshotSeq'] += 1
            self.send('INVALIDATE_CONTEXT'); self.wait_context()
            self.send('REQUEST_UI_UPDATE', 'item-%d' % index, interaction={'text': 'x'})
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'item-254', timeout=2))
            current = self.listener._pending
        self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'too-many', interaction={'text': 'x'})
        import select
        self.assertTrue(select.select([self.peer], [], [], 0.5)[0], 'count rejection must not wait for the model')
        self.assertEqual(self.read().get('error'), 'INTERACTION_HISTORY_LIMIT')
        self.assertIs(self.listener._pending, current)
        self.assertFalse(current.cancelled.is_set())
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'item-254')
        self.assertTrue(current.done.wait(2))
        self.assertEqual(self.agent.action_history, ['A'] + ['x'] * 255)
        self.assert_silent()

    def test_burger_task_keeps_goal_and_choices_across_screens_and_cancelled_work(self):
        goal = '我要点一份汉堡外卖'
        self.assertEqual(self.agent.instruction, goal)  # Whole burger preset was injected at construction.
        pages = [
            ('选择外卖软件', '外卖软件甲', '打开外卖软件甲', '天气软件'),
            ('选择商家', '合成商家', '进入合成商家', '鲜花配送'),
            ('选择汉堡', '合成鸡肉汉堡', '选择汉堡', '赠品广告'),
            ('选择汉堡规格', '合成汉堡规格', '选择规格', '非食品推广'),
        ]
        request_pages, stages, prompts, prompt_actions = {}, {}, {}, {}
        import run as runtime
        original_prompt = runtime.get_subtask_prompt
        def trace_prompt(*args, **kwargs):
            prompt_actions[self.agent.guard.request_id] = list(args[3])
            return original_prompt(*args, **kwargs)
        prompt_spy = patch.object(runtime, 'get_subtask_prompt', trace_prompt)
        prompt_spy.start(); self.addCleanup(prompt_spy.stop)
        def chat(messages, model):
            request_id = self.agent.guard.request_id
            stage = ('planning', 'decision', 'classification')[stages.get(request_id, 0)]
            stages[request_id] = stages.get(request_id, 0) + 1
            page = pages[request_pages[request_id]]
            if stage == 'planning':
                prompts[request_id] = json.dumps(messages, ensure_ascii=False)
                if request_id == 'burger-cancelled':
                    self.entered.set()
                    self.assertTrue(self.release.wait(3), 'synthetic planning gate')
                return '### Thought ### 合成连续任务 ### Subtask ### {} ### Screen ### {}'.format(page[0], page[1])
            return self.responses[stage].replace('Sample item', page[1]).replace('Open', page[2])
        self.agent.chat = chat
        def prepare(page_index):
            self.ctx['snapshotSeq'] += 1
            self.send('INVALIDATE_CONTEXT'); self.wait_context()
            tree = demo.load_tree()
            page = pages[page_index]
            nodes = tree['children']['element-card']['children']
            nodes['element-title']['text'], nodes['element-open']['text'] = page[1], page[2]
            tree['children']['element-other']['text'] = page[3]
            self.tree_path.write_text(demo.snapshot_text(json.dumps(tree), self.ctx))
        def verify_current(request_id, page_index):
            reply = self.read()
            self.assertEqual((reply['requestId'], reply['context']), (request_id, self.ctx))
            self.assertTrue(self.listener._active.done.wait(2))
            tree = reply['payload']
            self.assertTrue(tree['children']['element-card']['children']['element-open']['isVirtualFocusNode'])
            self.assertFalse(tree['children']['element-other']['isVirtualFocusNode'])
            self.assertEqual(tree['children']['element-card']['children']['element-title']['text'], pages[page_index][1])
            self.assertIn(goal, prompts[request_id])
            self.assertEqual((self.agent.instruction, self.agent.state), (goal, 'waiting'))
        for page_index in range(3):
            prepare(page_index)
            request_id = 'burger-page-%d' % page_index
            request_pages[request_id] = page_index
            action = None if page_index == 0 else {'text': pages[page_index - 1][2]}
            self.send('REQUEST_UI_UPDATE', request_id, interaction=action)
            verify_current(request_id, page_index)
        request_pages['burger-cancelled'] = 2
        self.send('REQUEST_UI_UPDATE', 'burger-cancelled', interaction={'text': '选择汉堡'})
        self.assertTrue(self.entered.wait(2)); old = self.listener._active
        prepare(3)
        request_pages['burger-pending'] = request_pages['burger-final'] = 3
        self.send('REQUEST_UI_UPDATE', 'burger-pending', interaction={'text': '打开规格说明'})
        self.send('REQUEST_UI_UPDATE', 'burger-final')
        with self.listener._condition:
            self.assertTrue(self.listener._condition.wait_for(
                lambda: self.listener._pending is not None and self.listener._pending.request_id == 'burger-final', timeout=2))
        self.assertTrue(old.cancelled.is_set())
        self.release.set(); verify_current('burger-final', 3)
        expected_actions = ['打开外卖软件甲', '进入合成商家', '选择汉堡', '打开规格说明']
        self.assertEqual(self.agent.action_history, expected_actions)
        self.assertEqual(prompt_actions['burger-final'], expected_actions)
        # Existing templates accept this argument but do not interpolate it.
        # Their real model text still receives the unchanged goal/proposed-step sequence.
        for page in pages[:3]:
            self.assertIn(page[0], prompts['burger-final'])
        self.assertNotIn('burger-pending', stages)
        self.assertEqual(self.agent.subtask_history, [page[0] for page in pages])
        self.assertEqual(self.ctx['taskEpoch'], demo.CONTEXT['taskEpoch'])
        self.agent.chat = lambda *args: self.responses['talk']
        self.send('REQUEST_TALK', 'burger-details', baseRequestId='burger-final')
        detail = self.read()
        self.assertEqual(detail['requestId'], 'burger-details')
        self.assertTrue(detail['payload']['children']['element-card']['children']['element-hint']['isVirtualFocusNode'])
        self.assertTrue(self.listener._active.done.wait(2))
        self.assert_silent()

    def test_cancel_without_replacement_produces_no_speech_or_reply(self):
        old = self.begin()
        self.ctx['snapshotSeq'] += 1
        self.send('INVALIDATE_CONTEXT'); self.wait_context()
        self.release.set(); self.assertTrue(old.done.wait(2))
        self.assertEqual(self.speeches, [])
        self.assertNotIn('beep', self.calls)
        self.assertEqual(self.agent.action_history, ['A'])
        self.assert_silent()

    def test_restart_resets_old_histories_after_cancelled_worker_stops(self):
        self.begin()
        self.ctx = dict(self.ctx, taskEpoch=2)
        self.establish(); self.write_snapshot()
        self.send('REQUEST_UI_UPDATE', 'restart', interaction={'text': 'restart'})
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'restart')
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, ['restart'])
        self.assertEqual(len(self.agent.subtask_history), 1)

    def test_disconnect_reconnect_never_routes_old_reply_to_new_socket(self):
        old = self.begin()
        self.peer.close(); self.readers[0].join(2)
        self.assertTrue(old.cancelled.is_set())
        self.peer = self.connect()
        self.ctx = dict(self.ctx, sessionId='00000000-0000-4000-8000-000000000088')
        self.establish(); self.write_snapshot()
        self.peer.sendall((json.dumps(demo.message('REQUEST_UI_UPDATE', 'old-packet', demo.CONTEXT)) + '\n').encode())
        self.send('REQUEST_UI_UPDATE', 'new-session', interaction={'text': 'new-session'})
        self.release.set()
        reply = self.read()
        self.assertEqual(reply['requestId'], 'new-session')
        self.assertEqual(reply['context']['sessionId'], self.ctx['sessionId'])
        self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(self.agent.action_history, ['new-session'])
        self.assert_silent()

    def test_talk_busy_invalid_base_and_positive_current_talk(self):
        self.begin()
        self.send('REQUEST_TALK', 'busy-talk', baseRequestId='A')
        self.assertEqual(self.read()['error'], 'INVALID_BASE_OR_BUSY')
        # A's blocked planning returns; next provider stage is decision.
        self.release.set()
        self.assertEqual(self.read()['requestId'], 'A')
        self.assertTrue(self.listener._active.done.wait(2))
        self.send('REQUEST_TALK', 'wrong-talk', baseRequestId='wrong')
        self.assertEqual(self.read()['error'], 'INVALID_BASE_OR_BUSY')
        self.agent.chat = lambda *args: self.responses['talk']
        self.send('REQUEST_TALK', 'good-talk', baseRequestId='A')
        reply = self.read()
        self.assertEqual(reply['requestId'], 'good-talk')
        self.assertTrue(reply['payload']['children']['element-card']['children']['element-hint']['isVirtualFocusNode'])
        self.assertTrue(self.listener._active.done.wait(2))
        self.agent.chat = lambda *args: '### Thought ### stay ### Mode ### A ### Displayed UI ###'
        self.send('REQUEST_TALK', 'noop-talk', baseRequestId='A')
        self.assertEqual(self.read()['status'], 'NO_OP')

    def test_delayed_real_tts_provider_never_starts_playback_after_cancel(self):
        from MobileAgent import api
        self.block = False
        self.agent.tts = api.text2audio
        entered, release = threading.Event(), threading.Event()
        starts = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_bytes(self, **kwargs):
                entered.set()
                if not release.wait(3): raise RuntimeError('test gate timed out')
                yield b'synthetic audio'
        client = SimpleNamespace(close=lambda: None, audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=lambda **kwargs: Response()))))
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-only'}), patch.dict('sys.modules', {
            'openai': SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=lambda **kwargs: client),
            'soundfile': SimpleNamespace(read=lambda *args: (SimpleNamespace(shape=(1,), dtype='float32'), 16000)),
            'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: starts.append('stream'))}):
            self.send('REQUEST_UI_UPDATE', 'tts')
            self.assertTrue(entered.wait(2)); old = self.listener._active
            self.ctx['snapshotSeq'] += 1
            self.send('INVALIDATE_CONTEXT'); self.wait_context()
            release.set(); self.assertTrue(old.done.wait(2))
        self.assertEqual(starts, [])
        self.assertNotIn('beep', self.calls)
        self.assert_silent()

    def test_owned_audio_aborts_after_cancelled_native_write_returns(self):
        from MobileAgent import api
        self.block = False
        started, aborted, native_release = threading.Event(), threading.Event(), threading.Event()
        closes = []
        class Stream:
            def start(self): pass
            def write(self, data):
                started.set()
                if not native_release.wait(3): raise RuntimeError('test native write gate timed out')
            def abort(self): aborted.set()
            def close(self, **kwargs): closes.append(1)
        def tts(text):
            api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        self.agent.tts = tts
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            self.send('REQUEST_UI_UPDATE', 'audio')
            self.assertTrue(started.wait(2)); old = self.listener._active
            self.ctx['snapshotSeq'] += 1
            self.send('INVALIDATE_CONTEXT'); self.wait_context()
            self.assertFalse(aborted.wait(0.2))
            native_release.set()
            self.assertTrue(aborted.wait(2)); self.assertTrue(old.done.wait(2))
        self.assertEqual(closes, [1])
        self.assert_silent()

    def test_blocked_audio_start_does_not_block_control_or_deliver_cancelled_samples(self):
        from MobileAgent import api
        self.block = False
        entered, release, applied = threading.Event(), threading.Event(), threading.Event()
        writes, closes = [], []
        original = self.listener._process_message
        def observe(msg, connection=None):
            result = original(msg, connection)
            if json.loads(msg).get('context', {}).get('snapshotSeq') == 2:
                applied.set()
            return result
        self.listener._process_message = observe
        class Stream:
            def start(self):
                entered.set()
                if not release.wait(3): raise RuntimeError('test start gate timeout')
            def write(self, data): writes.append('write')
            def abort(self): pass
            def close(self, **kwargs): closes.append('close')
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            try:
                self.send('REQUEST_UI_UPDATE', 'blocked-start')
                self.assertTrue(entered.wait(2)); old = self.listener._active
                self.ctx['snapshotSeq'] = 2; self.send('INVALIDATE_CONTEXT')
                self.assertTrue(applied.wait(0.2), 'reader must advance while start is blocked')
                self.assertTrue(old.cancelled.is_set())
                self.assertEqual(self.listener._context['snapshotSeq'], 2)
                self.ctx['snapshotSeq'] = 3; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(writes, [])
        self.assertEqual(closes, ['close'])

    def test_blocked_abort_waiting_for_worker_check_does_not_block_control(self):
        from MobileAgent import api
        self.block = False
        entered, release, closed, applied, aborting, checked = [threading.Event() for _ in range(6)]
        original = self.listener._process_message
        def observe(msg, connection=None):
            result = original(msg, connection)
            if json.loads(msg).get('context', {}).get('snapshotSeq') == 2: applied.set()
            return result
        self.listener._process_message = observe
        class Stream:
            def start(self): pass
            def write(stream, data):
                entered.set()
                if not self.agent.guard.cancelled.wait(3): raise RuntimeError('test write gate timeout')
            def abort(stream):
                aborting.set()
                if not checked.wait(2): raise RuntimeError('worker check did not advance')
                release.wait(3)
            def close(stream, **kwargs): closed.set()
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            try:
                self.send('REQUEST_UI_UPDATE', 'blocked-abort')
                self.assertTrue(entered.wait(2)); old = self.listener._active
                original_check = old.check
                def observe_check():
                    try: return original_check()
                    finally:
                        if old.cancelled.is_set(): checked.set()
                old.check = observe_check
                self.ctx['snapshotSeq'] = 2; self.send('INVALIDATE_CONTEXT')
                self.assertTrue(aborting.wait(2))
                self.assertTrue(applied.wait(0.2), 'reader must not wait for abort callback')
                self.assertTrue(checked.wait(0.2), 'worker can check cancellation while abort is pending')
                self.assertFalse(closed.is_set(), 'close waits until abort returns')
                self.assertEqual(self.listener._context['snapshotSeq'], 2)
                self.ctx['snapshotSeq'] = 3; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)

    def test_busy_talk_socket_backpressure_does_not_block_reader_invalidation(self):
        old = self.begin()
        server = self.listener._connection
        server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        server.setblocking(False)
        filled = 0
        while True:
            try: filled += server.send(b'x' * 4096)
            except BlockingIOError: break
        server.setblocking(False)
        entered, applied = threading.Event(), threading.Event()
        original = self.listener._send_to
        def sending(*args, **kwargs):
            entered.set()
            return original(*args, **kwargs)
        self.listener._send_to = sending
        original_process = self.listener._process_message
        def observe(msg, connection=None):
            result = original_process(msg, connection)
            if json.loads(msg).get('context', {}).get('snapshotSeq') == 2: applied.set()
            return result
        self.listener._process_message = observe
        try:
            self.send('REQUEST_TALK', 'busy-under-backpressure', baseRequestId='A')
            self.assertTrue(entered.wait(2))
            self.ctx['snapshotSeq'] = 2; self.send('INVALIDATE_CONTEXT')
            self.assertTrue(applied.wait(0.2), 'reader must advance without draining peer socket')
            self.assertTrue(old.cancelled.is_set())
        finally:
            received = 0
            while received < filled: received += len(self.peer.recv(min(4096, filled - received)))
            self.release.set(); old.done.wait(2)

    def test_rejection_backpressure_queue_is_bounded_and_overflow_closes_origin(self):
        old = self.begin()
        server = self.listener._connection
        server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        server.setblocking(False); filled = 0
        while True:
            try: filled += server.send(b'x' * 4096)
            except BlockingIOError: break
        server.setblocking(False)
        sending = threading.Event()
        original = self.listener._send_to
        def output(*args, **kwargs):
            sending.set()
            return original(*args, **kwargs)
        self.listener._send_to = output
        try:
            self.send('REQUEST_TALK', 'blocking-reject', baseRequestId='A')
            self.assertTrue(sending.wait(2))
            for number in range(9):
                self.send('REQUEST_TALK', 'queued-reject-%d' % number, baseRequestId='A')
            self.assertTrue(old.cancelled.wait(0.2), 'overflow must invalidate rather than block reader')
            self.readers[0].join(0.2)
            self.assertFalse(self.readers[0].is_alive())
            self.assertIsNone(self.listener._context)
            self.assertEqual(len(self.listener._replies), 0)
        finally:
            received = 0
            while received < filled:
                chunk = self.peer.recv(min(4096, filled - received))
                if not chunk: break
                received += len(chunk)
            self.release.set(); old.done.wait(2)

    def test_delayed_stream_creation_is_closed_without_start_after_cancel(self):
        from MobileAgent import api
        self.block = False
        creating, release, closed = threading.Event(), threading.Event(), threading.Event()
        starts, writes, closes = [], [], []
        class Stream:
            def start(self): starts.append(1)
            def write(self, data): writes.append(1)
            def abort(self): pass
            def close(self, **kwargs):
                closes.append(threading.current_thread().name)
                closed.set()
        def create(**kwargs):
            creating.set()
            if not release.wait(3): raise RuntimeError('test constructor gate timeout')
            return Stream()
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=create)}):
            try:
                self.send('REQUEST_UI_UPDATE', 'constructing')
                self.assertTrue(creating.wait(2)); old = self.listener._active
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
                self.assertTrue(old.cancelled.is_set())
            finally:
                release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertTrue(closed.is_set())
        self.assertEqual(closes, ['focalflow-audio-cleanup'])
        self.assertEqual(len(self.listener._audio_leases), 0)
        self.assertEqual(starts, [])
        self.assertEqual(writes, [])

    def test_guarded_original_ping_has_no_process_launch_and_rechecks_delayed_decode(self):
        from MobileAgent import api
        self.block = False
        decoding, release = threading.Event(), threading.Event()
        starts = []
        def read(path, **kwargs):
            self.assertEqual(path, '/System/Library/Sounds/Ping.aiff')
            decoding.set()
            if not release.wait(3): raise RuntimeError('test decode gate timeout')
            return SimpleNamespace(shape=(1,), dtype='float32'), 16000
        self.agent.tts = lambda text: api._play_ping(self.agent.guard)
        with patch.dict('sys.modules', {
            'soundfile': SimpleNamespace(read=read),
            'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: starts.append(1))}), \
             patch.object(api.subprocess, 'Popen', side_effect=AssertionError('guarded ping must not launch a playing process')):
            try:
                self.send('REQUEST_UI_UPDATE', 'ping-decode')
                self.assertTrue(decoding.wait(2)); old = self.listener._active
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(starts, [])
        self.assert_silent()

    def test_blocked_audio_cleanup_retains_capacity_and_bounds_later_work(self):
        from MobileAgent import api
        self.block = False
        entered, cleanup_release, aborting = threading.Event(), threading.Event(), threading.Event()
        creations, closes = [], []
        class Stream:
            def __init__(stream, index): stream.index = index
            def start(stream): pass
            def stop(stream, **kwargs): pass
            def write(stream, data):
                if stream.index == 0:
                    entered.set()
                    if not self.agent.guard.cancelled.wait(3): raise RuntimeError('test audio gate timeout')
            def abort(stream):
                aborting.set()
                if not cleanup_release.wait(3): raise RuntimeError('test cleanup gate timeout')
            def close(stream, **kwargs): closes.append(stream.index)
        def create(**kwargs):
            stream = Stream(len(creations)); creations.append(1); return stream
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=create)}):
            try:
                self.send('REQUEST_UI_UPDATE', 'cleanup-pending')
                self.assertTrue(entered.wait(2)); work = self.listener._active
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
                self.assertTrue(aborting.wait(2))
                for index in range(20): self.send('REQUEST_UI_UPDATE', 'while-cleanup-%d' % index)
                with self.listener._condition:
                    self.assertTrue(self.listener._condition.wait_for(lambda: self.listener._pending is not None and self.listener._pending.request_id == 'while-cleanup-19', timeout=2))
                    self.assertEqual(len(self.listener._audio_leases), 1)
                    self.assertIsNot(self.listener._pending, self.listener._active)
                self.assertFalse(work.done.is_set())
                self.assertEqual(creations, [1]); self.assertEqual(closes, [])
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                cleanup_release.set()
                self.assertTrue(work.done.wait(2))
                with self.listener._condition:
                    self.assertTrue(self.listener._condition.wait_for(lambda: not self.listener._audio_leases, timeout=2))
            self.assertEqual(closes, [0])
            self.stage = 0; self.write_snapshot(); self.send('REQUEST_UI_UPDATE', 'after-cleanup')
            self.assertIn('payload', self.read())
            self.assertTrue(self.listener._active.done.wait(2))
            self.assertEqual(closes, [0, 1])
            self.assertEqual(len(self.listener._audio_leases), 0)

    def test_sdk_exact_close_has_one_owner_for_same_native_pointer(self):
        import ast
        import importlib.util
        from MobileAgent import api
        specification = importlib.util.find_spec('sounddevice')
        if specification is None: self.skipTest('installed sounddevice source required for exact SDK probe')
        sdk = Path(specification.origin)
        module = ast.parse(sdk.read_text())
        stream_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == '_StreamBase')
        close_method = next(node for node in stream_class.body if isinstance(node, ast.FunctionDef) and node.name == 'close')
        entered, both, release, writing, checked, aborting = [threading.Event() for _ in range(6)]
        calls = []; lock = threading.Lock()
        abort_active = threading.Event(); overlaps = []
        def native_close(pointer):
            if abort_active.is_set(): overlaps.append('abort-close')
            with lock:
                calls.append((pointer, threading.current_thread().name))
                entered.set()
                if len(calls) > 1: both.set()
            if not release.wait(3): raise RuntimeError('test native close gate timeout')
            return 0
        namespace = {'_lib': SimpleNamespace(Pa_CloseStream=native_close), '_ffi': SimpleNamespace(NULL=None),
                     '_check': lambda error, *args: self.assertEqual(error, 0)}
        exec(compile(ast.Module(body=[close_method], type_ignores=[]), str(sdk), 'exec'), namespace)
        self.block = False
        class Stream:
            _ptr = 'synthetic-owned-pointer'
            close = namespace['close']
            def start(stream): pass
            def write(stream, data):
                writing.set()
                if not self.agent.guard.cancelled.wait(3): raise RuntimeError('test write gate timeout')
            def abort(stream):
                abort_active.set()
                aborting.set()
                try:
                    if not checked.wait(3): raise RuntimeError('test worker check gate timeout')
                finally:
                    abort_active.clear()
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            try:
                self.send('REQUEST_UI_UPDATE', 'sdk-single-close')
                self.assertTrue(writing.wait(2)); old = self.listener._active
                original_check = old.check
                def observe_check():
                    try: return original_check()
                    finally:
                        if old.cancelled.is_set(): checked.set()
                old.check = observe_check
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
                self.assertTrue(aborting.wait(2)); self.assertTrue(checked.wait(2)); self.assertTrue(entered.wait(2))
                self.assertFalse(both.wait(0.2), 'same SDK native pointer must not be closed concurrently')
                with self.listener._condition:
                    self.assertEqual(len(self.listener._audio_leases), 1, 'capacity retained until native close returns')
                self.assertFalse(old.done.is_set())
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(calls, [('synthetic-owned-pointer', 'focalflow-audio-cleanup')])
        self.assertEqual(overlaps, [])
        self.assertEqual(len(self.listener._audio_leases), 0)

    def test_current_guarded_audio_drains_tail_before_unique_close(self):
        from MobileAgent import api
        self.block = False
        pending, played, events = [], [], []
        class Stream:
            def start(stream): events.append('start')
            def write(stream, data): pending.extend(['head', 'tail']); events.append('write')
            def stop(stream, **kwargs):
                played.extend(pending); pending.clear(); events.append('stop')
            def abort(stream): pending.clear(); events.append('abort')
            def close(stream, **kwargs): pending.clear(); events.append(('close', threading.current_thread().name))
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            self.send('REQUEST_UI_UPDATE', 'complete-audio')
            self.assertIn('payload', self.read())
            self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(played, ['head', 'tail'], 'successful audio must not discard the final buffer')
        self.assertEqual(events, ['start', 'write', 'stop', ('close', 'focalflow-audio-cleanup')])
        self.assertEqual(len(self.listener._audio_leases), 0)

    def test_cancel_during_drain_keeps_reader_live_and_never_overlaps_native_controls(self):
        from MobileAgent import api
        self.block = False
        draining, native_release, aborted = threading.Event(), threading.Event(), threading.Event()
        stop_active = threading.Event()
        pending, played, closes, overlaps = [], [], [], []
        class Stream:
            def start(stream): pass
            def write(stream, data): pending.extend(['head', 'tail'])
            def stop(stream, **kwargs):
                stop_active.set(); draining.set()
                try:
                    if not native_release.wait(3): raise RuntimeError('test opaque drain gate timeout')
                    played.extend(pending); pending.clear()
                finally: stop_active.clear()
            def abort(stream):
                if stop_active.is_set(): overlaps.append('stop-abort')
                pending.clear(); aborted.set()
            def close(stream, **kwargs):
                if stop_active.is_set(): overlaps.append('stop-close')
                pending.clear(); closes.append(threading.current_thread().name)
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            try:
                self.send('REQUEST_UI_UPDATE', 'cancel-draining')
                self.assertTrue(draining.wait(2)); old = self.listener._active
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
                self.assertFalse(aborted.wait(0.2), 'abort must wait for the opaque stop call to return')
                self.assertEqual(closes, [])
                self.assertEqual(len(self.listener._audio_leases), 1)
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            finally:
                native_release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(played, ['head', 'tail'])  # Already handed-off final buffer is not retractable.
        self.assertTrue(aborted.is_set())
        self.assertEqual(closes, ['focalflow-audio-cleanup'])
        self.assertEqual(overlaps, [])
        self.assertEqual(len(self.listener._audio_leases), 0)
        self.assert_silent()

    def test_cancelled_output_does_not_submit_chunks_after_inflight_write(self):
        from MobileAgent import api
        self.block = False
        entered, native_release = threading.Event(), threading.Event()
        in_io = threading.Event(); writes, closes, overlaps = [], [], []
        class Samples:
            shape = (4800,); dtype = 'float32'
            def __getitem__(self, item): return SimpleNamespace(shape=(item.stop - item.start,), dtype='float32')
        class Stream:
            def start(stream): pass
            def write(stream, chunk):
                in_io.set(); writes.append(chunk.shape[0]); entered.set()
                try:
                    if not native_release.wait(3): raise RuntimeError('test write gate timeout')
                finally: in_io.clear()
            def stop(stream, **kwargs): raise AssertionError('cancelled output must not drain later buffers')
            def abort(stream):
                if in_io.is_set(): overlaps.append('write-abort')
            def close(stream, **kwargs):
                if in_io.is_set(): overlaps.append('write-close')
                closes.append(1)
        self.agent.tts = lambda text: api.play_samples(Samples(), 16000, self.agent.guard)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            try:
                self.send('REQUEST_UI_UPDATE', 'chunked-output')
                self.assertTrue(entered.wait(2)); old = self.listener._active
                self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
                self.assertEqual(writes, [1600]); self.assertEqual(closes, [])
            finally:
                native_release.set()
                if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(writes, [1600])
        self.assertEqual(closes, [1]); self.assertEqual(overlaps, [])
        self.assert_silent()

    def test_cancelled_input_does_not_read_chunks_after_inflight_read(self):
        from MobileAgent import api
        self.block = False
        entered, native_release = threading.Event(), threading.Event()
        in_io = threading.Event(); reads, closes, overlaps = [], [], []
        class Stream:
            def start(stream): pass
            def read(stream, frames):
                in_io.set(); reads.append(frames); entered.set()
                try:
                    if not native_release.wait(3): raise RuntimeError('test read gate timeout')
                    return SimpleNamespace(shape=(frames, 1)), False
                finally: in_io.clear()
            def abort(stream):
                if in_io.is_set(): overlaps.append('read-abort')
            def close(stream, **kwargs):
                if in_io.is_set(): overlaps.append('read-close')
                closes.append(1)
        def record(text):
            guard = self.agent.guard
            with guard.own(Stream, lambda stream: stream.start(), lambda stream: stream.abort(), lambda stream: stream.close()) as stream:
                api._read_audio_chunks(stream, 4800, guard)
        self.agent.tts = record
        try:
            self.send('REQUEST_UI_UPDATE', 'chunked-input')
            self.assertTrue(entered.wait(2)); old = self.listener._active
            self.ctx['snapshotSeq'] += 1; self.send('INVALIDATE_CONTEXT'); self.wait_context()
            self.assertEqual(reads, [1600]); self.assertEqual(closes, [])
        finally:
            native_release.set()
            if self.listener._active is not None: self.listener._active.done.wait(2)
        self.assertEqual(reads, [1600]); self.assertEqual(closes, [1]); self.assertEqual(overlaps, [])
        self.assert_silent()

    def test_sdk_close_error_retains_capacity_and_rejects_fifth_create(self):
        import ast
        import importlib.util
        from MobileAgent import api
        specification = importlib.util.find_spec('sounddevice')
        if specification is None: self.skipTest('installed sounddevice source required for exact SDK probe')
        sdk = Path(specification.origin)
        module = ast.parse(sdk.read_text())
        stream_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == '_StreamBase')
        method = next(node for node in stream_class.body if isinstance(node, ast.FunctionDef) and node.name == 'close')
        created, returned, checked = [], [], []
        def native_close(pointer): returned.append(pointer); return -9999
        def sdk_check(error, *args):
            checked.append(error)
            if error: raise RuntimeError('synthetic native close failure')
        namespace = {'_lib': SimpleNamespace(Pa_CloseStream=native_close), '_ffi': SimpleNamespace(NULL=None), '_check': sdk_check}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(sdk), 'exec'), namespace)
        self.block = False
        class Stream:
            close = namespace['close']
            def __init__(stream):
                stream._ptr = 'synthetic-pointer-%d' % len(created); created.append(stream._ptr)
            def start(stream): pass
            def write(stream, data): pass
            def stop(stream, **kwargs): pass
            def abort(stream): pass
        self.agent.tts = lambda text: api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000, self.agent.guard)
        replies = []
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            for index in range(5):
                self.stage = 0
                self.send('REQUEST_UI_UPDATE', 'failed-native-close-%d' % index)
                replies.append(self.read())
                self.assertTrue(self.listener._active.done.wait(2))
        self.assertEqual(sum('payload' in reply for reply in replies), 0, 'native close failures cannot report payload success')
        self.assertEqual([reply.get('error') for reply in replies], ['RuntimeError'] * 4 + ['ValidationError'])
        self.assertEqual(len(created), 4, 'fifth resource is rejected before SDK creation')
        self.assertEqual(returned, created, 'each uncertain native handle is closed only once')
        self.assertEqual(checked, [-9999] * 4)
        self.assertEqual(len(self.listener._audio_leases), 4)

    def test_snapshot_pair_rejected_when_envelope_changes_during_screencap(self):
        from MobileAgent import controller
        commands, pulls = [], []
        def execute(argv, **kwargs):
            commands.append(argv)
            if argv[1] == 'pull':
                if argv[2] == controller.TRANSPORT_SLOT:
                    pulls.append(1)
                    ctx = self.ctx if len(pulls) == 1 else dict(self.ctx, snapshotSeq=2)
                    Path(argv[-1]).write_text(demo.snapshot_text(json.dumps(demo.load_tree()), ctx))
                else:
                    Path(argv[-1]).write_bytes(b'synthetic image')
            return SimpleNamespace(returncode=0)
        with patch.object(controller.subprocess, 'run', execute), patch.object(controller.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'context mismatch'):
                controller.get_screenshot_and_ui_elements('synthetic adb', 'user', 'task', 1, expected_context=self.ctx)
        self.assertEqual(len(pulls), 2)
        self.assertTrue(all(isinstance(argv, list) for argv in commands))

    def test_retry_loop_observes_cancel_before_second_attempt(self):
        from MobileAgent import api
        old = self.begin(); calls = []
        def post(*args, **kwargs):
            calls.append(1)
            with self.listener._condition: old.cancel()
            raise RuntimeError('synthetic failure')
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post)}):
            with self.assertRaises(Cancelled):
                api.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'synthetic', guard=old)
        self.assertEqual(calls, [1])

class ProtocolVectorTests(unittest.TestCase):
    def test_real_audio_player_uses_supported_stream_dtype_and_closes(self):
        from MobileAgent import api
        calls = []
        data = SimpleNamespace(shape=(2,), dtype='float32')
        def read(path, **kwargs):
            self.assertEqual(kwargs, {'dtype': 'float32'})
            return data, 16000
        class Stream:
            def start(self): calls.append('start')
            def stop(self, **kwargs):
                if kwargs != {'ignore_errors': False}: raise AssertionError('drain must propagate failure')
                calls.append('stop')
            def write(self, samples):
                if samples is not data: raise AssertionError('audio sample identity')
                calls.append('write')
            def close(self, **kwargs): calls.append('close')
        def output(**kwargs):
            self.assertEqual(kwargs, {'samplerate': 16000, 'channels': 1, 'dtype': 'float32'})
            return Stream()
        with patch.dict('sys.modules', {'soundfile': SimpleNamespace(read=read), 'sounddevice': SimpleNamespace(OutputStream=output)}):
            api.play_audio_file('synthetic.wav')
        self.assertEqual(calls, ['start', 'write', 'stop', 'close'])

    def test_unguarded_audio_drains_tail_before_close(self):
        from MobileAgent import api
        pending, played, calls = [], [], []
        class Stream:
            def start(stream): calls.append('start')
            def write(stream, data): pending.extend(['head', 'tail']); calls.append('write')
            def stop(stream, **kwargs): played.extend(pending); pending.clear(); calls.append('stop')
            def close(stream, **kwargs): pending.clear(); calls.append('close')
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
            api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000)
        self.assertEqual(played, ['head', 'tail'])
        self.assertEqual(calls, ['start', 'write', 'stop', 'close'])

    def test_unguarded_close_error_is_reported_without_masking_primary_error(self):
        from MobileAgent import api
        for primary in (False, True):
            with self.subTest(primary=primary):
                calls = []
                class Stream:
                    def start(stream): pass
                    def write(stream, data):
                        if primary: raise ValueError('synthetic primary failure')
                    def stop(stream, **kwargs): pass
                    def close(stream, **kwargs):
                        calls.append(kwargs)
                        raise RuntimeError('synthetic close failure')
                with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(OutputStream=lambda **kwargs: Stream())}):
                    with self.assertRaises(ValueError if primary else RuntimeError):
                        api.play_samples(SimpleNamespace(shape=(1,), dtype='float32'), 16000)
                self.assertEqual(calls, [{'ignore_errors': False}])

    def test_shared_strict_header_vectors(self):
        from MobileAgent.protocol import header
        for vector in json.loads((demo.FIXTURES / 'protocol_vectors.json').read_text()):
            with self.subTest(name=vector['name']):
                if vector['accepted']:
                    self.assertEqual(header(vector['message']), (demo.CONTEXT, demo.REQUEST_ID))
                else:
                    with self.assertRaises(ValueError): header(vector['message'])
