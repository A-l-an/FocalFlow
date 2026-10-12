import os
import tempfile
import time
import subprocess
import ujson as json  # 确保兼容原有 json_filter.py
import logging
from MobileAgent.failure import FailurePolicy, OperationError


# One process-owned current snapshot. TemporaryDirectory removes only this
# directory on normal process exit; historical user_data is never touched.
_runtime_directory = None


def _runtime_path(filename):
    global _runtime_directory
    if _runtime_directory is None:
        _runtime_directory = tempfile.TemporaryDirectory(prefix="focalflow-runtime-")
    return os.path.join(_runtime_directory.name, filename)


def get_size(adb_path):
    command = adb_path + " shell wm size"
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    resolution_line = result.stdout.strip().split('\n')[-1]
    width, height = map(int, resolution_line.split(' ')[-1].split('x'))
    return width, height
    
    
def get_xml(adb_path):
    process = subprocess.Popen([adb_path, 'shell', 'uiautomator', 'dump'], stdout=subprocess.PIPE)
    process.communicate()
    subprocess.run([adb_path, 'pull', '/sdcard/window_dump.xml', './xml/window_dump.xml'])


def take_screenshots(adb_path, num_screenshots, output_folder, crop_y_start, crop_y_end, slide_y_start, slide_y_end):
    from PIL import Image
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for i in range(num_screenshots):
        command = adb_path + f" shell rm /sdcard/screenshot{i}.png"
        subprocess.run(command, capture_output=True, text=True, shell=True)
        command = adb_path + f" shell screencap -p /sdcard/screenshot{i}.png"
        subprocess.run(command, capture_output=True, text=True, shell=True)
        command = adb_path + f" pull /sdcard/screenshot{i}.png {output_folder}"
        subprocess.run(command, capture_output=True, text=True, shell=True)
        image = Image.open(f"{output_folder}/screenshot{i}.png")
        cropped_image = image.crop((0, crop_y_start, image.width, crop_y_end))
        cropped_image.save(f"{output_folder}/screenshot{i}.png")
        subprocess.run([adb_path, 'shell', 'input', 'swipe', '500', str(slide_y_start), '500', str(slide_y_end)])


TRANSPORT_SLOT = '/storage/emulated/0/Android/data/com.android.talkback/files/screen_reader_logs/virtual_tree_logs/User_transport/Task_transport/virtual_tree_current.json'


def adb_run(argv, policy=None, guard=None, cleanup=False):
    policy = policy or FailurePolicy()
    if guard is not None and not cleanup: guard.check()
    timeout = policy.adb if guard is None or cleanup else min(policy.adb, guard.remaining())
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OperationError('adb', 'TIMEOUT') from None
    except OSError:
        raise OperationError('adb', 'EXEC_FAILED') from None
    if result.returncode != 0:
        raise OperationError('adb', 'NONZERO_EXIT')
    if guard is not None and not cleanup: guard.check()
    return result


def pull_transport_snapshot(adb_path, policy=None, guard=None):
    path = _runtime_path('snapshot.json')
    if os.path.exists(path): os.remove(path)
    try:
        adb_run([adb_path, 'pull', TRANSPORT_SLOT, path], policy, guard)
        if not os.path.isfile(path): raise OperationError('adb', 'MISSING_OUTPUT')
        return path
    except BaseException:
        if os.path.exists(path): os.remove(path)
        raise


