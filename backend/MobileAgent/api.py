import base64
import os
import tempfile
import json
import logging
import subprocess
from pathlib import Path


from MobileAgent.protocol import Cancelled
from MobileAgent.failure import FailurePolicy, CallBudget, OperationError, DeadlineExceeded, checked_bytes

from MobileAgent.config import require_env as _require_env, resolve_api_token as _resolve_api_token




def _close_http_resource(resource, stage):
    import sys
    primary = sys.exc_info()[0]
    try:
        resource.close()
    except Exception as error:
        if primary is None:
            raise OperationError(stage, 'CLOSE_FAILED') from None
        logging.warning('HTTP cleanup failed: %s', type(error).__name__)


def _requests_response_hook(budget, stage):
    def check(response, *args, **kwargs):
        # requests prepares Response.next even with allow_redirects=False, and
        # resolve_redirects consumes the body first. Reject in its earlier hook.
        try:
            budget.check()
            if not 200 <= response.status_code < 300:
                raise OperationError(stage, 'HTTP_ERROR', response.status_code)
        except (Cancelled, DeadlineExceeded, OperationError):
            _close_http_resource(response, stage)
            raise
        return response
    return check


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

AUDIO_CHUNK_FRAMES = 1600  # Submission bound, not a guarantee of native call latency.


def _read_audio_chunks(stream, frame_count, guard):
    chunks = []
    for offset in range(0, frame_count, AUDIO_CHUNK_FRAMES):
        guard.check()
        chunk, _ = stream.read(min(AUDIO_CHUNK_FRAMES, frame_count - offset))
        guard.check()
        chunks.append(chunk)
    return chunks


def play_samples(data, samplerate, guard=None):
    import sounddevice as sd
    channels = 1 if len(data.shape) == 1 else data.shape[1]
    def create():
        return sd.OutputStream(samplerate=samplerate, channels=channels, dtype=data.dtype)
    if guard is None:
        stream = create()
        primary_failed = False
        try:
            stream.start()
            stream.write(data)
            stream.stop(ignore_errors=False)
        except BaseException:
            primary_failed = True
            raise
        finally:
            try:
                stream.close(ignore_errors=False)
            except Exception as error:
                if not primary_failed:
                    raise
                logging.warning('Secondary audio cleanup failed: %s', type(error).__name__)
    else:
        with guard.own(create, lambda stream: stream.start(),
                       lambda stream: stream.abort(), lambda stream: stream.close(ignore_errors=False),
                       drain=lambda stream: stream.stop(ignore_errors=False)) as stream:
            frames = data.shape[0]
            for offset in range(0, frames, AUDIO_CHUNK_FRAMES):
                guard.check()
                chunk = data if frames <= AUDIO_CHUNK_FRAMES else data[offset:offset + AUDIO_CHUNK_FRAMES]
                stream.write(chunk)
                guard.check()


def play_audio_file(file_path, guard=None):
    import soundfile as sf
    if guard is not None:
        guard.check()
    data, samplerate = sf.read(file_path, dtype='float32')
    play_samples(data, samplerate, guard)


def text2audio_old(text, API_TOKEN=None, guard=None, policy=None):
    import time
    api_token = _resolve_api_token(API_TOKEN, "FOCALFLOW_LEGACY_TTS_API_TOKEN")
    url = _require_env("FOCALFLOW_LEGACY_TTS_API_URL")
    import requests
    budget = CallBudget(policy, guard)
    response = None
    try:
        budget.check()
        response = requests.post(url, headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_token},
            json={"model": "tts-1-hd", "input": text, "voice": "fable"}, stream=True, allow_redirects=False, timeout=budget.http_timeout(),
            hooks={'response': _requests_response_hook(budget, 'tts')})
        budget.check()
        if not 200 <= response.status_code < 300:
            raise OperationError('tts', 'HTTP_ERROR', response.status_code)
        if 'audio' not in response.headers.get('Content-Type', ''):
            raise OperationError('tts', 'INVALID_CONTENT_TYPE')
        audio = checked_bytes(response.iter_content(chunk_size=1), budget, 32 * 1024 * 1024, 'tts')
        if not audio: raise OperationError('tts', 'EMPTY_AUDIO')
        with tempfile.TemporaryDirectory(prefix="focalflow-tts-") as directory:
            path = Path(directory) / 'audio_output.mp3'
            path.write_bytes(audio)
            budget.check()
            play_audio_file(path, guard=guard)
            budget.check()
    except (Cancelled, DeadlineExceeded, OperationError):
        raise
    except Exception:
        raise OperationError('tts', 'PROVIDER_ERROR') from None
    finally:
        if response is not None: _close_http_resource(response, 'tts')


