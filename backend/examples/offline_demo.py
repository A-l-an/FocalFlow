"""Run real production parsing/state/VAT with fixed responses and no services."""
import builtins
from contextlib import ExitStack, contextmanager
import copy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


FIXTURES = Path(__file__).with_name('fixtures')
REQUEST_ID = 'synthetic-request-04'
CONTEXT = {'sessionId': '00000000-0000-4000-8000-000000000099', 'taskEpoch': 1, 'snapshotSeq': 1}


def message(kind, request_id='synthetic-control', ctx=None, **fields):
    return dict(protocolVersion=1, context=CONTEXT if ctx is None else ctx,
                type=kind, requestId=request_id, **fields)


def admit_context(listener):
    # The synthetic client consumes the control ACK separately from business replies.
    output = listener.send
    ready = []
    def handshake_output(frame):
        obj = json.loads(frame)
        if obj.get('type') == 'SESSION_READY': ready.append(obj)
        elif output is not None: output(frame)
    listener.send = handshake_output
    role = message('ROLE', ctx=dict(CONTEXT, snapshotSeq=0), PID='synthetic-user', TaskID='synthetic-task')
    try: listener._process_message(json.dumps(role))
    finally: listener.send = output
    assert ready == [dict(type='SESSION_READY', protocolVersion=1, context=role['context'], requestId=role['requestId'])], 'synthetic client did not receive correlated readiness'
    listener._process_message(json.dumps(message('INVALIDATE_CONTEXT')))


def snapshot_text(tree_text, ctx=None):
    header = json.dumps({'protocolVersion': 1, 'context': CONTEXT if ctx is None else ctx})
    return header[:-1] + ', "tree":' + tree_text + '}'



class ExternalCallBlocked(BaseException):
    """Escape even the legacy provider's broad retry/exception handlers."""


@contextmanager
def offline_boundaries():
    """Fail closed at network, subprocess and optional service/audio imports."""
    calls = []
    original_import = builtins.__import__
    forbidden_modules = {
        'requests', 'httpx', 'urllib3', 'openai', 'dashscope', 'modelscope',
        'torch', 'whisper', 'sounddevice', 'soundfile', 'pyaudio', 'pygame',
    }

    def block(*args, **kwargs):
        calls.append('external boundary')
        raise ExternalCallBlocked('offline demo attempted an external boundary')

    def guarded_import(name, *args, **kwargs):
        if name.split('.')[0] in forbidden_modules:
            return block()
        return original_import(name, *args, **kwargs)

    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.bind', 'socket.socket.sendto',
                       'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            stack.enter_context(patch(target, block))
        for name in ('posix_spawn', 'posix_spawnp'):
            if hasattr(os, name):
                stack.enter_context(patch.object(os, name, block))
        stack.enter_context(patch('builtins.__import__', guarded_import))
        yield calls


def load_tree():
    return json.loads((FIXTURES / 'synthetic_tree.json').read_text(encoding='utf-8'))


def load_responses():
    return json.loads((FIXTURES / 'fixed_responses.json').read_text(encoding='utf-8'))


