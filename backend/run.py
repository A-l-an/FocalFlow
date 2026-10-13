import os
import hashlib
import time
import copy
import shutil
import logging
import warnings
import json
import wave
import sys
from datetime import datetime
from transitions import Machine
import subprocess
import select
import socket  # 新增socket依赖
import threading
from collections import deque

from MobileAgent.failure import FailurePolicy, OperationError, DeadlineExceeded
from MobileAgent.controller import adb_run

from MobileAgent.api import inference_chat, text2audio, get_voice
from MobileAgent.protocol import Work, Cancelled, header, read_snapshot, MAX_MESSAGE_BYTES
from MobileAgent.validation import bounded_json
from MobileAgent.controller import tap, slide, back, home, get_screenshot_and_ui_elements, filter_json_elements
from MobileAgent.prompt import get_action_prompt, get_reflect_prompt, get_memory_prompt, get_process_prompt, get_decision_prompt, get_subtask_prompt, get_classify_prompt, get_talk_prompt
from MobileAgent.chat import init_subtask_chat, init_reflect_chat, init_memory_chat, add_response, add_response_two_image, init_decision_chat, init_talk_chat, init_classify_chat


import concurrent.futures


from MobileAgent.validation import (
    ValidationError, require, identifier, read_tree, tree_index, sections,
    json_section, references, scoped_index, categories as validate_categories,
    selections, focus_candidate,
)
from MobileAgent.config import require_env as _require_env
from MobileAgent.task_presets import BURGER_PRESET, HOSPITAL_PRESET

####################################### Edit your Setting #########################################
# Your ADB path
adb_path = os.environ.get('FOCALFLOW_ADB') or shutil.which('adb') or 'adb'

# Your gpt-4 API URL

# API_url = 'https://api.openai.com/v1/chat/completions'

# Your gpt-4 API Token

# token = "${DASHSCOPE_API_KEY}"

# Choose between "api" and "local". api: use the qwen api. local: use the local qwen checkpoint
caption_call_method = "api"

# Choose between "qwen-vl-plus" and "qwen-vl-max" if use api method. Choose between "qwen-vl-chat" and "qwen-vl-chat-int4" if use local method.
caption_model = "qwen-vl-plus"

# If you choose the api caption call method, input your Qwen api here


# You can add operational knowledge to help Agent operate more accurately.
# add_info = "If you want to tap an icon of an app, use the action \"Open app\". If you want to exit an app, use the action \"Home\""

# add_info = "Never select an element that is relevant to the search box as output. When you can't find an element directly related to a subtask in the current interface, consider whether the category to which the sub-element belongs is present in the interface, e.g. KFC belongs to Burger and Burger belongs to Food."
flag_burger = 0

# add_info = "If you cannot find a contact person, you should open the magnifying glass in the upper right corner to search for their name."

# Reflection Setting: If you want to improve the operating speed, you can disable the reflection agent. This may reduce the success rate.
reflection_switch = False

# Memory Setting: If you want to improve the operating speed, you can disable the memory unit. This may reduce the success rate.
memory_switch = True
###################################################################################################

def _request_log_id(request_id):
    """Correlate requests without logging arbitrary client-supplied content."""
    return hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()[:12]


def load_runtime_setting(name):
    """Validate only the live feature's configuration when it is used."""
    return _require_env({
        "API_url": "FOCALFLOW_CHAT_API_URL",
        "token": "FOCALFLOW_CHAT_API_TOKEN",
        "qwen_api": "DASHSCOPE_API_KEY",
    }[name])


def _live_chat(chat, model, guard=None, policy=None, *, output_limit=2048):
    return inference_chat(chat, model, load_runtime_setting("API_url"),
                          load_runtime_setting("token"), guard=guard, policy=policy,
                          output_limit=output_limit)


def log_api_request(api_name, start_time, response=None):
    # Never log the response. Labels are internal call-site constants.
    logging.info("%s status=complete duration=%.2f", api_name, time.time() - start_time)


def play_long_beep(duration=0.5, frequency=440, guard=None):
    """生成并播放一声较长的提示音"""
    try:
        import numpy as np
        import sounddevice as sd
        samplerate = 44100  # 采样率
        t = np.linspace(0., duration, int(samplerate * duration), endpoint=False)
        amplitude = np.iinfo(np.int16).max * 0.5
        data = amplitude * np.sin(2. * np.pi * frequency * t)
        
        from MobileAgent.api import play_samples
        play_samples(data.astype(np.int16), samplerate, guard)
    except (Cancelled, DeadlineExceeded):
        raise
    except Exception as e:
        logging.warning('播放长提示音失败: %s', type(e).__name__)

def get_all_files_in_folder(folder_path):
    file_list = []
    for file_name in os.listdir(folder_path):
        file_list.append(file_name)
    return file_list


def draw_coordinates_on_image(image_path, coordinates):
    from PIL import Image, ImageDraw
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    point_size = 10
    for coord in coordinates:
        draw.ellipse((coord[0] - point_size, coord[1] - point_size, coord[0] + point_size, coord[1] + point_size), fill='red')
    output_image_path = './screenshot/output_image.png'
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
    image.save(output_image_path)
    return output_image_path


def crop(image, box, i):
    from PIL import Image, ImageDraw
    image = Image.open(image)
    x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
    if x1 >= x2-10 or y1 >= y2-10:
        return
    cropped_image = image.crop((x1, y1, x2, y2))
    os.makedirs(temp_file, exist_ok=True)
    cropped_image.save(f"./temp/{i}.png")


def generate_local(tokenizer, model, image_file, query):
    query = tokenizer.from_list_format([
        {'image': image_file},
        {'text': query},
    ])
    response, _ = model.chat(tokenizer, query=query, history=None)
    return response


def process_image(image, query):
    api_key = load_runtime_setting("qwen_api")
    import dashscope
    from dashscope import MultiModalConversation
    dashscope.api_key = api_key
    image = "file://" + image
    messages = [{
        'role': 'user',
        'content': [
            {
                'image': image
            },
            {
                'text': query
            },
        ]
    }]
    response = MultiModalConversation.call(model=caption_model, messages=messages)
    
    try:
        response = response['output']['choices'][0]['message']['content'][0]["text"]
    except:
        response = "This is an icon."
    
    return response


def generate_api(images, query):
    icon_map = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(process_image, image, query): i for i, image in enumerate(images)}
        
        for future in concurrent.futures.as_completed(futures):
            i = futures[future]
            response = future.result()
            icon_map[i + 1] = response
    
    return icon_map


def merge_text_blocks(text_list, coordinates_list):
    merged_text_blocks = []
    merged_coordinates = []

    sorted_indices = sorted(range(len(coordinates_list)), key=lambda k: (coordinates_list[k][1], coordinates_list[k][0]))
    sorted_text_list = [text_list[i] for i in sorted_indices]
    sorted_coordinates_list = [coordinates_list[i] for i in sorted_indices]

    num_blocks = len(sorted_text_list)
    merge = [False] * num_blocks

    for i in range(num_blocks):
        if merge[i]:
            continue
        
        anchor = i
        
        group_text = [sorted_text_list[anchor]]
        group_coordinates = [sorted_coordinates_list[anchor]]

        for j in range(i+1, num_blocks):
            if merge[j]:
                continue

            if abs(sorted_coordinates_list[anchor][0] - sorted_coordinates_list[j][0]) < 10 and \
            sorted_coordinates_list[j][1] - sorted_coordinates_list[anchor][3] >= -10 and sorted_coordinates_list[j][1] - sorted_coordinates_list[anchor][3] < 30 and \
            abs(sorted_coordinates_list[anchor][3] - sorted_coordinates_list[anchor][1] - (sorted_coordinates_list[j][3] - sorted_coordinates_list[j][1])) < 10:
                group_text.append(sorted_text_list[j])
                group_coordinates.append(sorted_coordinates_list[j])
                merge[anchor] = True
                anchor = j
                merge[anchor] = True

        merged_text = "\n".join(group_text)
        min_x1 = min(group_coordinates, key=lambda x: x[0])[0]
        min_y1 = min(group_coordinates, key=lambda x: x[1])[1]
        max_x2 = max(group_coordinates, key=lambda x: x[2])[2]
        max_y2 = max(group_coordinates, key=lambda x: x[3])[3]

        merged_text_blocks.append(merged_text)
        merged_coordinates.append([min_x1, min_y1, max_x2, max_y2])

    return merged_text_blocks, merged_coordinates