def text2audio(text, API_TOKEN=None, guard=None, policy=None):
    api_token = _resolve_api_token(API_TOKEN, "OPENAI_API_KEY")
    from openai import OpenAI, DefaultHttpxClient
    import httpx
    budget = CallBudget(policy, guard)
    budget.check()
    connect, read = budget.http_timeout()
    client, http_client = None, None
    hook_failure = [None]
    def response_boundary(response):
        # SDK 1.52 reads non-2xx error bodies eagerly before returning its stream.
        # This public HTTPX hook rejects/closes them before that SDK branch.
        try:
            budget.check()
            if not 200 <= response.status_code < 300:
                raise OperationError('tts', 'HTTP_ERROR', response.status_code)
        except (Cancelled, DeadlineExceeded, OperationError) as error:
            hook_failure[0] = error
            _close_http_resource(response, 'tts')
            raise
    try:
        timeout = httpx.Timeout(connect=connect, read=read, write=read, pool=connect)
        http_client = DefaultHttpxClient(timeout=timeout, follow_redirects=False, event_hooks={'response': [response_boundary]})
        client = OpenAI(api_key=api_token, max_retries=0, http_client=http_client, timeout=timeout)
        with tempfile.TemporaryDirectory(prefix="focalflow-tts-") as directory:
            path = Path(directory) / 'audio_output.mp3'
            budget.check()
            with client.audio.speech.with_streaming_response.create(
                    model="gpt-4o-mini-tts", voice="nova", input=text) as response:
                # Installed SDK context closes the HTTP response. Iterate explicitly
                # to bound total bytes/time even when the provider trickles data.
                audio = checked_bytes(response.iter_bytes(chunk_size=None), budget, 32 * 1024 * 1024, 'tts')
                if not audio: raise OperationError('tts', 'EMPTY_AUDIO')
                path.write_bytes(audio)
            budget.check()
            if guard is None: play_audio_file(path)
            else: play_audio_file(path, guard=guard)
            budget.check()
    except (Cancelled, DeadlineExceeded, OperationError):
        raise
    except Exception:
        # SDK wraps response-hook exceptions. Preserve interruption and our safe
        # HTTP status instead of exposing or inheriting the SDK exception chain.
        try: budget.check()
        except (Cancelled, DeadlineExceeded) as interrupted: raise interrupted from None
        if hook_failure[0] is not None: raise hook_failure[0] from None
        raise OperationError('tts', 'PROVIDER_ERROR') from None
    finally:
        if client is not None: _close_http_resource(client, 'tts')
        elif http_client is not None: _close_http_resource(http_client, 'tts')


def _play_ping(guard):
    # Keep the existing tone, but do not spawn afplay for guarded requests: process
    # creation can itself play content before a delayed Popen returns for checking.
    play_audio_file('/System/Library/Sounds/Ping.aiff', guard=guard)


