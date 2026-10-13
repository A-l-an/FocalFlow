#!/usr/bin/env python3
"""Temporary, operator-started production runner. --selftest never imports run."""
import json
import errno
import base64
import hashlib
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
import types

ART = Path(os.environ.get('FOCALFLOW_RUN_DIR', str(Path.home() / 'Library/Application Support/FocalFlow/manual-runtime'))).expanduser()
TARGET = ART / 'target.json'
SOURCE = str(Path(__file__).resolve().parents[2])
CONFIG = Path(os.environ.get('FOCALFLOW_CONFIG', str(Path.home() / '.config/focalflow/providers.env'))).expanduser()
KEYS = frozenset(('FOCALFLOW_CHAT_API_URL', 'FOCALFLOW_CHAT_API_TOKEN',
                  'FOCALFLOW_CHAT_MODEL', 'OPENAI_BASE_URL', 'OPENAI_API_KEY',
                  'OPENAI_TTS_MODEL', 'OPENAI_TTS_VOICE'))
PROTOCOL_TYPES = frozenset(('ROLE', 'SESSION_READY', 'INVALIDATE_CONTEXT', 'REQUEST_UI_UPDATE',
                            'REQUEST_TALK', 'UI_UPDATE', 'TALK_RESPONSE'))


def parse_config(text):
    values = {}
    for line in text.splitlines():
        words = shlex.split(line, comments=True, posix=True)
        if not words:
            continue
        if words[0] == 'export':
            words = words[1:]
        if len(words) != 1 or '=' not in words[0]:
            raise ValueError('CONFIG_FORMAT')
        key, value = words[0].split('=', 1)
        if key not in KEYS or key in values or not value or '\x00' in value:
            raise ValueError('CONFIG_FIELDS')
        values[key] = value
    if set(values) != KEYS:
        raise ValueError('CONFIG_FIELDS')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', values['FOCALFLOW_CHAT_MODEL']) or
            values['OPENAI_BASE_URL'] != 'https://api.openai.com/v1' or
            values['OPENAI_TTS_MODEL'] != 'gpt-4o-mini-tts' or
            values['OPENAI_TTS_VOICE'] != 'nova'):
        raise ValueError('CONFIG_SELECTION')
    return values


SAFE_CAUSES = frozenset(('PROXY_ERROR', 'TLS_ERROR', 'DNS_ERROR', 'CONNECT_TIMEOUT',
    'READ_TIMEOUT', 'TIMEOUT', 'CONNECTION_REFUSED', 'CONNECTION_RESET',
    'NETWORK_UNREACHABLE', 'CONNECTION_ERROR'))


def error_metadata(error):
    result = {'error_class': type(error).__name__}
    code = getattr(error, 'code', None)
    if isinstance(error, OSError) and error.errno == errno.EADDRINUSE: result['error_code'] = 'PORT_IN_USE'
    elif isinstance(code, str) and re.fullmatch(r'[A-Za-z_]{1,64}', code): result['error_code'] = code
    elif type(error).__name__ == 'ValidationError': result['error_code'] = 'INVALID_OUTPUT'
    elif len(error.args) == 1 and isinstance(error.args[0], str) and error.args[0] in (
            'CONFIG_PERMISSIONS', 'CONFIG_FIELDS', 'CONFIG_SELECTION', 'CONFIG_FORMAT', 'TARGET_FORMAT'):
        result['error_code'] = error.args[0]
    status = getattr(error, 'status', None)
    if type(status) is int and 100 <= status <= 599: result['http_status'] = status
    cause = getattr(error, 'cause_code', None)
    if isinstance(cause, str) and cause in SAFE_CAUSES: result['cause_code'] = cause
    stage = getattr(error, 'stage', None)
    if stage in ('chat', 'tts', 'voice', 'request'): result['stage'] = stage
    return result