def get_perception_infos(adb_path, screenshot_file, screenshot_cnt):
    from PIL import Image, ImageDraw
    from MobileAgent.text_localization import ocr
    from MobileAgent.icon_localization import det
    start_time = time.time()
    get_screenshot(adb_path, screenshot_cnt)
    log_api_request("Screenshot", start_time)
    
    width, height = Image.open(screenshot_file).size
    
    start_time = time.time()
    text, coordinates = ocr(screenshot_file, ocr_detection, ocr_recognition)
    log_api_request("OCR", start_time)
    text, coordinates = merge_text_blocks(text, coordinates)
    
    center_list = [[(coordinate[0]+coordinate[2])/2, (coordinate[1]+coordinate[3])/2] for coordinate in coordinates]
    draw_coordinates_on_image(screenshot_file, center_list)
    
    perception_infos = []
    for i in range(len(coordinates)):
        perception_info = {"text": "text: " + text[i], "coordinates": coordinates[i]}
        perception_infos.append(perception_info)
        
    coordinates = det(screenshot_file, "icon", groundingdino_model)
    
    for i in range(len(coordinates)):
        perception_info = {"text": "icon", "coordinates": coordinates[i]}
        perception_infos.append(perception_info)
        
    image_box = []
    image_id = []
    for i in range(len(perception_infos)):
        if perception_infos[i]['text'] == 'icon':
            image_box.append(perception_infos[i]['coordinates'])
            image_id.append(i)

    for i in range(len(image_box)):
        crop(screenshot_file, image_box[i], image_id[i])

    images = get_all_files_in_folder(temp_file)
    if len(images) > 0:
        images = sorted(images, key=lambda x: int(x.split('/')[-1].split('.')[0]))
        image_id = [int(image.split('/')[-1].split('.')[0]) for image in images]
        icon_map = {}
        prompt = 'This image is an icon from a phone screen. Please briefly describe the shape and color of this icon in one sentence.'
        if caption_call_method == "local":
            for i in range(len(images)):
                image_path = os.path.join(temp_file, images[i])
                icon_width, icon_height = Image.open(image_path).size
                if icon_height > 0.8 * height or icon_width * icon_height > 0.2 * width * height:
                    des = "None"
                else:
                    des = generate_local(tokenizer, model, image_path, prompt)
                icon_map[i+1] = des
        else:
            for i in range(len(images)):
                images[i] = os.path.join(temp_file, images[i])
            icon_map = generate_api(images, prompt)
        
        # Modify this part to avoid index out of range error
        for i, j in zip(image_id, range(1, len(image_id)+1)):
            if i < len(perception_infos) and j in icon_map:
                perception_infos[i]['text'] = "icon: " + icon_map[j]

    for i in range(len(perception_infos)):
        perception_infos[i]['coordinates'] = [int((perception_infos[i]['coordinates'][0]+perception_infos[i]['coordinates'][2])/2), int((perception_infos[i]['coordinates'][1]+perception_infos[i]['coordinates'][3])/2)]
        
    return perception_infos, width, height

### Load caption model ###

screenshot_cnt = 0

### Load ocr and icon detection model ###
# groundingdino_dir = snapshot_download('AI-ModelScope/GroundingDINO', revision='v1.0.0')
# groundingdino_model = pipeline('grounding-dino-task', model=groundingdino_dir)
# ocr_detection = pipeline(Tasks.ocr_detection, model='damo/cv_resnet18_ocr-detection-line-level_damo')
# ocr_recognition = pipeline(Tasks.ocr_recognition, model='damo/cv_convnextTiny_ocr-recognition-document_damo')


# thought_history = []
# subtask_history = []
# action_history = []
subtask = ""
action = ""
completed_requirements = ""
memory = ""
insight = ""
temp_file = "temp"
screenshot = "screenshot"
error_flag = False