def get_voice(model, initial_prompt=None, guard=None):
    if guard is not None:
        guard.check()
    import numpy as np
    import sounddevice as sd
    from scipy.io import wavfile
    with tempfile.TemporaryDirectory(prefix="focalflow-voice-") as directory:
        audio_path = os.path.join(directory, "recording.wav")
        # Setting Audio Streaming Parameters
        RATE = 16000
        CHANNELS = 1
        DURATION = 5  # 录制5秒

        try:
            # 显示可用设备信息，帮助调试
            devices = sd.query_devices()
            if guard is not None: guard.check()
            input_device = None
            macbook_mic = None
        
            # 首先寻找MacBook Pro麦克风
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    # print(f"发现输入设备 {i}: {device['name']}")
                    # 检查设备名称是否包含MacBook Pro
                    if 'MacBook Pro' in device['name']:
                        macbook_mic = i
                    if input_device is None:
                        input_device = i
        
            # 如果找到了MacBook Pro麦克风，优先使用它
            if macbook_mic is not None:
                input_device = macbook_mic
                # print(f"默认使用MacBook Pro麦克风: {devices[input_device]['name']}")
            elif input_device is None:
                print("未检测到输入设备，请检查麦克风连接")
                raise OperationError('voice', 'NO_DEVICE')
            else:
                print('未找到MacBook Pro麦克风，使用其他输入设备: [omitted]')

            # 使用sounddevice录制音频，明确指定输入设备
            print("Start recording for 5 seconds...")
            # 异步播放录音开始提示音
            if guard is None:
                subprocess.Popen(['afplay', '/System/Library/Sounds/Ping.aiff'])
            else:
                _play_ping(guard)
            # 立即开始录制
            if guard is None:
                audio_data = sd.rec(int(RATE * DURATION), samplerate=RATE, channels=CHANNELS,
                                    dtype='int16', device=input_device)
                sd.wait()
            else:
                def create_input():
                    return sd.InputStream(samplerate=RATE, channels=CHANNELS, dtype='int16', device=input_device)
                with guard.own(create_input, lambda stream: stream.start(),
                               lambda stream: stream.abort(), lambda stream: stream.close(ignore_errors=False)) as stream:
                    chunks = _read_audio_chunks(stream, int(RATE * DURATION), guard)
                    audio_data = np.concatenate(chunks, axis=0)
                    guard.check()
        
            # 检查音频数据是否有效
            if audio_data.size == 0:
                print("录制的音频数据为空")
                raise OperationError('voice', 'EMPTY_AUDIO')
            
            # 检查音频音量
            audio_max = np.max(np.abs(audio_data))
            # print(f"录音最大音量: {audio_max}")
            if audio_max < 50:  # 阈值可能需要根据实际情况调整
                print("录音音量过低，可能是麦克风静音或未正确接收声音")
        
            # 可选：如果音量太低，可以进行增益处理
            if audio_max < 500 and audio_max > 0:
                gain_factor = min(5000 / audio_max, 10)  # 限制最大增益倍数为10
                audio_data = audio_data * gain_factor
                print('已应用增益因子: [omitted]')
        
            # 保存为临时wav文件
            wavfile.write(audio_path, RATE, audio_data)
        
            # 检查文件是否已正确保存
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                print('音频文件已保存，大小: [omitted] 字节')
            else:
                raise OperationError('voice', 'RECORDING_FAILED')
        
            # 播放录音结束提示音
            if guard is None:
                subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'])
            else:
                _play_ping(guard)
                guard.check()
            # 使用whisper进行转录
            if guard is not None: guard.check()
            result = model.transcribe(audio=audio_path, language='zh', fp16=False, initial_prompt=initial_prompt)
            print('User:[omitted]')
            if guard is not None: guard.check()
            transcript = result.get('text') if isinstance(result, dict) else None
            if not isinstance(transcript, str) or not transcript.strip():
                raise OperationError('voice', 'EMPTY_TRANSCRIPT')
            return transcript

        except (Cancelled, DeadlineExceeded, OperationError):
            raise
        except KeyboardInterrupt:
            raise Cancelled("voice interrupted") from None
        except Exception as e:
            logging.error('Error during recording: %s', type(e).__name__)
            raise OperationError('voice', 'RECORDING_FAILED') from None


