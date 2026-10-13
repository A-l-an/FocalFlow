"""Output budgets/truncation through production APIs; synthetic responses, no services."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples import offline_demo as demo
from MobileAgent import api
from MobileAgent.failure import FailurePolicy, OperationError
from MobileAgent.validation import ValidationError
from requests import exceptions as network_errors


TOOLS = Path(__file__).resolve().parents[1] / 'tools/manual_testing'
PRIVATE = 'SYNTHETIC_PRIVATE_BODY_TOKEN_URL'


def load_tool(name):
    spec = importlib.util.spec_from_file_location('budget_' + name, str(TOOLS / (name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    status_code = 200
    def __init__(self, text='synthetic answer', reason='stop', include_reason=True):
        choice = {'message': {'content': text}}
        if include_reason:
            choice['finish_reason'] = reason
        self.body = json.dumps({'choices': [choice]}).encode()
        self.closed = 0
    def iter_content(self, chunk_size):
        return iter([self.body])
    def close(self):
        self.closed += 1


class OutputBudgetProviderTests(unittest.TestCase):
    def request(self, response, model='gpt-4', **kwargs):
        calls = []
        def post(*args, **options):
            calls.append(options)
            return response
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
            value = api.inference_chat([], model, 'https://offline.test/chat', 'synthetic-no-key', **kwargs)
        return value, calls

    def test_default_and_classification_limits_use_each_model_parameter_branch(self):
        for model in ('gpt-6-luna', 'gpt-4o'):
            for limit in (None, 8192):
                with self.subTest(model=model, limit=limit):
                    response = Response()
                    value, calls = self.request(response, model, **({} if limit is None else {'output_limit': limit}))
                    self.assertEqual(value, 'synthetic answer')
                    self.assertEqual(len(calls), 1)
                    payload = calls[0]['json']
                    field = 'max_completion_tokens' if model == 'gpt-6-luna' else 'max_tokens'
                    self.assertEqual(payload[field], 2048 if limit is None else 8192)
                    self.assertNotIn('max_tokens' if model == 'gpt-6-luna' else 'max_completion_tokens', payload)
                    self.assertEqual(calls[0]['timeout'], (5, 30))
                    self.assertEqual(response.closed, 1)

    def test_invalid_limits_fail_before_http(self):
        for limit in (0, -1, 8193, True, False, 1.5, '8192', None, float('nan'), float('inf')):
            with self.subTest(limit=repr(limit)):
                calls = []
                def post(*args, **kwargs):
                    calls.append(kwargs)
                    return Response()
                with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
                    with self.assertRaises(ValueError):
                        api.inference_chat([], 'gpt-6-luna', 'https://offline.test/chat', 'synthetic-no-key', output_limit=limit)
                self.assertEqual(calls, [])

    def test_length_rejects_even_complete_parseable_content_and_never_retries(self):
        response = Response(json.dumps({'complete': True, 'private': PRIVATE}), 'length')
        calls, waits = [], []
        def post(*args, **kwargs):
            calls.append(kwargs)
            return response
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
            with self.assertRaises(OperationError) as raised:
                api.inference_chat([], 'gpt-6-luna', 'https://offline.test/chat', 'synthetic-no-key',
                                   policy=FailurePolicy(attempts=3), wait=waits.append)
        self.assertEqual((raised.exception.stage, raised.exception.code), ('chat', 'OUTPUT_TRUNCATED'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(waits, [])
        self.assertEqual(response.closed, 1)
        self.assertNotIn(PRIVATE, str(raised.exception))

    def test_missing_finish_reason_keeps_existing_compatibility(self):
        value, calls = self.request(Response(include_reason=False))
        self.assertEqual(value, 'synthetic answer')
        self.assertEqual(len(calls), 1)

    def test_invalid_response_never_exposes_arbitrary_finish_reason(self):
        response = Response('', PRIVATE)
        with self.assertRaises(OperationError) as raised:
            self.request(response)
        self.assertEqual(raised.exception.code, 'INVALID_RESPONSE')
        self.assertNotIn(PRIVATE, str(raised.exception))


class ClassificationBudgetTests(unittest.TestCase):
    def test_live_checked_without_guard_preserves_default_policy_and_explicit_limit(self):
        import run
        observed = []
        def inference(*args, **kwargs):
            observed.append(kwargs)
            return 'synthetic answer'
        with demo.offline_boundaries(), patch.object(run, 'inference_chat', inference), \
                patch.object(run, 'load_runtime_setting', return_value='synthetic-setting'):
            agent = run.MobileAgentStateMachine()
            self.assertEqual(agent._checked(agent.chat, [], 'gpt-4', output_limit=8192), 'synthetic answer')
            self.assertEqual(agent._checked(agent.chat, [], 'gpt-4'), 'synthetic answer')
        self.assertEqual(observed, [{'guard': None, 'policy': None, 'output_limit': 8192},
                                    {'guard': None, 'policy': None, 'output_limit': 2048}])

    def flow(self, truncated=False, invalid=False, events=None):
        import run
        responses = demo.load_responses()
        if invalid:
            responses['classification'] = 'PRIVATE malformed sections'
        pending = iter(('planning', 'decision', 'classification', 'talk'))
        observed, sent = [], []
        policy = FailurePolicy()
        def inference(chat, model, url, token, guard=None, policy=None, *, output_limit=2048):
            stage = next(pending)
            observed.append((stage, output_limit, guard, policy))
            if truncated and stage == 'classification':
                raise OperationError('chat', 'OUTPUT_TRUNCATED')
            return responses[stage]
        with demo.offline_boundaries() as external, tempfile.TemporaryDirectory() as directory, \
                patch.object(run, 'inference_chat', inference), \
                patch.object(run, 'load_runtime_setting', side_effect=lambda name: 'synthetic-setting'), \
                contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            image = root/'image.png'
            image.write_bytes((demo.FIXTURES/'synthetic.png').read_bytes())
            snapshot = root/'snapshot.json'
            snapshot.write_text(demo.snapshot_text(json.dumps(demo.load_tree())))
            agent = run.MobileAgentStateMachine(tts=lambda *args: None, voice=lambda *args: 'Show notes',
                                                beep=lambda: None, policy=policy)
            listener = run.UIListener(agent, acquire=lambda *args, **kwargs: (str(image), str(snapshot)), send=sent.append)
            if events is not None:
                load_tool('live_backend').observe_listener(listener, run,
                    lambda event, **data: events.append((event, data)))
            demo.admit_context(listener)
            listener._process_message(json.dumps(demo.message('REQUEST_UI_UPDATE', demo.REQUEST_ID)))
            if not truncated and not invalid:
                listener._process_message(json.dumps(demo.message('REQUEST_TALK', 'synthetic-talk', baseRequestId=demo.REQUEST_ID)))
            self.assertEqual(external, [])
        return observed, sent, agent, policy

    def test_only_real_classification_uses_8192_and_preserves_guard_policy(self):
        observed, sent, agent, policy = self.flow()
        self.assertEqual([(stage, limit) for stage, limit, _, _ in observed],
                         [('planning', 2048), ('decision', 2048), ('classification', 8192), ('talk', 2048)])
        self.assertTrue(all(guard is not None and selected_policy is policy for _, _, guard, selected_policy in observed))
        self.assertTrue(all('payload' in json.loads(frame) for frame in sent))

    def test_truncation_rolls_back_partial_derived_state_and_sends_fixed_error(self):
        observed, sent, agent, _ = self.flow(truncated=True)
        self.assertEqual([stage for stage, _, _, _ in observed], ['planning', 'decision', 'classification'])
        self.assertEqual(len(sent), 1)
        reply = json.loads(sent[0])
        self.assertEqual(reply['error'], 'OUTPUT_TRUNCATED')
        self.assertNotIn('payload', reply)
        self.assertEqual(agent.state, 'waiting')
        self.assertIsNone(agent.current_request_id)
        self.assertIsNone(agent.target_element)
        self.assertEqual(agent.subtask_history, [])
        self.assertFalse(getattr(agent, 'all_classified_info', None))
        self.assertFalse(getattr(agent, 'classification_source', None))
        self.assertEqual(agent.ui_layout_info_original, demo.load_tree())

    def test_injected_two_argument_chat_remains_compatible(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = demo.run_demo(include_talk=True)
        demo.verify_outcome(result)
        self.assertEqual(result['external_calls'], [])

    def test_validation_failure_is_static_invalid_output(self):
        events = []
        _, sent, _, _ = self.flow(invalid=True, events=events)
        reply = json.loads(sent[0])
        self.assertEqual(reply['error'], 'ValidationError')
        self.assertNotIn('payload', reply)
        self.assertNotIn('PRIVATE', json.dumps(reply))
        replies = [data for event, data in events if event == 'reply_sent' and data.get('reply_outcome') == 'ERROR']
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]['error_code'], 'INVALID_OUTPUT')
        self.assertNotIn('PRIVATE', json.dumps(events))


class ManualOutputBudgetTests(unittest.TestCase):
    def test_manual_wrapper_preserves_limits_guards_counts_and_no_partial_output_evidence(self):
        runtime = load_tool('live_backend')
        responses = iter((Response(), Response(), Response(PRIVATE, 'length')))
        calls, events, saved = [], [], []
        def post(*args, **kwargs):
            calls.append(kwargs)
            return next(responses)
        fake = SimpleNamespace(inference_chat=api.inference_chat, text2audio=lambda *args, **kwargs: None,
                               OperationError=OperationError)
        counts = runtime.install_call_wrappers(fake, lambda event, **data: events.append((event, data)),
                                              'gpt-6-luna', evidence=lambda name, build: saved.append((name, build())))
        policy = FailurePolicy(attempts=3)
        guard = SimpleNamespace(check=lambda: None, remaining=lambda: 100)
        with patch.dict('sys.modules', {'requests': SimpleNamespace(post=post, exceptions=network_errors)}):
            self.assertEqual(fake.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'synthetic-no-key',
                                                 guard=guard, policy=policy), 'synthetic answer')
            self.assertEqual(fake.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'synthetic-no-key',
                                                 guard=guard, policy=policy, output_limit=8192), 'synthetic answer')
            with self.assertRaises(OperationError) as raised:
                fake.inference_chat([], 'gpt-4', 'https://offline.test/chat', 'synthetic-no-key',
                                    guard=guard, policy=policy, output_limit=8192)
        self.assertEqual(raised.exception.code, 'OUTPUT_TRUNCATED')
        self.assertEqual([item['json']['max_completion_tokens'] for item in calls], [2048, 8192, 8192])
        self.assertEqual(counts, {'chat': 3, 'tts': 0})
        self.assertEqual(sum(event == 'call_done' for event, _ in events), 2)
        self.assertEqual(events[-1][1]['error_code'], 'OUTPUT_TRUNCATED')
        self.assertFalse(any(name == 'chat-003-output' for name, _ in saved))
        self.assertEqual([body['output_limit'] for name, body in saved if name.endswith('-input')],
                         [2048, 8192, 8192])
        self.assertNotIn(PRIVATE, json.dumps(events))

    def test_console_truncation_and_invalid_output_hints_are_static_and_deduplicated(self):
        module = load_tool('manual_test')
        for code, hint in (('OUTPUT_TRUNCATED', '输出上限'), ('INVALID_OUTPUT', '校验')):
            console = module.ConsoleEvents()
            event = {'event': 'call_failure', 'stage': 'chat', 'event_id': 1,
                     'error_code': code, 'message': PRIVATE, 'finish_reason': PRIVATE}
            text = ' '.join(console.consume(event))
            self.assertIn(code, text)
            self.assertIn(hint, text)
            self.assertNotIn(PRIVATE, text)
            self.assertNotIn('网络', text)
            self.assertEqual(console.consume(dict(event, event='reply_sent')), [])
            self.assertEqual(console.failures, 1)

    def test_runner_metadata_maps_validation_without_exception_body(self):
        result = load_tool('live_backend').error_metadata(ValidationError(PRIVATE))
        self.assertEqual(result['error_code'], 'INVALID_OUTPUT')
        self.assertNotIn(PRIVATE, json.dumps(result))

    def test_fixed_runner_hash_accepts_current_source_and_rejects_changed_source(self):
        launcher = load_tool('manual_test')
        self.assertEqual(hashlib.sha256(launcher.RUNNER.read_bytes()).hexdigest(), launcher.RUNNER_SHA)
        self.assertTrue(callable(launcher.runner_module().install_call_wrappers))
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory)/'live_backend.py'
            altered.write_text('raise AssertionError("untrusted runner imported")\n')
            with patch.object(launcher, 'RUNNER', altered):
                with self.assertRaisesRegex(RuntimeError, '^RUNNER_CHANGED$'):
                    launcher.runner_module()


if __name__ == '__main__':
    unittest.main()
