"""Consume a JVM-emitted request/snapshot through real Python admission; emit its reply."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from examples import offline_demo as demo


def main():
    source = json.loads(Path(sys.argv[1]).read_text())
    request, snapshot = source['request'], source['snapshot']
    ctx = request['context']
    sent = []
    with demo.offline_boundaries(), tempfile.TemporaryDirectory(prefix='focalflow-bridge-') as tmp, contextlib.redirect_stdout(io.StringIO()):
        from run import MobileAgentStateMachine, UIListener
        from MobileAgent.protocol import read_snapshot
        path = Path(tmp) / 'snapshot.json'
        path.write_text(json.dumps(snapshot))
        read_snapshot(path, ctx)
        stages = iter(demo.load_responses()[key] for key in ('planning', 'decision', 'classification'))
        agent = MobileAgentStateMachine(chat=lambda *args: next(stages), tts=lambda *args: None,
            voice=lambda *args: 'synthetic', beep=lambda: None)
        listener = UIListener(agent, acquire=lambda *args, **kwargs: (str(demo.FIXTURES / 'synthetic.png'), str(path)), send=sent.append)
        controls = source.get('controls', [
            demo.message('ROLE', ctx=dict(ctx, snapshotSeq=0), PID='synthetic', TaskID='bridge'),
            demo.message('INVALIDATE_CONTEXT', ctx=ctx)])
        for control in controls:
            listener._process_message(json.dumps(control))
        listener._process_message(json.dumps(request))
    controls_sent=[json.loads(frame) for frame in sent if json.loads(frame).get('type') == 'SESSION_READY']
    assert len(controls_sent) == 1
    role=next(control for control in controls if control['type'] == 'ROLE')
    assert controls_sent[0] == dict(type='SESSION_READY',protocolVersion=1,context=role['context'],requestId=role['requestId'])
    sent=[frame for frame in sent if json.loads(frame).get('type') != 'SESSION_READY']
    assert len(sent) == 1 and 'payload' in json.loads(sent[0])
    assert json.loads(sent[0])['requestId'] == request['requestId']
    Path(sys.argv[2]).write_text(sent[0])
    print('cross_language_python_admission=PASS external_calls=0')


if __name__ == '__main__':
    main()