def get_screenshot_and_ui_elements(adb_path, current_user_id, current_task_id, screenshot_counter,
                                   *, expected_context, policy=None, guard=None):
    from MobileAgent.protocol import read_snapshot
    from MobileAgent.validation import require
    policy = policy or FailurePolicy()
    snapshot = pull_transport_snapshot(adb_path, policy, guard)
    before = read_snapshot(snapshot, expected_context)
    local_screenshot = _runtime_path('screenshot.png')
    if os.path.exists(local_screenshot): os.remove(local_screenshot)
    run_id = os.path.basename(os.path.dirname(local_screenshot))
    remote = '/storage/emulated/0/Android/data/com.android.talkback/files/screen_reader_logs/screenshots/' + run_id + '/'
    failure = None
    try:
        adb_run([adb_path, 'shell', 'mkdir', '-p', remote], policy, guard)
        adb_run([adb_path, 'shell', 'screencap', '-p', remote + 'screenshot.png'], policy, guard)
        adb_run([adb_path, 'pull', remote + 'screenshot.png', local_screenshot], policy, guard)
        if not os.path.isfile(local_screenshot): raise OperationError('adb', 'MISSING_OUTPUT')
    except Exception as error:
        failure = error
    finally:
        # Cleanup has its own finite budget even after request cancellation/deadline.
        for argv in ([adb_path, 'shell', 'rm', '-f', remote + 'screenshot.png'],
                     [adb_path, 'shell', 'rmdir', remote]):
            try: adb_run(argv, policy, guard, cleanup=True)
            except OperationError as error:
                logging.error('Screenshot cleanup failed: %s', error.code)
                if failure is None: failure = error
    if failure is not None:
        if os.path.exists(local_screenshot): os.remove(local_screenshot)
        raise failure from None
    snapshot = pull_transport_snapshot(adb_path, policy, guard)
    after = read_snapshot(snapshot, expected_context)
    require(before == after, 'snapshot changed during screenshot')
    if guard is not None: guard.check()
    return local_screenshot, snapshot


def get_screenshot_old(adb_path, user_id, task_id, screenshot_counter):
    from PIL import Image
    command = adb_path + " shell rm /sdcard/screenshot" + f"_{screenshot_counter}.png"
    subprocess.run(command, capture_output=True, text=True, shell=True)
    time.sleep(0.5)
    command = adb_path + " shell screencap -p /sdcard/screenshot" + f"_{screenshot_counter}.png"
    subprocess.run(command, capture_output=True, text=True, shell=True)
    time.sleep(0.5)
    command = adb_path + " pull /sdcard/screenshot" + f"_{screenshot_counter}.png" + " ./screenshot"
    subprocess.run(command, capture_output=True, text=True, shell=True)
    image_path = "./screenshot/screenshot"+ f"_{screenshot_counter}.png"
    save_path = "./screenshot/screenshot" + f"_{screenshot_counter}.jpg"
    image = Image.open(image_path)
    image.convert("RGB").save(save_path, "JPEG")
    os.remove(image_path)
    
    # 拉取UI元素日志文件
    pull_latest_file(user_id, task_id)
    # ui_log_command = adb_path + f" pull /storage/emulated/0/Android/data/com.example.blv_mobile_app/files/screen_reader_logs/ui_elements_logs/P{user_id}/Task{task_id}/ui_elements_log_0412_141017.json ./src/UI_elements/test.json"
    # subprocess.run(ui_log_command, capture_output=True, text=True, shell=True)

def get_latest_file_from_sdcard(extension="json"):
    try:
        command = f"adb shell 'ls -t /storage/emulated/0/Android/data/com.android.talkback/files/screen_reader_logs/virtual_tree_logs/User_*/Task_*/*.{extension}' | head -n 1"
        result = subprocess.check_output(command, shell=True, encoding='utf-8', stderr=subprocess.PIPE)
        return result.strip()
    except subprocess.CalledProcessError as e:
        print('Failed to get latest file:[omitted]')
        return None

def pull_file_from_device(remote_path, user_id, task_id, local_filename=None):
    if local_filename is None:
        local_filename = _runtime_path("ui.json")
    result = subprocess.run(["adb", "pull", remote_path, local_filename],
                            capture_output=True, text=True)
    if result.returncode != 0:
        logging.error("UI acquisition failed: adb pull")
        return None
    print('Pulled [omitted] -> [omitted]')
    return local_filename