class MobileAgentStateMachine(object):
    states = ['waiting', 'subtask', 'decision', 'talk']

    def __init__(self, *, chat=None, tts=None, voice=None, beep=None, v2t_model=None, policy=None, task_preset=None):
        self.task_preset = (BURGER_PRESET if flag_burger else HOSPITAL_PRESET) if task_preset is None else task_preset
        self.policy = policy or FailurePolicy()
        self.guard = None
        self.chat = _live_chat if chat is None else chat
        self.tts = text2audio if tts is None else tts
        self.voice = self._live_voice if voice is None else voice
        self.beep = play_long_beep if beep is None else beep
        self.machine = Machine(model=self, states=MobileAgentStateMachine.states, initial='waiting')
        
        # 定义状态转换
        self.machine.add_transition('receive_normal', 'waiting', 'subtask')
        self.machine.add_transition('subtask_to_decision', 'subtask', 'decision')
        self.machine.add_transition('decision_to_talk', 'decision', 'talk')
        self.machine.add_transition('talk_to_decision', 'talk', 'decision')
        self.machine.add_transition('talk_to_waiting', 'talk', 'waiting')
        self.machine.add_transition('decision_complete', 'decision', 'waiting')
        self.machine.add_transition('receive_change', 'waiting', 'talk')
        
        # 全局变量
        # self.instruction = "帮我用滴滴打车前往豪哥烧鸡，用最便宜的价钱"
        self.instruction = self.task_preset.instruction
        # self.thought_history = ["用户需要使用滴滴出行应用来打车，因此下一步需要打开滴滴出行应用。在截图中，找到\"滴滴出行\"图标并选择它。", "用户需要在滴滴出行应用中选择目的地。当前页面显示了出发和目的地的输入框，用户需要点击目的地输入框。"]

        # self.thought_history = []
        # self.subtask_history = ["请点击\"滴滴出行\"图标以打开应用。", "请点击目的地输入框\"您想去哪儿？\"。"]
        self.subtask_history = []
        self.action_history = []  # TODO: 需要换成用户最终点击的 UI 元素
        self.subtask = ""
        self.curScreenIntro = None
        self.last_action = ""
        self.target_element = None
        self.completed_requirements = ""
        self.memory = ""
        self.insight = ""
        self.v2t_model = v2t_model
        self.ui_listener = None
        self.current_request_id = None  # 用于存储当前请求的requestId
        
        # 模拟收到的信息，用于调试
        self.screenshot_cnt = 0
        self.screenshot_file = f""
        self.ui_layout_info_filtered = None
        self.ui_layout_info_original = None
        self.ui_layout_info_focused = None
        self.ui_layout_info_original_path = ''
        self.simulated_message = "normal"

        
    def _live_voice(self, model, initial_prompt=None):
        if self.v2t_model is None:
            import torch
            import whisper
            torch.manual_seed(1234)
            self.v2t_model = whisper.load_model("base")
        if self.guard is not None:
            self.guard.check()
            return get_voice(self.v2t_model, initial_prompt, guard=self.guard)
        return get_voice(self.v2t_model, initial_prompt)

    def _checked(self, function, *args, output_limit=None):
        guard = self.guard
        if guard is not None:
            guard.check()
        kwargs = {}
        if function is _live_chat and output_limit is not None:
            kwargs['output_limit'] = output_limit
        if function in (_live_chat, text2audio, play_long_beep) and guard is not None:
            kwargs['guard'] = guard
            if function in (_live_chat, text2audio): kwargs['policy'] = self.policy
        result = function(*args, **kwargs)
        if guard is not None:
            guard.check()
        return result

    # These are the derived fields written by the synchronous model pipeline.
    # Roll back the whole group when a request fails; keep an acquired raw capture.
    _derived_fields = (
        'thought', 'subtask', 'curScreenIntro', 'subtask_history',
        'target_element', 'relevantAreaList', 'relevantAreaAllInfoList',
        'all_classified_info', 'classification_source', 'ui_layout_info_focused',
    )

    def request_checkpoint(self):
        return {name: (value[:] if isinstance(value, list) else value)
                for name in self._derived_fields if hasattr(self, name)
                for value in [getattr(self, name)]}

    def reject_request(self, checkpoint):
        for name in self._derived_fields:
            if name in checkpoint:
                setattr(self, name, checkpoint[name])
            elif hasattr(self, name):
                delattr(self, name)
        self.current_request_id = None
        self.machine.set_state('waiting')

    def get_json_data(self, file_path):
        return read_tree(file_path)

    def on_enter_subtask(self):
        logging.info("=== Subtask Agent 开始执行 ===")
        print("执行 Subtask Agent")
        
        # 记录当前任务指令和历史信息
        logging.info('当前任务指令: [omitted]')
        logging.info('当前subtask: [omitted]')
        logging.info('上次操作: [omitted]')
        
        # get_screenshot(adb_path, user_id, task_id, screenshot_cnt)
        # Subtask Agent 代码
        tree_index(self.ui_layout_info_original)
        self.ui_layout_info_filtered = filter_json_elements(self.ui_layout_info_original)
        prompt_subtask = get_subtask_prompt(self.instruction, self.ui_layout_info_filtered, self.subtask_history, self.action_history, self.subtask, self.last_action, self.task_preset.planning_hint, error_flag, self.completed_requirements, self.memory)
        chat_subtask = init_subtask_chat()
        chat_subtask = add_response("user", prompt_subtask, chat_subtask, self.screenshot_file)

        logging.info("开始调用Subtask Agent API...")
        start_time = time.time()
        output_subtask = self._checked(self.chat, chat_subtask, 'gpt-4')
        log_api_request("Plan", start_time, output_subtask)

        thought, subtask, screen = sections(output_subtask, ('Thought', 'Subtask', 'Screen'))
        self.thought = thought.replace("\n", " ").replace(":", "").replace("  ", " ").strip()
        self.subtask = subtask.replace("\n", " ").replace("  ", " ").strip()
        self.curScreenIntro = screen.replace("\n", " ").replace("  ", " ").strip()

        # 更新subtask_history
        if self.subtask:
            self.subtask_history.append(self.subtask)
            logging.info('已将新的subtask添加到历史记录: [omitted]')
            print('已将新的subtask添加到历史记录: [omitted]')
        else:
            logging.warning("Subtask Agent未生成新的subtask")
        
        logging.info("Subtask Agent执行完毕，转向Decision Agent")
        self.subtask_to_decision()
        logging.info("=== Subtask Agent 执行结束 ===")

    def on_enter_decision(self):
        logging.info("=== Decision Agent 开始执行 ===")
        print("执行 Decision Agent")
        
        # Decision Agent 代码
        logging.info("开始生成决策...")
        self.generate_decision()
        
        # 当decision agent的output为空时，切换为waiting状态
        if not self.relevantAreaList:
            logging.warning("Decision Agent的输出为空，切换到waiting状态")
            print("Decision Agent的输出为空，切换到waiting状态。")
            self.decision_complete()
            return
        
        logging.info('Decision Agent识别到相关UI元素: [omitted]')
        logging.info('相关元素数量: [omitted]')
        
        # 新增: 对子节点进行功能性分类
        logging.info("开始对UI元素进行功能性分类...")
        self.classify_of_elements()

        # 2. 定位目标UI范围
        # logging.info("从分类结果中提取目标UI元素...")
        self.target_element = selections(
            self.all_classified_info['topmost_ui'],
            scoped_index(tree_index(self.ui_layout_info_original), self.relevantAreaList))

        # 3. 检查并优化元素可点击状态（缩小范围到元素级）
        # self.target_element = self.optimize_element_clickable()
        
        # 4. 提取元素完整信息(已经缩小)
        # self.extract_element_info()
        
        # 5 将元素信息传给GPT进行功能性分类
        # self.target_element = self.classify_element_function()
        
        # 6. 更新虚拟焦点并发送给Android
        logging.info("更新虚拟焦点并发送给Android...")
        self.update_and_send_virtual_focus()
        
        # 7. 可视化UI元素（调试用）
        # self.visualize_ui_element()
        
        # 完成决策后，进入等待状态
        logging.info("Decision Agent 完成，进入等待状态")
        print("Decision Agent 完成，进入等待状态")
        self._checked(self.beep)  # 播放滴声提示
        self.decision_complete()
        logging.info("=== Decision Agent 执行结束 ===")

    def on_enter_talk(self):
        logging.info("=== Talk Agent 开始执行 ===")
        print("执行 Talk Agent")
        
        # 1. 根据 all_classified_info 播报当前界面可用的UI类别
        require(getattr(self, 'classification_source', None) is self.ui_layout_info_original,
                'classification belongs to another capture')
        index = tree_index(self.ui_layout_info_original)
        categories = validate_categories(self.all_classified_info.get('categories'), index)
        references(self.target_element, index)
        logging.info('当前界面分类信息: [omitted]')
        
        if categories:
            category_names = ", ".join(categories.keys())
            self._checked(self.tts, f"当前界面有以下几类信息：{category_names}")
            logging.info('当前界面有以下几类信息: [omitted]')
            logging.info('播报的类别数量: [omitted]')
        else:
            self._checked(self.tts, "当前界面没有识别出任何信息类别")
            logging.warning("当前界面没有识别出任何信息类别")

        # 2. 获取用户语音输入
        logging.info("开始获取用户语音输入...")
        user_prompt = self._checked(self.voice, self.v2t_model, f"以下是和用户界面相关的一段对话，其中可能包括激活、{category_names}等和用户界面类型元素相关的名称")
        logging.info('[omitted]')

        # 3. 构建并调用Talk Agent
        logging.info("构建Talk Agent提示...")
        prompt_talk = get_talk_prompt(
            user_prompt, json.dumps(categories, ensure_ascii=False)
        )
        logging.info('Talk Agent提示构建完成，提示长度: [omitted] 字符')
        
        chat_talk = init_talk_chat()
        chat_talk = add_response("user", prompt_talk, chat_talk)
        
        logging.info("开始调用Talk Agent API...")
        start_time = time.time()
        output_talk = self._checked(self.chat, chat_talk, 'gpt-4')
        log_api_request("Talk", start_time, output_talk)
        
        # 4. 解析Talk Agent的输出
        logging.info("解析Talk Agent输出...")
        thought_talk, mode, COI = sections(
            output_talk, ('Thought', 'Mode', 'Displayed UI'), empty=('Displayed UI',))
        require(mode in ('A', 'B'), 'invalid Talk mode')
        if mode == 'A':
            require(not COI, 'mode A cannot select categories')
            # Existing mode A is a placeholder; no device action is executed.
            self.ui_listener.reply({'type': 'TALK_RESPONSE', 'status': 'NO_OP'})
        else:
            interested = [name.strip() for name in COI.replace('，', ',').split(',')]
            require(all(name in categories for name in interested), 'unknown Talk category')
            require(len(interested) == len(set(interested)), 'duplicate Talk category')
            additions = [alias for name in interested for alias in categories[name]]
            combined = list(dict.fromkeys(self.target_element + additions))
            references(combined, index)
            self.target_element = combined

        logging.info("Talk Agent 执行完毕")
        print("Talk Agent 执行完毕")
        
        # 9. 根据mode决定下一步操作
        if mode.strip() == "B":
            # B模式：激活了UI元素，需要更新虚拟焦点并转到decision状态
            logging.info("B模式：激活UI元素，更新虚拟焦点并转到decision状态")
            self.update_and_send_virtual_focus()
            self.talk_to_waiting()
            self._checked(self.beep)  # 播放滴声提示
        else:
            # A模式或其他模式：直接回到waiting状态
            logging.info("A模式或其他模式：直接回到waiting状态")
            self.talk_to_waiting()
            self._checked(self.beep)  # 播放滴声提示
        
        logging.info("=== Talk Agent 执行结束 ===")

    def generate_decision(self):
        """生成决策提示并解析结果"""

        # 构建决策提示
        prompt_decision = get_decision_prompt(
            self.instruction, self.ui_layout_info_filtered, 
            self.subtask_history, self.action_history, 
            self.subtask, self.last_action, self.task_preset.decision_hint, error_flag,
            self.completed_requirements, self.memory, self.subtask
        )
        
        # 初始化对话并添加用户提示
        chat_decision = init_decision_chat()
        chat_decision = add_response("user", prompt_decision, chat_decision, self.screenshot_file)
        
        # 调用API获取决策结果
        logging.info("开始请求 Decision Agent API...")
        print("开始请求 Decision Agent...")
        
        # 在后台线程中播放提示音，使其与网络请求同步进行
        audio_content = self.curScreenIntro + "您当前的任务是：" + self.subtask
        logging.info('播放语音提示: [omitted]')
        self._checked(self.tts, audio_content)

        start_time = time.time()
        output_decision = self._checked(self.chat, chat_decision, 'gpt-4')
        log_api_request("Decision", start_time, output_decision)

        # 解析输出
        logging.info("解析Decision Agent输出...")
        thought, output = sections(output_decision, ('Thought', 'Output'))
        areas = references(json_section(output), tree_index(self.ui_layout_info_original))
        self.thought = thought.replace("\n", " ").replace(":", "").replace("  ", " ").strip()
        self.relevantAreaList = areas

        # 查询relevantAreaList列表中的每个元素在ui_layout_info_original中的完整结构
        logging.info("提取相关UI元素的完整信息...")
        self.extract_elements_complete_info()
        logging.info('提取到的完整元素信息数量: [omitted]')

    def classify_of_elements(self):
        """
        对 `relevantAreaAllInfoList` 中存储的所有UI元素进行功能性的分类。
        这是一个agent，将所有识别出的相关UI元素作为一个整体进行处理。
        """
        logging.info("=== UI元素分类 Agent 开始执行 ===")
        
        if not hasattr(self, 'relevantAreaAllInfoList') or not self.relevantAreaAllInfoList:
            logging.warning("没有可供分类的UI元素完整信息，跳过分类步骤")
            print("没有可供分类的UI元素完整信息，跳过分类步骤。")
            self.all_classified_info = {}
            return

        print("启动UI元素组分类 Agent...")

        # 将所有识别出的元素作为一个整体输入给Agent
        elements_to_classify = self.relevantAreaAllInfoList
        element_json_for_prompt = json.dumps(elements_to_classify, ensure_ascii=False, indent=2)
        prompt_classify = get_classify_prompt(
            self.instruction, self.subtask, element_json_for_prompt, self.task_preset.classification_hint
        )
        
        chat_classify = init_classify_chat()
        chat_classify = add_response("user", prompt_classify, chat_classify, self.screenshot_file)
        
        logging.info("开始调用分类Agent API...")
        start_time = time.time()
        output_classify = self._checked(self.chat, chat_classify, 'gpt-4', output_limit=8192)
        log_api_request("####Classification####", start_time, output_classify)
        
        thought, categories_str, selected_str = sections(
            output_classify, ('Thought', 'Categories', 'SelectedUI'))
        scope = scoped_index(tree_index(self.ui_layout_info_original), self.relevantAreaList)
        categories_json = validate_categories(json_section(categories_str), scope)
        topmost_UI_json = json_section(selected_str)
        selections(topmost_UI_json, scope)

        # The result is a single classification for the entire group of elements.
        self.all_classified_info = {
            'thought': thought,
            'categories': categories_json,
            'topmost_ui': topmost_UI_json
        }
        
        self.classification_source = self.ui_layout_info_original
        logging.info("UI元素组分类 Agent 执行完毕")
        logging.info('分类结果统计 - 类别数: [omitted], 选中UI数: [omitted]')
        print("UI元素组分类 Agent 执行完毕。结果已存入 `self.all_classified_info`。")
        logging.info("=== UI元素分类 Agent 执行结束 ===")

    def extract_elements_complete_info(self):
        index = tree_index(self.ui_layout_info_original)
        references(self.relevantAreaList, index)
        self.relevantAreaAllInfoList = {alias: index[alias] for alias in self.relevantAreaList}
        return self.relevantAreaAllInfoList

    def classify_element_function(self):
        """将目标元素信息传给GPT进行功能性分类，并根据分类结果进一步缩小target_element范围"""
        # 处理target_element的不同格式
        if isinstance(self.target_element, list):
            # 如果是列表，使用第一个元素进行分类
            target_for_classification = self.target_element[0] if self.target_element else None
        elif isinstance(self.target_element, dict):
            # 如果是字典，使用第一个键进行分类
            target_for_classification = list(self.target_element.keys())[0] if self.target_element else None
        else:
            # 字符串或其他格式
            target_for_classification = self.target_element
            
        if not self.target_element_info or target_for_classification not in self.target_element_info:
            print("没有找到元素 '[omitted]' 的信息，无法进行功能分类")
            return self.target_element
        
        # 构建提示
        element_json = json.dumps(self.target_element_info, ensure_ascii=False)
        prompt_classify = get_classify_prompt(
            self.instruction, self.subtask, element_json
        )
        
        # 初始化对话
        chat_classify = init_classify_chat()
        chat_classify = add_response("user", prompt_classify, chat_classify)
        
        # 调用API获取分类结果
        start_time = time.time()
        output_classify = self._checked(self.chat, chat_classify, 'gpt-4')
        log_api_request("Element Classification", start_time, output_classify)
        
        # 解析输出
        thought = output_classify.split("### Thought ###")[-1].split("### Categories ###")[0].replace("\n", " ").replace(":", "").replace("  ", " ").strip()
        categories = output_classify.split("### Categories ###")[-1].split("### Output ###")[0].replace("\n", " ").replace("  ", " ").strip()
        topmost_UI = output_classify.split("### Output ###")[-1].replace("\n", " ").replace("  ", " ").strip()
        
        try:
            categories_str = categories.split("json")[-1].split("```")[0]
            self.UI_categories_json = json.loads(categories_str)
        except json.JSONDecodeError as e:
            logging.error('解析 UI_categories_json 失败: %s', type(e).__name__)
            print('导致失败的原始字符串: [omitted]')
            self.UI_categories_json = {}

        try:
            topmost_UI_str = topmost_UI.split("json")[-1].split("```")[0]
            self.UI_topmost_json = json.loads(topmost_UI_str)
        except json.JSONDecodeError as e:
            logging.error('解析 UI_topmost_json 失败: %s', type(e).__name__)
            print('导致失败的原始字符串: [omitted]')
            self.UI_topmost_json = None
        
        # 从新的对象列表格式中提取action_point和context_elements
        if self.UI_topmost_json and isinstance(self.UI_topmost_json, list):
            target_elements = []
            for ui_obj in self.UI_topmost_json:
                if isinstance(ui_obj, dict):
                    # 提取action_point
                    action_point = ui_obj.get('action_point')
                    if action_point:
                        target_elements.append(action_point)
                    
                    # 提取context_elements中的name字段
                    context_elements = ui_obj.get('context_elements', [])
                    if isinstance(context_elements, list):
                        for context_elem in context_elements:
                            if isinstance(context_elem, dict):
                                context_name = context_elem.get('name')
                                if context_name:
                                    target_elements.append(context_name)
            
            # 如果原始target_element是列表格式，返回列表
            if isinstance(self.target_element, list):
                return target_elements if target_elements else []
            else:
                return target_elements[0] if target_elements else self.target_element
        elif self.UI_topmost_json and isinstance(self.UI_topmost_json, dict) and len(self.UI_topmost_json) > 0:
            # 向后兼容：如果是字典格式，使用原有逻辑
            if isinstance(self.target_element, list):
                return list(self.UI_topmost_json.keys())
            else:
                return list(self.UI_topmost_json.keys())[0]
        else:
            return self.target_element

    def find_element_with_text_or_description(self, data, parent_key=None):
        """递归查找具有text或contentDescription属性的元素的直接父节点"""
        if not isinstance(data, dict):
            return None
        
        # 先检查当前层级的所有元素是否有text或contentDescription属性
        for key, value in data.items():
            if isinstance(value, dict) and ('text' in value or 'contentDescription' in value):
                return parent_key  # 返回父节点
        
        # 如果当前层级没有找到，则继续递归子元素
        for key, value in data.items():
            # 检查children字段
            if key == 'children' and isinstance(value, dict):
                result = self.find_element_with_text_or_description(value, parent_key)
                if result:
                    return result
            # 如果元素是字典但不是children字段，递归检查
            elif isinstance(value, dict):
                # 不是children字段的字典则将当前key作为parent_key传递
                result = self.find_element_with_text_or_description(value, key)
                if result:
                    return result
        
        return None

    def get_target_element(self):
        """获取目标UI元素"""
        # self.target_element = None
        if "elements" in self.relevantAreaList:
            self.target_element = self.find_element_with_text_or_description(self.relevantAreaList["elements"])
            if not self.target_element:
                # 如果没有找到，则使用第一个元素作为默认值
                self.target_element = list(self.relevantAreaList["elements"])[0]
        else:
            self.target_element = self.find_element_with_text_or_description(self.relevantAreaList)
            if not self.target_element:
                # 如果没有找到，则使用第一个元素作为默认值
                self.target_element = list(self.relevantAreaList)[0]
        
        return self.target_element

    def check_clickable(self, element_id):
        """检查元素（包含所有子元素）是否可点击"""
        return self._find_clickable_status(self.ui_layout_info_original, element_id)

    def _find_clickable_status(self, data, target):
        if isinstance(data, dict):
            # 检查当前层级的键
            for key, value in data.items():
                # 如果找到目标键，先检查其可点击状态
                if key == target:
                    is_clickable = value.get('isClickable', 0) == 1
                    # 如果不可点击且有children字段，检查children是否有可点击元素
                    if not is_clickable and 'children' in value and isinstance(value['children'], dict):
                        is_clickable, clickable_parent = self._check_children_clickable(value['children'], target)
                        if is_clickable:
                            return True, clickable_parent  # 返回父元素键名
                        return False, None
                    return is_clickable, None if not is_clickable else target
                
                # 递归检查所有字典类型的值
                if isinstance(value, dict):
                    result = self._find_clickable_status(value, target)
                    if result[0] is not None:
                        return result
        
            # 特别处理children字段
            if 'children' in data and isinstance(data['children'], dict):
                for child_key, child_value in data['children'].items():
                    # 检查子元素是否为目标
                    if child_key == target:
                        is_clickable = child_value.get('clickable', 0) == 1
                        # 如果不可点击且有children字段，检查children是否有可点击元素
                        if not is_clickable and 'children' in child_value and isinstance(child_value['children'], dict):
                            is_clickable, _ = self._check_children_clickable(child_value['children'], target)
                            if is_clickable:
                                return True, target  # 返回父元素键名
                            return False, None
                        return is_clickable, None if not is_clickable else target
                    
                    # 递归检查子元素
                    if isinstance(child_value, dict):
                        result = self._find_clickable_status(child_value, target)
                        if result[0] is not None:
                            return result
        return None, None

    def _check_children_clickable(self, children_dict, parent_key=None):
        """递归检查所有子元素是否可点击，返回是否可点击状态和直接父元素键名"""
        if not isinstance(children_dict, dict):
            return False, None
        
        for child_key, child_value in children_dict.items():
            # 检查当前子元素是否可点击
            if child_value.get('isClickable', child_value.get('clickable', 0)) == 1:
                return True, parent_key  # 返回可点击状态和直接父元素键名
            
            # 递归检查子元素的子元素
            if 'children' in child_value and isinstance(child_value['children'], dict):
                is_clickable, clickable_parent = self._check_children_clickable(child_value['children'], child_key)
                if is_clickable:
                    # 返回直接父元素键名，而不是当前层级的parent_key
                    return True, clickable_parent
        
        return False, None

    def optimize_element_clickable(self):
        """检查和优化目标元素的可点击状态"""
        # 处理target_element的不同格式
        if isinstance(self.target_element, list):
            # 对列表中的每个元素进行可点击性检查
            optimized_elements = []
            for element_id in self.target_element:
                is_clickable, clickable_key = self.check_clickable(element_id)
                if clickable_key and clickable_key != element_id:
                    optimized_elements.append(clickable_key)
                else:
                    optimized_elements.append(element_id)
            return optimized_elements
        elif isinstance(self.target_element, dict):
            # 对字典中的每个键进行可点击性检查
            optimized_dict = {}
            for element_id, element_data in self.target_element.items():
                is_clickable, clickable_key = self.check_clickable(element_id)
                if clickable_key and clickable_key != element_id:
                    optimized_dict[clickable_key] = element_data
                else:
                    optimized_dict[element_id] = element_data
            return optimized_dict
        else:
            # 单个元素（字符串格式）
            is_clickable, clickable_key = self.check_clickable(self.target_element)
            if clickable_key and clickable_key != self.target_element:
                return clickable_key  # 如果有可点击的子元素，则直接更新目标元素
            return self.target_element

    def get_element_json(self, data, target):
        """递归获取元素的完整JSON结构"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target:
                    return value
                if isinstance(value, dict):
                    result = self.get_element_json(value, target)
                    if result:
                        return result
                if key == 'children' and isinstance(value, dict):
                    result = self.get_element_json(value, target)
                    if result:
                        return result
        return None

    def extract_element_info(self):
        """提取目标元素的完整JSON信息"""
        # 处理target_element的不同格式
        target_elements_to_extract = []
        if isinstance(self.target_element, str):
            target_elements_to_extract = [self.target_element]
        elif isinstance(self.target_element, list):
            target_elements_to_extract = self.target_element
        elif isinstance(self.target_element, dict):
            target_elements_to_extract = list(self.target_element.keys())
        else:
            print('不支持的target_element格式: [omitted]')
            return

        # 初始化target_element_info字典
        self.target_element_info = {}
        
        # 为每个目标元素提取完整JSON结构
        for target_element in target_elements_to_extract:
            target_element_json = self.get_element_json(self.ui_layout_info_filtered, target_element)
            
            # 如果找到了元素，保存其信息
            if target_element_json:
                self.target_element_info[target_element] = target_element_json
                
                # 为了方便查看，创建一个简化版本用于打印
                display_info = {
                    'element_id': target_element,
                    'properties': target_element_json.copy()
                }
                
                # 如果有子元素，添加子元素数量信息
                if 'children' in target_element_json and isinstance(target_element_json['children'], dict):
                    display_info['children_count'] = len(target_element_json['children'])
                    
                print('目标元素信息 ([omitted]): [omitted]')
            else:
                self.target_element_info[target_element] = None
                print("未能找到元素 '[omitted]' 的完整JSON结构")
                
        print('完整的元素数据已保存到 self.target_element_info')

    def find_element_bounds(self, data, target):
        """在原始UI布局信息中递归查找对应元素的边界"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target:
                    return value.get('bounds', 'Bounds not found')
                if isinstance(value, dict):
                    result = self.find_element_bounds(value, target)
                    if result != 'Bounds not found':
                        return result
                if key == 'children' and isinstance(value, dict):
                    result = self.find_element_bounds(value, target)
                    if result != 'Bounds not found':
                        return result
        return 'Bounds not found'

    def visualize_ui_element(self):
        """在截图上可视化UI_topmost_json中activationStatus为1的所有元素，或者可视化relevantAreaList中的多个元素"""
        # 创建用于保存最终图像的对象
        from PIL import Image, ImageDraw
        img = None
        draw = None
        
        if self.screenshot_file and os.path.exists(self.screenshot_file):
            img = Image.open(self.screenshot_file)
            draw = ImageDraw.Draw(img)
        
        # 定义不同颜色列表，用于绘制不同的激活元素
        colors = ["green", "blue", "purple", "orange", "cyan", "magenta", "yellow", "lime", "pink", "brown"]
        
        # 收集所有需要绘制的元素
        elements_to_visualize = []
        
        # 优先检查UI_topmost_json是否存在
        if hasattr(self, 'UI_topmost_json') and self.UI_topmost_json:
            # 递归查找所有激活的元素（包括子元素）
            for element_id, element_info in self.UI_topmost_json.items():
                elements_to_visualize.extend(self._find_active_elements(element_id, element_info))
        # 如果没有UI_topmost_json，检查是否有多个relevantAreaList要可视化
        elif hasattr(self, 'relevantAreaList') and self.relevantAreaList and isinstance(self.relevantAreaList, list):
            elements_to_visualize = self.relevantAreaList
        # 最后回退到单个target_element
        elif hasattr(self, 'target_element') and self.target_element:
            # 处理target_element的不同格式
            if isinstance(self.target_element, str):
                elements_to_visualize = [self.target_element]
            elif isinstance(self.target_element, list):
                elements_to_visualize = self.target_element
            elif isinstance(self.target_element, dict):
                elements_to_visualize = list(self.target_element.keys())
            else:
                elements_to_visualize = []
            
        # 绘制所有需要可视化的元素
        color_idx = 0
        
        for element_id in elements_to_visualize:
            bounds = self.find_element_bounds(self.ui_layout_info_original, element_id)
            if bounds != 'Bounds not found' and img is not None:
                points = [
                    (bounds['left'], bounds['top']),      # 左上点
                    (bounds['right'], bounds['top']),     # 右上点
                    (bounds['left'], bounds['bottom']),   # 左下点
                    (bounds['right'], bounds['bottom'])   # 右下点
                ]
                
                # 为每个元素选择不同的颜色
                current_color = colors[color_idx % len(colors)]
                
                # 绘制不同颜色的矩形框表示不同的元素
                self._draw_rectangle(draw, points, current_color)
                
                # 更新颜色索引
                color_idx += 1
        
        # 保存并返回
        if img is not None:
            debug_img_path = self.screenshot_file.replace('.png', '_debug.png')
            img.save(debug_img_path)

    def _draw_rectangle(self, draw, points, color="red"):
        """在给定的ImageDraw对象上绘制矩形框"""
        if draw is not None:
            draw.line([points[0], points[1]], fill=color, width=3)  # 上边
            draw.line([points[0], points[2]], fill=color, width=3)  # 左边
            draw.line([points[1], points[3]], fill=color, width=3)  # 右边
            draw.line([points[2], points[3]], fill=color, width=3)  # 下边

    def _set_virtual_focus_recursive(self, node, target_element_ids):
        """Compatibility entry: return a validated copy; never mutate the capture."""
        return focus_candidate(node, target_element_ids)

    def update_and_send_virtual_focus(self):
        candidate = self._set_virtual_focus_recursive(
            self.ui_layout_info_original, self.target_element)
        require(self.ui_listener is not None, 'UI listener unavailable')
        self.ui_listener.reply({'type': 'UI_UPDATE', 'payload': candidate})
        self.guard.run(lambda: setattr(self, 'ui_layout_info_focused', candidate))


    def run(self):
        while True:
            if self.state == 'waiting':
                # 在实际应用中，这里应该是等待真实的消息
                # 现在我们使用模拟的消息进行测试
                if self.simulated_message == "normal":
                    self.receive_normal()
                elif self.simulated_message == "change":
                    self.receive_change()
                else:
                    print("未知消息类型")
                    break
            
            # 可以在这里添加退出条件
            # if some_exit_condition:
            #     break

            time.sleep(1)  # 避免过快循环

