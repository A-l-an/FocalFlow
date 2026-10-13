"""User-operated, bounded FocalFlow launcher with independent exit supervision."""
import datetime
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import socket
from urllib.parse import urlsplit
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[2]
BASE = Path(os.environ.get('FOCALFLOW_STATE_DIR', str(Path.home() / 'Library/Application Support/FocalFlow'))).expanduser()
RUNNER = Path(__file__).with_name('live_backend.py')
RUNNER_SHA = 'e6bf978489d4e66252767afe279b2159c7d33d5806bf5a26a2f84a54702910a6'
PYTHON = os.environ.get('FOCALFLOW_PYTHON', sys.executable)
CONFIG = Path(os.environ.get('FOCALFLOW_CONFIG', str(Path.home() / '.config/focalflow/providers.env'))).expanduser()
ADB = os.environ.get('FOCALFLOW_ADB') or shutil.which('adb') or 'adb'
OWN_COMPONENTS = frozenset((
    'com.android.talkback/com.google.android.accessibility.talkback.TalkBackService',
    'com.android.talkback/com.google.android.marvin.talkback.TalkBackService',
))
CAUSES = frozenset(('PROXY_ERROR', 'TLS_ERROR', 'DNS_ERROR', 'CONNECT_TIMEOUT',
    'READ_TIMEOUT', 'TIMEOUT', 'CONNECTION_REFUSED', 'CONNECTION_RESET',
    'NETWORK_UNREACHABLE', 'CONNECTION_ERROR'))
ERROR_CODES = frozenset(('NETWORK_ERROR', 'NETWORK_TIMEOUT', 'PROVIDER_ERROR', 'HTTP_ERROR',
    'INVALID_RESPONSE', 'RESPONSE_LIMIT', 'LIVE_CALL_LIMIT', 'DEADLINE_EXCEEDED',
    'OUTPUT_TRUNCATED', 'PORT_IN_USE',
    'INVALID_BASE_OR_BUSY', 'INVALID_OUTPUT', 'CANCELLED', 'ACQUIRE_FAILED',
    'RUNNER_CHANGED', 'LOCAL_RUNTIME_MISSING', 'PRIVATE_CONFIG_MISSING_OR_PERMISSIONS',
    'BACKEND_SOURCE_MISSING', 'ADB_UNAVAILABLE', 'TARGET_FORMAT', 'CONFIG_FORMAT',
    'CONFIG_FIELDS', 'CONFIG_SELECTION', 'CONFIG_PERMISSIONS', 'START_FAILED', 'NETWORK_PREFLIGHT_FAILED'))


def safe_code(value, allowed, fallback='UNKNOWN'):
    return value if isinstance(value, str) and value in allowed else fallback