def pull_latest_file(user_id, task_id):
    latest_file = get_latest_file_from_sdcard("json")
    if latest_file:
        remote_path = f"{latest_file}"
        return pull_file_from_device(remote_path, user_id, task_id)
    else:
        print("No latest file found.")
        return None

def get_keyboard(adb_path):
    from PIL import Image
    command = adb_path + " shell dumpsys input_method"
    process = subprocess.run(command, capture_output=True, text=True, shell=True, encoding='utf-8')
    output = process.stdout.strip()
    for line in output.split('\n'):
        if "mInputShown" in line:
            if "mInputShown=true" in line:
                
                for line in output.split('\n'):
                    if "hintText" in line:
                        hintText = line.split("hintText=")[-1].split(" label")[0]
                        break
                
                return True, hintText
            elif "mInputShown=false" in line:
                return False, None


def tap(adb_path, x, y):
    command = adb_path + f" shell input tap {x} {y}"
    subprocess.run(command, capture_output=True, text=True, shell=True)


def type(adb_path, text):
    text = text.replace("\\n", "_").replace("\n", "_")
    for char in text:
        if char == ' ':
            command = adb_path + f" shell input text %s"
            subprocess.run(command, capture_output=True, text=True, shell=True)
        elif char == '_':
            command = adb_path + f" shell input keyevent 66"
            subprocess.run(command, capture_output=True, text=True, shell=True)
        elif 'a' <= char <= 'z' or 'A' <= char <= 'Z' or char.isdigit():
            command = adb_path + f" shell input text {char}"
            subprocess.run(command, capture_output=True, text=True, shell=True)
        elif char in '-.,!?@\'°/:;()':
            command = adb_path + f" shell input text \"{char}\""
            subprocess.run(command, capture_output=True, text=True, shell=True)
        else:
            command = adb_path + f" shell am broadcast -a ADB_INPUT_TEXT --es msg \"{char}\""
            subprocess.run(command, capture_output=True, text=True, shell=True)


def slide(adb_path, x1, y1, x2, y2):
    command = adb_path + f" shell input swipe {x1} {y1} {x2} {y2} 500"
    subprocess.run(command, capture_output=True, text=True, shell=True)


def back(adb_path):
    command = adb_path + f" shell input keyevent 4"
    subprocess.run(command, capture_output=True, text=True, shell=True)
    
    
def home(adb_path):
    command = adb_path + f" shell am start -a android.intent.action.MAIN -c android.intent.category.HOME"
    subprocess.run(command, capture_output=True, text=True, shell=True)

def filter_json_elements(json_data):
    """
    输入已加载的 JSON 数据，返回过滤后的数据。
    """
    element_count = 0
    start_time = time.time()

    def filter_node(data):
        nonlocal element_count
        element_count += 1
        if element_count % 10000 == 0:
            logging.info('已处理 [omitted] 个元素')
        if not isinstance(data, dict):
            return None
        if not data:
            return None
        filtered = {}
        for key in ("children", "text", "contentDescription"):
            if key in data and data[key]:
                filtered[key] = data[key]
        if "children" in filtered:
            filtered_children = {}
            for key, child in filtered["children"].items():
                filtered_child = filter_node(child)
                if filtered_child:
                    filtered_children[key] = filtered_child
            if filtered_children:
                filtered["children"] = filtered_children
            else:
                del filtered["children"]
        return filtered if filtered else None

    logging.info("开始过滤 JSON 数据")
    
    if "elements" in json_data:
        # 兼容旧格式
        filtered_data = {"elements": {}}
        for key, element in json_data["elements"].items():
            filtered_element = filter_node(element)
            if filtered_element:
                filtered_data["elements"][key] = filtered_element
    else:
        # 处理新格式
        filtered_data = filter_node(json_data)

    end_time = time.time()
    logging.info('过滤完成，共处理 [omitted] 个元素，耗时 [omitted] 秒')
    return filtered_data