def save_evidence(directory, emit, name, build):
    """Local observation only; callers supply content, never transport credentials."""
    try:
        directory.parent.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.parent.chmod(0o700)
        directory.chmod(0o700)

        def local_images(value):
            if isinstance(value, str) and value.startswith('data:image/'):
                header, encoded = value.split(',', 1)
                if not header.endswith(';base64'):
                    raise ValueError('IMAGE_ENCODING')
                raw = base64.b64decode(encoded, validate=True)
                digest = hashlib.sha256(raw).hexdigest()
                suffix = '.png' if raw.startswith(b'\x89PNG') else '.jpg' if raw.startswith(b'\xff\xd8') else '.image'
                filename = 'image-' + digest + suffix
                path = directory / filename
                if not path.exists():
                    with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
                        file.write(raw)
                return {'local_file': filename, 'sha256': digest}
            if isinstance(value, dict):
                return {key: local_images(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [local_images(item) for item in value]
            return value

        body = json.dumps(local_images(build()), ensure_ascii=False, allow_nan=False)
        with os.fdopen(os.open(str(directory / (name + '.json')),
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
            file.write(body + '\n')
    except Exception:
        try:
            emit('evidence_warning', error_code='SAVE_FAILED')
        except Exception:
            pass


def install_call_wrappers(run, emit, model, chat_limit=24, tts_limit=12, evidence=None):
    """Keep _live_chat unchanged; install TTS before the agent captures it."""
    counts = {'chat': 0, 'tts': 0}
    originals = run.inference_chat, run.text2audio

    def invoke(stage, limit, function, args, kwargs):
        # The production state worker serializes these logical calls.
        if counts[stage] >= limit:
            error = run.OperationError(stage, 'LIVE_CALL_LIMIT')
            emit('call_failure', **dict(error_metadata(error), stage=stage))
            raise error
        counts[stage] += 1
        number = counts[stage]
        emit('call_begin', stage=stage, call_number=number)
        if stage == 'chat' and evidence is not None:
            evidence('chat-%03d-input' % number, lambda: {
                'model': args[1], 'output_limit': kwargs['output_limit'],
                'messages': [{'role': role, 'content': content}
                                              for role, content in args[0]]})
        try:
            result = function(*args, **kwargs)
        except BaseException as error:
            emit('call_failure', **dict(error_metadata(error), stage=stage, call_number=number))
            raise
        if stage == 'chat' and evidence is not None:
            evidence('chat-%03d-output' % number, lambda: {'text': result})
        emit('call_done', stage=stage, call_number=number)
        return result

    def chat(chat, requested_model, api_url, token, guard=None, policy=None,
             *, clock=None, wait=None, output_limit=2048):
        return invoke('chat', chat_limit, originals[0],
                      (chat, model, api_url, token),
                      dict(guard=guard, policy=policy, clock=clock, wait=wait, output_limit=output_limit))

    def tts(text, API_TOKEN=None, guard=None, policy=None):
        return invoke('tts', tts_limit, originals[1], (text,),
                      dict(API_TOKEN=API_TOKEN, guard=guard, policy=policy))

    run.inference_chat, run.text2audio = chat, tts
    return counts


def protocol_metadata(obj):
    if not isinstance(obj, dict):
        return {'protocol_type': 'UNKNOWN'}
    kind = obj.get('type')
    result = {'protocol_type': kind if isinstance(kind, str) and kind in PROTOCOL_TYPES else 'UNKNOWN'}
    ctx = obj.get('context')
    seq = ctx.get('snapshotSeq') if isinstance(ctx, dict) else None
    if type(seq) is int and 0 <= seq <= 9007199254740991:
        result['snapshot_seq'] = seq
    return result


def observe_listener(listener, run, emit, evidence=None):
    process, send = listener._process_message, listener._send_to
    acquire = listener.acquire
    ui_count = [0]
    acquire_count = [0]

    def acquired(adb_path, current_user_id, current_task_id, screenshot_counter,
                 *, expected_context, policy=None, guard=None):
        result = acquire(adb_path, current_user_id, current_task_id, screenshot_counter,
                         expected_context=expected_context, policy=policy, guard=guard)
        if evidence is not None:
            try:
                acquire_count[0] += 1

                def build():
                    screenshot_path, snapshot_path = result
                    raw = Path(snapshot_path).read_bytes()
                    return {'snapshot': json.loads(raw),
                            'snapshot_raw_base64': base64.b64encode(raw).decode('ascii'),
                            'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
                            'screenshot': 'data:image/png;base64,' + base64.b64encode(
                                Path(screenshot_path).read_bytes()).decode('ascii')}

                evidence('acquire-%03d-snapshot' % acquire_count[0], build)
            except Exception:
                try:
                    emit('evidence_warning', error_code='ACQUIRE_SAVE_FAILED')
                except Exception:
                    pass
        return result

    def received(msg, connection=None):
        try:
            metadata = protocol_metadata(run.bounded_json(msg, 65536))
        except Exception:
            metadata = {'protocol_type': 'INVALID'}
        try:
            emit('protocol_received', **metadata)
        except Exception:
            pass  # Observation cannot prevent the original admission call.
        return process(msg, connection=connection)

    def sent(connection, obj, guard=None):
        result = send(connection, obj, guard=guard)
        try:
            metadata = protocol_metadata(obj)
            if obj.get('type') == 'SESSION_READY':
                emit('session_ready_sent', **dict(metadata, phone_applied='unobserved'))
                return result
            outcome = 'UNKNOWN'
            if 'error' in obj:
                outcome = 'ERROR'
                code = obj['error']
                if code == 'ValidationError':
                    metadata['error_code'] = 'INVALID_OUTPUT'
                elif isinstance(code, str) and re.fullmatch(r'[A-Za-z_]{1,64}', code):
                    metadata['error_code'] = code
            elif obj.get('type') == 'UI_UPDATE' and isinstance(obj.get('payload'), dict):
                outcome = 'UI_UPDATE'
            elif (obj.get('type') == 'TALK_RESPONSE' and obj.get('status') == 'NO_OP'
                  and 'payload' not in obj):
                outcome = 'NO_OP'
            metadata.update(reply_outcome=outcome, success_reply=outcome in ('UI_UPDATE', 'NO_OP'),
                            phone_applied='unobserved')
            if outcome == 'UI_UPDATE':
                ui_count[0] += 1
                if evidence is not None:
                    evidence('ui-%03d-payload' % ui_count[0], lambda: {'payload': obj['payload']})
                # The already validated full tree is not logged or retained here.
                nodes = [obj['payload']]
                focused = 0
                while nodes:
                    node = nodes.pop()
                    focused += node.get('isVirtualFocusNode') is True
                    nodes.extend(node.get('children', {}).values())
                metadata['focused_nodes'] = focused
            emit('reply_sent', **metadata)
        except Exception:
            pass  # A completed production send remains completed if observation fails.
        return result

    listener._process_message, listener._send_to = received, sent
    listener.acquire = acquired


def live_main():
    os.umask(0o077)
    sys.dont_write_bytecode = True
    # Write metadata only to the private event file; discard Python and native output.
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    logging.disable(logging.CRITICAL)
    event_fd = os.open(str(ART / 'live-events.jsonl'),
                       os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(event_fd, 0o600)
    events = os.fdopen(event_fd, 'w', buffering=1)
    event_lock = threading.Lock()

    event_number = [0]
    def emit(event, **metadata):
        with event_lock:
            event_number[0] += 1
            line = json.dumps(dict(event=event, event_id=event_number[0], time_utc=time.strftime(
                '%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **metadata), sort_keys=True)
            events.write(line + '\n')
            events.flush()

    stopped = threading.Event()
    signal_seen = [False]
    listener = None
    monitor = None
    runtime = None
    previous_cwd = os.getcwd()
    started = time.monotonic()

    def on_signal(number, frame):
        signal_seen[0] = True
        stopped.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    emit('runner_starting', chat_limit=24, tts_limit=12, wall_seconds=600)
    try:
        if (ART / 'STOP').exists():
            emit('runner_stopped', reason='stop_file_before_start')
            return 0
        config_stat = CONFIG.stat()
        if stat.S_IMODE(config_stat.st_mode) != 0o600 or config_stat.st_uid != os.getuid():
            raise ValueError('CONFIG_PERMISSIONS')
        os.environ.update(parse_config(CONFIG.read_text()))
        target = json.loads(TARGET.read_text())
        serial = target['serial']
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9._:-]+', serial):
            raise ValueError('TARGET_FORMAT')
        os.environ['ANDROID_SERIAL'] = serial
        del target, serial
        runtime = tempfile.TemporaryDirectory(prefix='live-runtime-', dir=str(ART))
        os.environ['TMPDIR'] = runtime.name
        tempfile.tempdir = runtime.name
        os.chdir(runtime.name)
        sys.path.insert(0, SOURCE)
        import run
        evidence_dir = ART / 'private-evidence' / ('run-' + time.strftime('%Y%m%dT%H%M%S') + '-%d' % os.getpid())
        evidence = lambda name, build: save_evidence(evidence_dir, emit, name, build)
        install_call_wrappers(run, emit, os.environ['FOCALFLOW_CHAT_MODEL'], evidence=evidence)
        agent = run.MobileAgentStateMachine(task_preset=run.BURGER_PRESET)
        listener = run.UIListener(agent, run.adb_path)
        observe_listener(listener, run, emit, evidence=evidence)

        def watch():
            ready = False
            while True:
                reason = ('signal' if signal_seen[0] else 'stop_file'
                          if (ART / 'STOP').exists() else 'wall_limit'
                          if time.monotonic() - started >= 600 else None)
                if reason:
                    emit('runner_stopping', reason=reason)
                    stopped.set()
                    listener.stop_worker()
                    return
                if stopped.is_set():
                    return
                server = listener._server
                if not ready and server is not None:
                    try:
                        if server.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
                            ready = True
                            emit('runner_ready', port=9998, listening=True)
                    except OSError:
                        pass
                stopped.wait(0.1)

        monitor = threading.Thread(target=watch, name='live-run-watchdog', daemon=True)
        monitor.start()
        listener.ensure_adb_reverse(9998)
        if not stopped.is_set():
            listener.run_server(9998)
        emit('runner_stopped', reason='server_returned')
        return 0
    except BaseException as error:
        emit('runner_failure', **error_metadata(error))
        return 1
    finally:
        stopped.set()
        if listener is not None:
            listener.stop_worker()
        if monitor is not None:
            monitor.join(8)
        os.chdir(previous_cwd)
        if runtime is not None:
            runtime.cleanup()
        events.close()


def selftest():
    """Offline fake module only: not an API, audio, socket, or phone test."""
    class OperationError(RuntimeError):
        def __init__(self, stage, code):
            self.stage, self.code = stage, code

    fake = types.ModuleType('fake_run')
    fake.OperationError = OperationError
    observed, events = [], []
    guard, policy, clock, wait = object(), object(), object(), object()
    response = object()

    def original(*args, **kwargs):
        observed.append((args, kwargs))
        return response

    fake.inference_chat = original
    fake.text2audio = original
    fake._live_chat = object()
    identity = fake._live_chat
    counts = install_call_wrappers(fake, lambda event, **kw: events.append((event, kw)),
                                   'gpt-4o', chat_limit=1, tts_limit=1)
    assert fake._live_chat is identity
    assert fake.inference_chat([], 'gpt-4', 'fake-url', 'fake-token', guard, policy,
                               clock=clock, wait=wait, output_limit=8192) is response
    assert observed[-1] == (([], 'gpt-4o', 'fake-url', 'fake-token'),
                           dict(guard=guard, policy=policy, clock=clock, wait=wait, output_limit=8192))
    # Mirrors the production constructor and _checked identity branch.
    fake_agent_tts = fake.text2audio
    assert fake_agent_tts is fake.text2audio
    assert fake_agent_tts('synthetic', guard=guard, policy=policy) is response
    assert observed[-1] == (('synthetic',), dict(API_TOKEN=None, guard=guard, policy=policy))
    for function, args in ((fake.inference_chat, ([], 'gpt-4', 'fake-url', 'fake-token')),
                           (fake.text2audio, ('synthetic',))):
        try:
            function(*args, guard=guard, policy=policy)
            raise AssertionError('budget failed')
        except OperationError as error:
            assert error.code == 'LIVE_CALL_LIMIT'
    assert len(observed) == 2 and counts == {'chat': 1, 'tts': 1}
    assert [event for event, _ in events] == ['call_begin', 'call_done', 'call_begin',
                                            'call_done', 'call_failure', 'call_failure']
    fake.bounded_json = lambda text, limit: json.loads(text)
    listener = types.SimpleNamespace(_process_message=original, _send_to=original, acquire=original)
    observe_listener(listener, fake, lambda event, **kw: events.append((event, kw)))
    cases = [({'type': 'UI_UPDATE', 'payload': {'isVirtualFocusNode': True}}, 'UI_UPDATE', True),
             ({'type': 'TALK_RESPONSE', 'status': 'NO_OP'}, 'NO_OP', True),
             ({'type': 'UI_UPDATE', 'error': 'DEADLINE_EXCEEDED'}, 'ERROR', False),
             ({'type': 'TALK_RESPONSE', 'error': 'INVALID_BASE_OR_BUSY'}, 'ERROR', False),
             ({'type': 'ERROR'}, 'UNKNOWN', False),
             ({'type': 'NO_OP'}, 'UNKNOWN', False),
             ({'type': 'UNKNOWN'}, 'UNKNOWN', False),
             ({'type': 'TALK_RESPONSE'}, 'UNKNOWN', False)]
    for obj, outcome, success in cases:
        assert listener._send_to(None, obj, guard=guard) is response
        assert events[-1][1]['reply_outcome'] == outcome
        assert events[-1][1]['success_reply'] is success

    def failed_observation(*args, **kwargs):
        raise ValueError('synthetic observer failure')

    isolated = types.SimpleNamespace(_process_message=original, _send_to=original, acquire=original)
    observe_listener(isolated, fake, failed_observation)
    assert isolated._send_to(None, {'type': 'UI_UPDATE', 'payload': {}}, guard=guard) is response
    assert isolated._process_message('{"type":"ROLE"}') is response
    # Bad observational traversal must not change a completed send either.
    assert listener._send_to(None, {'type': 'UI_UPDATE', 'payload': {'children': None}}) is response
    with tempfile.TemporaryDirectory(prefix='offline-evidence-', dir=str(ART)) as folder:
        directory = Path(folder) / 'private-evidence' / 'run-offline'
        evidence = lambda name, build: save_evidence(directory, lambda event, **kw: events.append((event, kw)), name, build)
        raw_image = b'\x89PNG\r\n\x1a\nsynthetic-bytes'
        data_image = 'data:image/jpeg;base64,' + base64.b64encode(raw_image).decode('ascii')
        messages = [['user', [{'type': 'text', 'text': 'synthetic prompt'},
                              {'type': 'image_url', 'image_url': {'url': data_image}}]]]
        fake.inference_chat = lambda *a, **kw: 'synthetic model answer'
        fake.text2audio = original
        install_call_wrappers(fake, lambda *a, **kw: None, 'gpt-4o', chat_limit=1, evidence=evidence)
        assert fake.inference_chat(messages, 'gpt-4', 'secret-url-marker', 'secret-token-marker') == 'synthetic model answer'
        try:
            fake.inference_chat(messages, 'gpt-4', 'secret-url-marker', 'secret-token-marker')
            raise AssertionError('budget failed')
        except OperationError:
            pass
        saved = json.loads((directory / 'chat-001-input.json').read_text())
        reference = saved['messages'][0]['content'][1]['image_url']['url']
        assert (directory / reference['local_file']).read_bytes() == raw_image
        assert reference['sha256'] == hashlib.sha256(raw_image).hexdigest()
        assert messages[0][1][1]['image_url']['url'] == data_image  # No mutation.
        assert json.loads((directory / 'chat-001-output.json').read_text())['text'] == 'synthetic model answer'
        assert not (directory / 'chat-002-input.json').exists()
        saved_listener = types.SimpleNamespace(_process_message=original, _send_to=original, acquire=original)
        observe_listener(saved_listener, fake, lambda *a, **kw: None, evidence=evidence)
        payload = {'isVirtualFocusNode': True, 'children': {}}
        assert saved_listener._send_to(None, {'type': 'UI_UPDATE', 'payload': payload}) is response
        assert json.loads((directory / 'ui-001-payload.json').read_text()) == {'payload': payload}
        for path in directory.iterdir():
            content = path.read_bytes()
            assert b'secret-url-marker' not in content and b'secret-token-marker' not in content
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(directory.parent.stat().st_mode) == 0o700
        # A blocked output path must warn without changing success or exceptions.
        blocked = Path(folder) / 'blocked'
        blocked.write_text('synthetic blocker')
        broken = lambda name, build: save_evidence(blocked / 'run', lambda event, **kw: events.append((event, kw)), name, build)
        fake.inference_chat = lambda *a, **kw: 'unchanged'
        install_call_wrappers(fake, lambda *a, **kw: None, 'gpt-4o', evidence=broken)
        assert fake.inference_chat(messages, 'gpt-4', 'secret-url-marker', 'secret-token-marker') == 'unchanged'
        failure = RuntimeError('secret-exception-marker')

        def failing_call(*args, **kwargs):
            raise failure

        fake.inference_chat = failing_call
        install_call_wrappers(fake, lambda *a, **kw: None, 'gpt-4o', evidence=broken)
        try:
            fake.inference_chat(messages, 'gpt-4', 'secret-url-marker', 'secret-token-marker')
            raise AssertionError('provider failure was swallowed')
        except RuntimeError as error:
            assert error is failure
        assert events[-1] == ('evidence_warning', {'error_code': 'SAVE_FAILED'})
        assert 'secret-exception-marker' not in json.dumps(events)
    print('OFFLINE SELFTEST PASS: forwarding/budgets/reply outcomes; private evidence, image hash, secret exclusion, save-failure isolation; no production import or services')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    elif not sys.argv[1:]:
        sys.exit(live_main())
    else:
        raise SystemExit('Use no arguments for live mode, or --selftest for offline verification.')