def run_demo(*, tree=None, responses=None, include_talk=False, raw_tree=None):
    """Same real entry for CLI and tests. Arguments permit synthetic mutations."""
    with offline_boundaries() as external_calls, tempfile.TemporaryDirectory(
            prefix='focalflow-synthetic-') as directory:
        from run import MobileAgentStateMachine, UIListener

        tree = load_tree() if tree is None else copy.deepcopy(tree)
        responses = load_responses() if responses is None else responses
        tree_path = Path(directory) / 'synthetic_tree.json'
        image_path = Path(directory) / 'synthetic.png'
        tree_text = snapshot_text(json.dumps(tree) if raw_tree is None else raw_tree)
        tree_path.write_text(tree_text, encoding='utf-8')
        image_path.write_bytes((FIXTURES / 'synthetic.png').read_bytes())
        stages = ['planning', 'decision', 'classification']
        if include_talk:
            stages.append('talk')
        pending = iter(stages)
        calls, sent, leaving_states = [], [], []

        def fixed_chat(messages, model):
            stage = next(pending)
            calls.append(stage)
            return responses[stage]

        def acquire(adb_path, user_id, task_id, screenshot_counter, *, expected_context, policy=None, guard=None):
            calls.append('acquire')
            return str(image_path), str(tree_path)

        def voice(model, prompt):
            calls.append('voice')
            return 'Show the notes.'

        agent = MobileAgentStateMachine(
            chat=fixed_chat, tts=lambda text: calls.append('tts'),
            voice=voice, beep=lambda: calls.append('beep'))
        agent.instruction = 'Open the sample item on the fictional shelf.'
        agent.machine.before_state_change.append(lambda: leaving_states.append(agent.state))
        listener = UIListener(agent, adb_path='synthetic-adb', acquire=acquire, send=sent.append)
        listener.current_user_id = 'synthetic-user'
        listener.current_task_id = 'synthetic-task'
        admit_context(listener)
        listener._process_message(json.dumps(message('REQUEST_UI_UPDATE', REQUEST_ID,
            interaction={'text': 'Open fictional shelf'})))
        if include_talk:
            listener._process_message(json.dumps(message('REQUEST_TALK', 'synthetic-talk', baseRequestId=REQUEST_ID)))
        return {
            'agent': agent, 'sent': sent, 'calls': calls,
            'leaving_states': leaving_states, 'include_talk': include_talk,
            'external_calls': external_calls,
            'source_tree': tree,
            'fixture_unchanged': tree_path.read_text(encoding='utf-8') == tree_text,
        }


def verify_outcome(result):
    """Example expectations, NOT production input validation or rejection."""
    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    sent = result['sent']
    check(len(sent) == (2 if result['include_talk'] else 1), 'unexpected UI_UPDATE count')
    first = json.loads(sent[0])
    check(first.get('type') == 'UI_UPDATE', 'missing UI_UPDATE')
    check('error' not in first, 'production returned an error response')
    check(first.get('requestId') == REQUEST_ID, 'UI_UPDATE requestId was not preserved')

    expected = {
        'root': (False, '00000000-0000-4000-8000-000000000001'),
        'element-card': (False, '00000000-0000-4000-8000-000000000002'),
        'element-title': (True, '00000000-0000-4000-8000-000000000003'),
        'element-open': (True, '00000000-0000-4000-8000-000000000004'),
        'element-hint': (False, '00000000-0000-4000-8000-000000000005'),
        'element-other': (False, '00000000-0000-4000-8000-000000000006'),
    }
    for index, serialized in enumerate(sent):
        message = json.loads(serialized)
        root = message['payload']
        card = root['children']['element-card']
        nodes = {'root': root, 'element-card': card,
                 'element-other': root['children']['element-other']}
        nodes.update({key: card['children'][key] for key in
                      ('element-title', 'element-open', 'element-hint')})
        for key, (focus, virtual_id) in expected.items():
            if index == 1 and key == 'element-hint':
                focus = True
            check(nodes[key]['isVirtualFocusNode'] is focus, key + ' focus mismatch')
            check(nodes[key]['virtualNodeId'] == virtual_id, key + ' virtualNodeId mismatch')
        if index == 1:
            check(message.get('requestId') == 'synthetic-talk', 'Talk response lost its own requestId')
    agent = result['agent']
    check(agent.ui_layout_info_original == result['source_tree'], 'raw capture was mutated')
    for serialized in sent:
        payload = json.loads(serialized)['payload']
        check('isVirtualFocusNode' not in payload['bounds'], 'root bounds polluted')
        check('isVirtualFocusNode' not in payload['children'], 'children container polluted')
    check(agent.state == 'waiting', 'final state is not waiting')
    check(agent.current_request_id is None, 'completed requestId was not cleared')
    check(agent.action_history == ['Open fictional shelf'], 'interaction was not parsed')
    check(result['fixture_unchanged'], 'production wrote to the fixture file')
    check(result['external_calls'] == [], 'an external boundary was attempted')


def main():
    result = run_demo()
    verify_outcome(result)
    print('Synthetic fixture / fixed model responses (no inference).')
    print('requestId={}; targets={}; state={}; external_calls={}'.format(
        REQUEST_ID, ','.join(result['agent'].target_element),
        result['agent'].state, len(result['external_calls'])))
    print('Validated full-tree update: raw capture preserved; only real-node focus flags changed.')


if __name__ == '__main__':
    main()