class ConsoleEvents:
    """Only allowlisted metadata reaches the Terminal; one line per logical failure."""
    def __init__(self):
        self.failures = 0
        self.counts = {'chat': 0, 'tts': 0}
        self.awaiting_error_reply = None
        self.connected = False

    def consume(self, event):
        kind = event.get('event')
        stage = safe_code(event.get('stage'), ('chat', 'tts', 'voice', 'request', 'runner'), 'runner')
        number = event.get('event_id')
        ident = '#%d' % number if type(number) is int and number > 0 else '#?'
        stamp = event.get('time_utc')
        clock = stamp[11:19] if isinstance(stamp, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', stamp) else '--:--:--'
        prefix = '[%s UTC %s]' % (clock, ident)
        if kind == 'call_begin':
            if stage in self.counts: self.counts[stage] += 1
            self.awaiting_error_reply = None
            return []
        if kind == 'runner_ready':
            return [prefix + ' 电脑正在监听 9998，等待已开启的手机 FocalFlow 连接。']
        if kind == 'protocol_received' and event.get('protocol_type') == 'ROLE':
            return [prefix + ' 已收到手机握手请求，正在确认后端会话。']
        if kind == 'session_ready_sent' and event.get('protocol_type') == 'SESSION_READY':
            self.connected = True
            return [prefix + ' 后端会话已就绪，确认已发送到手机；请离开设置进入美团。']
        if kind == 'reply_sent' and event.get('success_reply'):
            self.awaiting_error_reply = None
            return [prefix + ' 分析结果已发送到手机；手机应用结果仍需手动确认。']
        if kind not in ('call_failure', 'reply_sent', 'runner_failure'):
            return []
        code = safe_code(event.get('error_code'), ERROR_CODES)
        if kind == 'reply_sent':
            if self.awaiting_error_reply == code:
                self.awaiting_error_reply = None
                return []
            stage = 'request'
        self.failures += 1
        if kind == 'call_failure': self.awaiting_error_reply = code
        cause = safe_code(event.get('cause_code'), CAUSES, '')
        status = event.get('http_status')
        details = code + (' / ' + cause if cause else '')
        if type(status) is int and 100 <= status <= 599: details += ' / HTTP %d' % status
        if code == 'OUTPUT_TRUNCATED': action = '模型回复达到输出上限，内容不完整；这次分析未完成。'
        elif code == 'PORT_IN_USE': action = '电脑监听端口被占用，后端未启动；确认上一轮已完全停止后再重启。'
        elif code == 'INVALID_OUTPUT': action = '返回数据未通过格式或节点校验；这次分析未完成。'
        elif cause == 'PROXY_ERROR': action = '检查电脑代理是否运行，并确认代理可访问已配置的模型服务。'
        elif cause == 'DNS_ERROR': action = '已配置的模型接口域名无法解析；检查电脑 DNS 与网络，恢复后重新启动本轮。'
        elif cause == 'TLS_ERROR': action = '检查代理与证书连接后重新启动本轮。'
        elif code in ('NETWORK_ERROR', 'NETWORK_TIMEOUT'): action = '检查电脑网络与代理；这次模型请求未成功。'
        elif code == 'HTTP_ERROR' and status in (401, 403): action = '检查已保存的服务凭据与授权。'
        elif code == 'HTTP_ERROR' and status == 429: action = '检查服务额度，稍后再启动本轮。'
        elif code == 'LIVE_CALL_LIMIT': action = '本轮调用上限已到；停止后再开始新一轮。'
        elif code == 'DEADLINE_EXCEEDED': action = '本轮请求超时；检查连接后再试。'
        else: action = '查看本轮私有日志中的对应事件，再检查电脑与手机连接。'
        return [prefix + ' ' + stage + ' 失败：' + details + '。' + action]


def print_events(directory, console, printed):
    path = directory / 'live-events.jsonl'
    if not path.exists(): return printed
    lines = path.read_text().splitlines()
    while printed < len(lines):
        try: event = json.loads(lines[printed])
        except json.JSONDecodeError: break
        printed += 1
        for line in console.consume(event): print(line, flush=True)
    return printed


def runner_module():
    if hashlib.sha256(RUNNER.read_bytes()).hexdigest() != RUNNER_SHA:
        raise RuntimeError('RUNNER_CHANGED')
    spec = importlib.util.spec_from_file_location('focalflow_manual_runner', str(RUNNER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight():
    if not Path(PYTHON).is_file() or not Path(ADB).is_file(): raise RuntimeError('LOCAL_RUNTIME_MISSING')
    if not CONFIG.is_file() or CONFIG.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError('PRIVATE_CONFIG_MISSING_OR_PERMISSIONS')
    if not (SOURCE / 'run.py').is_file():
        raise RuntimeError('BACKEND_SOURCE_MISSING')
    return runner_module()


def probe_chat_endpoint(url):
    """No model call/authentication; use production proxy/CA routing, not direct DNS."""
    import requests
    source = str(SOURCE)
    if source not in sys.path: sys.path.insert(0, source)
    from MobileAgent.api import network_cause_code
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return {'reachable': False, 'cause_code': 'CONNECTION_ERROR'}
    session = requests.Session()
    response = None
    try:
        settings = session.merge_environment_settings(url, {}, True, None, None)
        # Preserve env proxy/NO_PROXY and CA settings, then prevent implicit netrc
        # credentials. A fresh session has no application token or cookies.
        session.trust_env = False
        response = session.get(url, timeout=(3, 3), allow_redirects=False, **settings)
        return {'reachable': True, 'layers': 'HTTP_ONLY', 'http_status': response.status_code}
    except requests.exceptions.RequestException as error:
        return {'reachable': False, 'cause_code': network_cause_code(error)}
    finally:
        if response is not None: response.close()
        session.close()


def network_preflight():
    # DNS can block below socket's timeout: bound the entire metadata-only probe.
    try:
        result = subprocess.run([PYTHON, '-B', str(Path(__file__).resolve()), '--network-check'],
            capture_output=True, text=True, timeout=6)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError): data = {}
    if data.get('reachable') is True: return
    error = RuntimeError('NETWORK_PREFLIGHT_FAILED')
    error.cause_code = safe_code(data.get('cause_code'), CAUSES, 'TIMEOUT')
    raise error


def startup_failure(directory, error):
    code = safe_code(error.args[0] if len(error.args) == 1 else None, ERROR_CODES, 'START_FAILED')
    cause = safe_code(getattr(error, 'cause_code', None), CAUSES, '')
    event = {'event': 'runner_failure', 'event_id': 1, 'stage': 'runner', 'error_code': code,
             'time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    if cause: event['cause_code'] = cause
    with (directory / 'live-events.jsonl').open('a') as file: file.write(json.dumps(event) + '\n')


def disable_phone_service(serial, adb=ADB):
    """Remove only our exact accessibility components; preserve all other services."""
    def command(args):
        return subprocess.run([adb, '-s', serial] + args, capture_output=True, text=True, timeout=5)
    try:
        read = command(['shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'])
        if read.returncode: return 'UNVERIFIED'
        raw = read.stdout.strip()
        components = [] if raw in ('', 'null') else raw.split(':')
        remaining = [part for part in components if part not in OWN_COMPONENTS]
        if len(remaining) != len(components):
            write = command(['shell', 'settings', 'put', 'secure', 'enabled_accessibility_services', ':'.join(remaining) if remaining else 'null'])
            if write.returncode: return 'UNVERIFIED'
        verify = command(['shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'])
        if verify.returncode or any(part in OWN_COMPONENTS for part in verify.stdout.strip().split(':')):
            return 'UNVERIFIED'
        return 'DISABLED'
    except (OSError, subprocess.TimeoutExpired):
        return 'UNVERIFIED'


class ChildExitInfo(ctypes.Structure):
    # Darwin SDK sys/signal.h siginfo_t. The launcher targets this macOS host.
    _fields_ = [('signo', ctypes.c_int), ('error', ctypes.c_int), ('code', ctypes.c_int),
                ('pid', ctypes.c_int), ('uid', ctypes.c_uint), ('status', ctypes.c_int),
                ('address', ctypes.c_void_p), ('value', ctypes.c_void_p),
                ('band', ctypes.c_long), ('reserved', ctypes.c_ulong * 7)]


waitid = ctypes.CDLL(None, use_errno=True).waitid
waitid.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ChildExitInfo), ctypes.c_int]
waitid.restype = ctypes.c_int


def leader_exited(child):
    """Observe exit without reaping: the leader PID anchors ownership through group cleanup."""
    info = ChildExitInfo()
    if waitid(os.P_PID, child.pid, ctypes.byref(info), os.WEXITED | os.WNOHANG | os.WNOWAIT):
        code = ctypes.get_errno()
        if code == errno.EINTR: return False
        raise OSError(code, 'CHILD_WAIT_FAILED')
    return info.pid == child.pid


def signal_owned_group(child, number):
    try: os.killpg(child.pid, number)
    except ProcessLookupError: pass
    except PermissionError:
        # Darwin returns EPERM for a group containing only an unreaped zombie.
        # Check only this still-anchored PGID; never reinterpret live members as
        # a harmless permission failure or signal a replacement/unrelated group.
        result = subprocess.run(['/bin/ps', '-o', 'pid=,stat=', '-g', str(child.pid)],
                                capture_output=True, text=True, timeout=2)
        if result.returncode not in (0, 1) or any(
                row.strip() and not row.split()[-1].startswith('Z')
                for row in result.stdout.splitlines()):
            raise


def stop_process(child, directory, grace=8):
    if child is None: return
    (directory / 'STOP').touch(mode=0o600)
    end = time.monotonic() + grace
    while not leader_exited(child) and time.monotonic() < end: time.sleep(0.02)
    # Never poll/wait/reap the leader before the final group signal. Even an
    # already exited leader retains its PID, so this PGID cannot be reused.
    signal_owned_group(child, signal.SIGTERM)
    time.sleep(min(grace, 0.2))
    signal_owned_group(child, signal.SIGKILL)
    child.wait(timeout=5)


def run_guardian(directory, parent_fd, runner_command, adb=ADB, stop_grace=8):
    """Survives Terminal/launcher death; inherited EOF pipe proves operator liveness."""
    os.umask(0o077)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    started = time.monotonic()
    child = None
    reason, result = 'child_exit', 1
    target = json.loads((directory / 'target.json').read_text())
    serial = target['serial']
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9._:-]+', serial):
        raise RuntimeError('TARGET_FORMAT')
    try:
        child = subprocess.Popen(runner_command, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        (directory / 'runner-pid.json').write_text(json.dumps({'pid': child.pid}))
        while not leader_exited(child):
            if time.monotonic() - started >= 600:
                reason = 'wall_limit'
                break
            ready, _, _ = select.select([parent_fd], [], [], 0.1)
            if ready and not os.read(parent_fd, 1):
                reason = 'operator_exit'
                break
        result = 0 if reason in ('operator_exit', 'wall_limit') else 1
    except (OSError, subprocess.SubprocessError):
        reason = 'start_failed'
    finally:
        runner_cleanup = 'STOPPED'
        try:
            stop_process(child, directory, stop_grace)
        except Exception:
            runner_cleanup = 'UNVERIFIED'
            result = 1
            # No further group signal follows failure; reap an already exited
            # owned leader without pretending its descendants were stopped.
            try:
                if child is not None and leader_exited(child): child.wait(timeout=1)
            except Exception: pass
        finally:
            try: cleanup = disable_phone_service(serial, adb)
            except Exception: cleanup = 'UNVERIFIED'
            if not target.get('had_reverse', False):
                try:
                    subprocess.run([adb, '-s', serial, 'reverse', '--remove', 'tcp:9998'], capture_output=True, timeout=5)
                except Exception: pass
            if reason == 'child_exit' and child is not None and runner_cleanup == 'STOPPED':
                result = child.returncode
            report = {'reason': reason, 'phone_cleanup': cleanup, 'runner_cleanup': runner_cleanup,
                      'runner_exit': child.returncode if child is not None else None}
            try: (directory / 'guardian-cleanup.json').write_text(json.dumps(report) + '\n')
            except OSError: result = 1
    return result


def main():
    os.umask(0o077)
    if len(sys.argv) == 4 and sys.argv[1] == '--guardian':
        return run_guardian(Path(sys.argv[2]), int(sys.argv[3]),
            [PYTHON, '-B', str(Path(__file__).resolve()), '--child', sys.argv[2]])
    if sys.argv[1:] == ['--check']:
        module = runner_module()
        with tempfile.TemporaryDirectory(prefix='focalflow-manual-offline-') as folder:
            module.ART = Path(folder); module.selftest()
        print('启动器离线检查通过；未连接手机、未读取密钥、未调用 API。')
        return 0
    if sys.argv[1:] == ['--network-check']:
        module = preflight()
        values = module.parse_config(CONFIG.read_text())
        print(json.dumps(probe_chat_endpoint(values['FOCALFLOW_CHAT_API_URL'])))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        directory = Path(sys.argv[2])
        try:
            module = preflight(); module.parse_config(CONFIG.read_text()); network_preflight()
        except Exception as error:
            startup_failure(directory, error)
            return 1
        module.ART = directory; module.TARGET = module.ART / 'target.json'
        return module.live_main()
    if sys.argv[1:]: raise RuntimeError('UNKNOWN_ARGUMENT')
    # Discover the phone before preflight so startup failures still have safe cleanup.
    devices = subprocess.run([ADB, 'devices'], capture_output=True, text=True, timeout=10)
    if devices.returncode: raise RuntimeError('ADB_UNAVAILABLE')
    targets = [line.split()[0] for line in devices.stdout.splitlines()
        if len(line.split()) == 2 and line.split()[1] == 'device']
    if len(targets) != 1:
        print('请只连接一台测试手机，解锁并允许 USB 调试，然后重试。'); return 1
    serial = targets[0]
    if not re.fullmatch(r'[A-Za-z0-9._:-]+', serial): raise RuntimeError('TARGET_FORMAT')
    guardian, control_write, directory = None, None, None
    console = ConsoleEvents()
    printed = 0
    exit_code = 0
    try:
        occupied = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:9998', '-sTCP:LISTEN'], capture_output=True, timeout=5)
        if occupied.returncode == 0:
            print('9998 端口已被占用，请先关闭旧的 FocalFlow 后端。'); return 1
        reverse = subprocess.run([ADB, '-s', serial, 'reverse', '--list'], capture_output=True, text=True, timeout=10)
        if reverse.returncode: raise RuntimeError('ADB_UNAVAILABLE')
        root = BASE / 'manual-tests';root.mkdir(mode=0o700, parents=True, exist_ok=True);root.chmod(0o700)
        stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S-')
        directory = Path(tempfile.mkdtemp(prefix=stamp, dir=str(root)))
        (directory / 'target.json').write_text(json.dumps({'serial': serial, 'had_reverse': 'tcp:9998 tcp:9998' in reverse.stdout}))
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        control_read, control_write = os.pipe()
        try:
            guardian = subprocess.Popen([PYTHON, '-B', str(Path(__file__).resolve()), '--guardian', str(directory), str(control_read)],
                env=environment, pass_fds=(control_read,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        finally: os.close(control_read)
        stop_requested = [False]
        def stop(number=None, frame=None): stop_requested[0] = True
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(number, stop)
        print('先在手机开启 FocalFlow，再启动电脑程序；手机可提前等待连接。', flush=True)
        print('正在启动点汉堡任务。每轮最多 10 分钟、24 次聊天和 12 次 TTS；Ctrl+C 停止并关闭手机 FocalFlow。', flush=True)
        print('本轮私有日志：' + str(directory), flush=True)
        printed = 0
        while guardian.poll() is None and not stop_requested[0]:
            printed = print_events(directory, console, printed)
            time.sleep(0.1)
        exit_code = guardian.returncode if guardian.returncode is not None else 0
    finally:
        if control_write is not None: os.close(control_write)
        if guardian is not None:
            try: guardian.wait(timeout=45)
            except subprocess.TimeoutExpired:
                # Separate guardian may still be doing its bounded cleanup; never kill it here.
                print('退出清理仍在进行；请查看本轮日志。', flush=True)
        if directory is not None:
            printed = print_events(directory, console, printed)
            (directory / 'manual-summary.json').write_text(json.dumps(dict(console.counts, failures=console.failures, backend_session_ready=console.connected)) + '\n')
        cleanup, runner_cleanup = None, None
        if directory is not None and (directory / 'guardian-cleanup.json').exists():
            report = json.loads((directory / 'guardian-cleanup.json').read_text())
            cleanup, runner_cleanup = report.get('phone_cleanup'), report.get('runner_cleanup')
        if cleanup is None: cleanup = disable_phone_service(serial)
        if guardian is not None and runner_cleanup != 'STOPPED':
            exit_code = 1
            print('电脑退出清理未确认：GROUP_STOP_FAILED。请查看本轮私有日志。', flush=True)
            if cleanup == 'DISABLED': print('手机 FocalFlow 无障碍服务已关闭。', flush=True)
            else: print('USB 清理未确认，请在手机无障碍设置中关闭 FocalFlow。', flush=True)
        elif cleanup == 'DISABLED': print('电脑端已停止，手机 FocalFlow 无障碍服务已关闭。', flush=True)
        else: print('电脑端已停止；USB 清理未确认，请在手机无障碍设置中关闭 FocalFlow。', flush=True)
        print('本轮计数：聊天 %d/24，TTS %d/12，失败 %d。' % (console.counts['chat'],console.counts['tts'],console.failures), flush=True)
        if directory is not None: print('私有日志：' + str(directory), flush=True)
    return exit_code


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as error:
        code = safe_code(error.args[0] if len(error.args) == 1 else None, ERROR_CODES, 'START_FAILED')
        print('FocalFlow 启动器未完成：' + code + '。检查本地运行环境与 USB 连接。', flush=True)
        raise SystemExit(1)