# ========== UIListener类定义 ========== #
class UIListener:
    def __init__(self, agent, adb_path=adb_path, *, acquire=None, send=None, policy=None, clock=time.monotonic):
        self.policy = policy or agent.policy
        agent.policy = self.policy
        self.clock = clock
        self._server = None
        self.acquire = get_screenshot_and_ui_elements if acquire is None else acquire
        self.send, self.adb_path, self.agent = send, adb_path, agent
        agent.ui_listener = self
        self.current_user_id, self.current_task_id = "User_12", "Task_3"
        self.client = None
        self._condition = threading.Condition(threading.RLock())
        self._execution_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._replies = deque()
        self._reply_worker = None
        self._audio_thread = None
        self._audio_leases = set()
        self._audio_pending = deque()
        self._connection = object()
        self._context = None
        self._ready_role_id = None
        self._active = None
        self._pending = None
        self._worker = None
        self._stopping = False
        self._base = None
        self._seen = set()
        self._state_task = None
        # Accepted user actions are facts, independent of cancellable model state.
        # The reader owns this task-scoped ledger; only the serial worker projects it.
        self._interaction_task = None
        self._accepted_interactions = []
        self._interaction_bytes = 0

    def _invalidate(self):
        if self._active is not None:
            self._active.cancel()
        if self._pending is not None:
            self._pending.cancel()
            self._pending.done.set()
        self._pending = None
        self._base = None

    def open_connection(self, client):
        with self._condition:
            self._invalidate()
            self._connection = client
            self.client = client
            self._context = None
            self._ready_role_id = None
            self._replies.clear()
            self._seen.clear()
            self._interaction_task = None
            self._accepted_interactions = []
            self._interaction_bytes = 0

    def close_connection(self, client):
        with self._condition:
            if self._connection is not client: return
            self._invalidate()
            self._context = None
            self._ready_role_id = None
            self._replies.clear()
            self._connection = object()
            self.client = None
        # Shutdown wakes both reader/select and a blocked sender without sharing
        # socket timeout mutations. Never close a replacement connection.
        try: client.shutdown(socket.SHUT_RDWR)
        except (AttributeError, OSError): pass
        try: client.close()
        except (AttributeError, OSError): pass

    def start_worker(self):
        with self._condition:
            if self._worker is None:
                self._worker = threading.Thread(target=self._worker_loop, name='focalflow-state', daemon=True)
                self._worker.start()
                self._reply_worker = threading.Thread(target=self._reply_loop, name='focalflow-replies', daemon=True)
                self._reply_worker.start()

    def stop_worker(self):
        client, server = self.client, self._server
        with self._condition:
            self._invalidate()
            self._stopping = True
            self._condition.notify_all()
        if client is not None: self.close_connection(client)
        if server is not None: server.close()
        for worker in (self._worker, self._reply_worker, self._audio_thread):
            if worker is not None:
                worker.join(2)

    def _start_audio_cleanup(self):
        # Called under the control condition; construction/import starts no threads.
        if self._audio_thread is None:
            self._audio_thread = threading.Thread(target=self._audio_cleanup_loop, name='focalflow-audio-cleanup', daemon=True)
            self._audio_thread.start()

    def _audio_cleanup_loop(self):
        while True:
            with self._condition:
                while not self._audio_pending and not self._stopping:
                    self._condition.wait()
                if not self._audio_pending:
                    return
                lease = self._audio_pending.popleft()
            # Native threading safety is platform-dependent: do not overlap
            # abort/close with worker start/read/write/stop, even after cancellation.
            lease.ready.wait()
            lease.finalized.wait()
            try:
                if lease.resource is not None and lease.start_attempted and (lease.work.cancelled.is_set() or lease.failed):
                    try:
                        lease.abort(lease.resource)
                    except Exception as error:
                        lease.error = type(error).__name__
                if lease.resource is not None:
                    lease.close(lease.resource)
                lease.closed = True
            except Exception as error:
                lease.error = type(error).__name__
            finally:
                with self._condition:
                    lease.work._release_lease(lease)
                    lease.completed.set()
                if lease.error is not None:
                    logging.warning('Owned audio cleanup failed: %s', lease.error)

    def _queue_rejection(self, connection, response):
        # Caller holds the control condition. Never writes to a socket here.
        if len(self._replies) >= 8:
            raise OSError('rejection output capacity exhausted')
        self._replies.append((connection, response))
        self._condition.notify_all()

    def _reply_loop(self):
        while True:
            with self._condition:
                while not self._replies and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                connection, response = self._replies.popleft()
                if connection is not self._connection or response['context'] != self._context:
                    continue
            try:
                self._send_to(connection, response)
            except (OSError, Cancelled, DeadlineExceeded):
                self.close_connection(connection)

    def expire_requests(self):
        with self._condition:
            # Admission budgets include the bounded pending slot as well as the
            # executing worker. A blocked provider must not hide pending expiry.
            for work in (self._active, self._pending):
                if work is None or work.done.is_set() or work.terminal_sent or (work.cancelled.is_set() and not work.expired): continue
                if not work.expired and self.clock() < work.deadline: continue
                work.expired = True
                work.cancel()
                if work is self._active: self._base = None
                if self._pending is work:
                    self._pending = None
                    work.done.set()
                if not work.error_sent and work.connection is self._connection and work.context == self._context:
                    work.error_sent = True
                    response = dict(protocolVersion=1, context=work.context, requestId=work.request_id,
                                    type='TALK_RESPONSE' if work.obj['type'] == 'REQUEST_TALK' else 'UI_UPDATE',
                                    error='DEADLINE_EXCEEDED', stage='request')
                    if self._worker is not None:
                        self._queue_rejection(work.connection, response)
                    else:
                        return work.connection, response

    def _worker_loop(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                work, self._pending = self._pending, None
                self._active = work
            self._execute(work)

    def _process_message(self, msg, connection=None):
        """Reader-side admission; a single bounded latest slot feeds the serial worker."""
        try:
            obj = bounded_json(msg, 65536)
            ctx, request_id = header(obj)
            rejection = None
            kind = obj.get('type')
            if kind == 'ROLE':
                with self._condition:
                    origin = self._connection if connection is None else connection
                    require(origin is self._connection, 'old connection')
                    role = identifier(obj.get('PID')), identifier(obj.get('TaskID'))
                    if self._context is not None:
                        require(ctx['sessionId'] == self._context['sessionId'] and ctx['taskEpoch'] > self._context['taskEpoch'], 'old task')
                    require(ctx['taskEpoch'] > 0 and ctx['snapshotSeq'] == 0, 'invalid task boundary')
                    self._invalidate()
                    self._context, self._seen = ctx, set()
                    self._interaction_task = (ctx['sessionId'], ctx['taskEpoch'])
                    self._accepted_interactions = []
                    self._interaction_bytes = 0
                    self.current_user_id, self.current_task_id = role
                    self._ready_role_id = request_id
                    self._condition.notify_all()
                    ready = dict(protocolVersion=1, context=dict(ctx), requestId=request_id, type='SESSION_READY')
                # Readiness is a control response, independent of business/model work.
                # The bounded writer rechecks socket/context/ROLE ownership before IO.
                try: self._send_to(origin, ready)
                except Cancelled: pass
                return
            with self._condition:
                origin = self._connection if connection is None else connection
                require(origin is self._connection, 'old connection')
                require(self._context is not None and ctx['sessionId'] == self._context['sessionId'] and ctx['taskEpoch'] == self._context['taskEpoch'], 'unknown task')
                if kind == 'INVALIDATE_CONTEXT':
                    require(ctx['snapshotSeq'] > self._context['snapshotSeq'], 'old snapshot')
                    self._invalidate()
                    self._context, self._seen = ctx, set()
                    self._condition.notify_all()
                    return
                require(kind in ('REQUEST_UI_UPDATE', 'REQUEST_TALK') and ctx == self._context and ctx['snapshotSeq'] > 0, 'unknown request context')
                require(request_id not in self._seen and len(self._seen) < 256, 'duplicate or excessive requests')
                self._seen.add(request_id)
                interaction_text, interaction_bytes = None, 0
                if kind == 'REQUEST_UI_UPDATE' and isinstance(obj.get('interaction'), dict):
                    value = obj['interaction'].get('text') or obj['interaction'].get('contentDescription')
                    if isinstance(value, str) and value:
                        interaction_text, interaction_bytes = value, len(value.encode('utf-8'))
                        if len(self._accepted_interactions) >= 256 or self._interaction_bytes + interaction_bytes > 65536:
                            rejection = dict(protocolVersion=1, context=ctx, requestId=request_id,
                                             type='UI_UPDATE', error='INTERACTION_HISTORY_LIMIT', stage='request')
                if rejection is None and kind == 'REQUEST_TALK' and (self._base != (ctx, obj.get('baseRequestId')) or self._pending is not None or (self._active is not None and not self._active.done.is_set() and not self._active.terminal_sent)):
                    rejection = dict(protocolVersion=1, context=ctx, requestId=request_id, type='TALK_RESPONSE', error='INVALID_BASE_OR_BUSY')
                if rejection is not None:
                    if self._worker is not None:
                        self._queue_rejection(origin, rejection)
                        return
                else:
                    if self._pending is not None:
                        self._pending.cancel()
                        self._pending.done.set()
                    if kind == 'REQUEST_UI_UPDATE':
                        self._base = None
                        if interaction_text is not None:
                            self._accepted_interactions.append(interaction_text)
                            self._interaction_bytes += interaction_bytes
                    work = Work(self, obj, origin, (self.current_user_id, self.current_task_id))
                    if self._worker is None:
                        self._active = work
                    if self._worker is not None:
                        self._pending = work
                        self._condition.notify_all()
                        return work
            if rejection is not None:
                # Synchronous embedding has no reader thread; still release the control
                # lock before invoking its output boundary.
                self._send_to(origin, rejection)
                return
            self._execute(work)
            return work
        except (ValidationError, UnicodeError):
            logging.warning('Protocol message rejected')

    def _check_ready_reply(self, connection, obj):
        if obj.get('type') != 'SESSION_READY': return
        with self._condition:
            if (connection is not self._connection or obj['context'] != self._context
                    or obj['requestId'] != self._ready_role_id):
                raise Cancelled('session readiness superseded')

    def _send_to(self, connection, obj, guard=None):
        self._check_ready_reply(connection, obj)
        if guard is not None: guard.check()
        message = json.dumps(obj, ensure_ascii=False, allow_nan=False)
        data = (message + '\n').encode('utf-8')
        if len(data) > MAX_MESSAGE_BYTES + 1: raise OperationError('transport', 'FRAME_LIMIT')
        timeout = self.policy.write if guard is None else min(self.policy.write, guard.remaining())
        deadline = self.clock() + timeout
        acquired = False
        offset = 0
        try:
            while not acquired:
                self._check_ready_reply(connection, obj)
                if guard is not None: guard.check()
                if self._stopping or self.clock() >= deadline: raise OSError('write deadline')
                acquired = self._send_lock.acquire(timeout=min(0.05, max(0.001, deadline - self.clock())))
            if self.send is not None:
                # Explicit embedding boundary; the real socket path below is bounded.
                self._check_ready_reply(connection, obj)
                if guard is not None: guard.check()
                self.send(message)
                if guard is not None:
                    with self._condition:
                        guard.terminal_sent = True
                return
            while offset < len(data):
                if guard is not None: guard.check()
                if self._stopping or connection is not self._connection or self.clock() >= deadline:
                    raise OSError('write deadline or closed connection')
                _, writable, _ = select.select([], [connection], [], min(0.05, max(0, deadline - self.clock())))
                if not writable: continue
                # The socket is permanently nonblocking. Only this immediate
                # write and terminal metadata share the admission/expiry lock;
                # select/backpressure and framing-lock waits remain outside it.
                with self._condition:
                    self._check_ready_reply(connection, obj)
                    if guard is not None: guard.check()
                    try: count = connection.send(data[offset:])
                    except BlockingIOError: continue
                    if count <= 0: raise OSError('closed during send')
                    offset += count
                    if offset == len(data) and guard is not None:
                        guard.terminal_sent = True
        except (OSError, ValueError, Cancelled, DeadlineExceeded) as error:
            # Once a frame has begun it must finish or the connection must close.
            # Never append another response onto an abandoned partial frame.
            obsolete_ready = isinstance(error, Cancelled) and obj.get('type') == 'SESSION_READY' and offset == 0
            if not obsolete_ready and (offset or not (guard is not None and guard.cancelled.is_set())):
                self.close_connection(connection)
            if isinstance(error, ValueError): raise OSError("closed socket") from None
            raise
        finally:
            if acquired: self._send_lock.release()

    def reply(self, obj):
        work = self.agent.guard
        require(work is not None, 'unregistered request')
        # State-machine callbacks prepare one terminal response. The serial worker
        # delivers it only after all state/audio work and the final guard check.
        work.run(lambda: setattr(work, 'response', dict(obj)))

    def _deliver_terminal(self, work):
        response = work.response
        if response is None:
            return
        response.update(protocolVersion=1, context=work.context, requestId=work.request_id)
        def commit():
            if 'payload' in response and work.obj['type'] == 'REQUEST_UI_UPDATE':
                self._base = (work.context, work.request_id)
        work.run(commit)
        self._send_to(work.connection, response, guard=work)
        # No fallible old-context operation follows a successfully delivered frame.

    def _execute(self, work):
        with self._execution_lock:
            self._execute_serial(work)

    def _execute_serial(self, work):
        checkpoint = None
        try:
            work.check()
            task = (work.context['sessionId'], work.context['taskEpoch'])
            if self._state_task != task:
                self.agent.reject_request({})
                self.agent.subtask_history, self.agent.action_history = [], []
                self.agent.subtask, self.agent.last_action = '', ''
                self.agent.target_element = None
                self.agent.ui_layout_info_original = None
                self.agent.ui_layout_info_focused = None
                self._state_task = task
            self.agent.guard = work
            with self._condition:
                work.check()
                if self._interaction_task == task:
                    self.agent.action_history = self._accepted_interactions[:]
            checkpoint = self.agent.request_checkpoint()
            self.agent.current_request_id = work.request_id
            if work.obj['type'] == 'REQUEST_UI_UPDATE':
                current = self.get_current_ui_state()
                work.check()
                self.update_agent_state(current)
                self.agent.receive_normal()
            else:
                self.agent.receive_change()
            work.check()
            self._deliver_terminal(work)
        except Exception as error:
            if checkpoint is not None:
                self.agent.reject_request(checkpoint)
            with self._condition:
                if self._active is work:
                    self._base = None
            if isinstance(error, DeadlineExceeded):
                try:
                    pending_error = self.expire_requests()
                    if pending_error is not None: self._send_to(*pending_error)
                except OSError:
                    self.close_connection(work.connection)
            elif not isinstance(error, Cancelled):
                logging.error('Request failed: %s', type(error).__name__)
                try:
                    response = {'type': 'TALK_RESPONSE' if work.obj['type'] == 'REQUEST_TALK' else 'UI_UPDATE', 'error': error.code if isinstance(error, OperationError) else type(error).__name__}
                    if isinstance(error, OperationError):
                        response['stage'] = error.stage
                        if error.status is not None: response['status'] = error.status
                    self.reply(response)
                    self._deliver_terminal(work)
                except (Cancelled, DeadlineExceeded):
                    pass
                except OSError:
                    # A failed error frame is a connection failure, not a fatal
                    # state-worker exception. Reconnect can use the same worker.
                    self.close_connection(work.connection)
        finally:
            self.agent.current_request_id = None
            self.agent.guard = None
            work.done.set()

    def read_connection(self, client):
        client.setblocking(False)  # One fixed policy, shared by reader and writer.
        self.open_connection(client)
        self.start_worker()
        buffer, frame_started = b'', None
        try:
            while not self._stopping and client is self._connection:
                self.expire_requests()
                if frame_started is not None and self.clock() - frame_started >= self.policy.frame:
                    raise OperationError('transport', 'FRAME_TIMEOUT')
                readable, _, _ = select.select([client], [], [], 0.05)
                if not readable: continue
                try: chunk = client.recv(4096)
                except BlockingIOError: continue
                if not chunk:
                    if buffer: raise OperationError('transport', 'TRUNCATED_FRAME')
                    break
                if frame_started is None: frame_started = self.clock()
                if self.clock() - frame_started >= self.policy.frame:
                    raise OperationError('transport', 'FRAME_TIMEOUT')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    require(len(line) <= 65536, 'wire size limit')
                    if line.strip(): self._process_message(line.decode('utf-8'), client)
                    frame_started = self.clock() if buffer else None
                require(len(buffer) <= 65536, 'wire size limit')
        except (OSError, ValueError, UnicodeError, OperationError) as error:
            logging.warning('Connection rejected: %s', type(error).__name__)
        finally:
            self.close_connection(client)
            client.close()

    def run_server(self, port=9998):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self._server = server
            server.bind(('localhost', port))
            server.listen(1)
            server.setblocking(False)
            try:
                while not self._stopping:
                    try:
                        readable, _, _ = select.select([server], [], [], 0.05)
                        if readable:
                            client, _ = server.accept()
                            self.read_connection(client)
                    except (OSError, ValueError):
                        if not self._stopping: raise
            finally:
                self._server = None
                self.stop_worker()

    def get_current_ui_state(self):
        """
        获取当前Android端的UI状态
        复用项目中已有的get_screenshot_and_ui_elements函数
        """
        logging.info("开始获取当前UI状态...")
        
        try:
            # 更新时间戳作为截图编号
            screenshot_counter = int(time.strftime("%m%d%H%M%S", time.localtime()))
            
            print('获取UI状态，使用截图编号: [omitted]')
            logging.info('当前用户ID: [omitted], 任务ID: [omitted]')
            
            # 复用已有的获取截图和UI元素的函数
            logging.info("调用get_screenshot_and_ui_elements函数...")
            screenshot_file, ui_layout_path = self.acquire(
                self.adb_path, self.current_user_id, self.current_task_id, screenshot_counter,
                expected_context=self.agent.guard.context, policy=self.policy, guard=self.agent.guard
            )
            
            if screenshot_file is None or ui_layout_path is None:
                error_msg = f"获取截图或UI元素失败。截图: {screenshot_file}, UI布局: {ui_layout_path}"
                logging.error('[omitted]')
                raise Exception(error_msg)
            
            logging.info('成功获取文件路径 - 截图: [omitted], UI布局: [omitted]')
            
            # 读取UI布局信息
            logging.info("读取UI布局文件...")
            ui_layout_data = read_snapshot(ui_layout_path, self.agent.guard.context)
            
            logging.info('UI布局数据读取完成，包含 [omitted] 个顶级元素')
            print('成功获取UI状态 - 截图: [omitted], UI布局文件: [omitted]')
            
            ui_state = {
                'screenshot_file': screenshot_file,
                'ui_layout': ui_layout_data,
                'ui_layout_path': ui_layout_path,
                'timestamp': screenshot_counter
            }
            
            logging.info("UI状态获取完成")
            return ui_state
            
        except Exception as e:
            logging.error('获取当前UI状态失败: %s', type(e).__name__)
            logging.error('获取当前UI状态失败: %s', type(e).__name__)
            raise

    def update_agent_state(self, current_ui_state):
        """
        更新agent的状态信息
        统一处理UI状态更新的逻辑
        """
        if current_ui_state and 'screenshot_file' in current_ui_state:
            tree_index(current_ui_state['ui_layout'])
            # 更新agent基本状态信息
            self.agent.screenshot_file = current_ui_state['screenshot_file']
            self.agent.ui_layout_info_original = current_ui_state['ui_layout']
            self.agent.ui_layout_info_original_path = current_ui_state['ui_layout_path']
            self.agent.screenshot_cnt = current_ui_state['timestamp']
            
            # 过滤UI布局信息
            self.agent.ui_layout_info_filtered = filter_json_elements(current_ui_state['ui_layout'])
            
            print('已更新agent状态 - 截图计数: [omitted]')

    def process_ui_state(self, current_ui_state):
        self.update_agent_state(current_ui_state)
        return focus_candidate(self.agent.ui_layout_info_original, self.agent.target_element)

    def ensure_adb_reverse(self, port=9998):
        result = adb_run([self.adb_path, 'reverse', '--list'], self.policy)
        if 'tcp:%d tcp:%d' % (port, port) not in result.stdout:
            adb_run([self.adb_path, 'reverse', 'tcp:%d' % port, 'tcp:%d' % port], self.policy)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_runtime_setting("API_url")
    load_runtime_setting("token")
    mobile_agent = MobileAgentStateMachine()
    # 启动UI监听器
    ui_listener = UIListener(mobile_agent, adb_path)
    ui_listener.ensure_adb_reverse(9998)
    # 启动socket监听（阻塞式）
    ui_listener.run_server()