def network_cause_code(error):
    """Classify exception types/errno only; never inspect provider URLs or text."""
    import errno
    import socket
    import ssl
    pending, seen = [error], set()
    fallback = 'CONNECTION_ERROR'
    for _ in range(16):
        if not pending: break
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen: continue
        seen.add(id(item))
        name = type(item).__name__
        if name == 'ProxyError': return 'PROXY_ERROR'
        if isinstance(item, ssl.SSLError) or name == 'SSLError': return 'TLS_ERROR'
        if isinstance(item, socket.gaierror) or name == 'NameResolutionError': return 'DNS_ERROR'
        if name == 'ConnectTimeout': return 'CONNECT_TIMEOUT'
        if name in ('ReadTimeout', 'ReadTimeoutError'): return 'READ_TIMEOUT'
        if isinstance(item, TimeoutError) or name in ('Timeout', 'TimeoutError'): fallback = 'TIMEOUT'
        code = getattr(item, 'errno', None)
        if code == errno.ECONNREFUSED: return 'CONNECTION_REFUSED'
        if code == errno.ECONNRESET: return 'CONNECTION_RESET'
        if code in (errno.ENETUNREACH, errno.EHOSTUNREACH): return 'NETWORK_UNREACHABLE'
        pending.extend([item.__cause__, item.__context__])
        pending.extend(arg for arg in item.args if isinstance(arg, BaseException))
        reason = getattr(item, 'reason', None)
        if isinstance(reason, BaseException): pending.append(reason)
    return fallback


def inference_chat(chat, model, api_url, token, guard=None, policy=None, *, clock=None, wait=None):
    from MobileAgent.config import validate_config_value
    import time
    validate_config_value(api_url, "FOCALFLOW_CHAT_API_URL")
    validate_config_value(token, "FOCALFLOW_CHAT_API_TOKEN")
    import requests
    budget = CallBudget(policy, guard, clock or time.monotonic, wait)
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    data = {"model": model, "messages": []}
    if model == 'gpt-6-luna':
        data.update(max_completion_tokens=2048, reasoning_effort='none')
    else:
        data.update(max_tokens=2048, temperature=0.0, seed=1234)
    for role, content in chat:
        data['messages'].append({'role': role, 'content': content})
    for attempt in range(budget.policy.attempts):
        budget.check()
        response = None
        retryable = False
        error = None
        try:
            response = requests.post(api_url, headers=headers, json=data,
                                     timeout=budget.http_timeout(), stream=True, allow_redirects=False,
                                     hooks={'response': _requests_response_hook(budget, 'chat')})
            budget.check()
            status = response.status_code
            if not 200 <= status < 300:
                retryable = status == 429 or 500 <= status < 600
                error = OperationError('chat', 'HTTP_ERROR', status)
            else:
                raw = checked_bytes(response.iter_content(chunk_size=1), budget, 1024 * 1024, 'chat')
                try:
                    value = json.loads(raw.decode('utf-8'))['choices'][0]['message']['content']
                    if not isinstance(value, str) or not value.strip(): raise ValueError()
                except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
                    raise OperationError('chat', 'INVALID_RESPONSE') from None
                budget.check()
                return value
        except (Cancelled, DeadlineExceeded):
            raise
        except OperationError as failure:
            budget.check()
            if failure.code != 'HTTP_ERROR': raise
            error = failure
            retryable = failure.status == 429 or 500 <= failure.status < 600
        except Exception as exc:
            budget.check()
            # Only the provider's explicit network error categories permit retry.
            retryable = isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
            error = OperationError('chat', 'NETWORK_TIMEOUT' if isinstance(exc, requests.exceptions.Timeout) else 'NETWORK_ERROR' if retryable else 'PROVIDER_ERROR')
            if retryable: error.cause_code = network_cause_code(exc)
        finally:
            if response is not None:
                _close_http_resource(response, 'chat')
        if not retryable or attempt + 1 == budget.policy.attempts:
            raise error from None
        budget.pause()
    raise OperationError('chat', 'ATTEMPTS_EXHAUSTED')
