import copy
from MobileAgent.api import encode_image


def init_subtask_chat():
    operation_history = []
    sysetm_prompt = "You are an AI assistant specializing in UI automation for mobile. You need to help me analyze the screen and generate subtasks for completing the user\'s instruction."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history

def init_decision_chat():
    operation_history = []
    sysetm_prompt = "You are an AI assistant specializing in UI automation for mobile. Your task is to analyze the phone screenshots and the corresponding UI structure information to precisely identify one or more UI elements that the next action should focus on, based on the user's instructions and the current subtask."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history

def init_classify_chat():
    operation_history = []
    sysetm_prompt = "You are a helpful AI mobile phone operating assistant. You need to help me figure out what UI elements are most relevant to the task right now."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history

def init_talk_chat():
    operation_history = []
    sysetm_prompt = "You are a helpful AI mobile phone operating assistant. You need to help me tweak the currently displayed UI elements according to the user's requirements."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history

# def init_talk_chat():
#     operation_history = []
#     sysetm_prompt = "You are a helpful AI mobile phone operating assistant. Your goal is to analyze the current screen of the mobile device, identify and classify all UI elements into functional categories, and provide accurate feedback addressing the user\’s questions or doubts about the screen."
#     operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
#     return operation_history

def init_reflect_chat():
    operation_history = []
    sysetm_prompt = "You are a helpful AI mobile phone operating assistant."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history


def init_memory_chat():
    operation_history = []
    sysetm_prompt = "You are a helpful AI mobile phone operating assistant."
    operation_history.append(["system", [{"type": "text", "text": sysetm_prompt}]])
    return operation_history


def add_response(role, prompt, chat_history, image=None):
    new_chat_history = copy.deepcopy(chat_history)
    if image:
        base64_image = encode_image(image)
        content = [
            {
                "type": "text", 
                "text": prompt
            },
            {
                "type": "image_url", 
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            },
        ]
    else:
        content = [
            {
            "type": "text", 
            "text": prompt
            },
        ]
    new_chat_history.append([role, content])
    return new_chat_history


def add_response_two_image(role, prompt, chat_history, image):
    new_chat_history = copy.deepcopy(chat_history)

    base64_image1 = encode_image(image[0])
    base64_image2 = encode_image(image[1])
    content = [
        {
            "type": "text", 
            "text": prompt
        },
        {
            "type": "image_url", 
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image1}"
            }
        },
        {
            "type": "image_url", 
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image2}"
            }
        },
    ]

    new_chat_history.append([role, content])
    return new_chat_history


def print_status(chat_history):
    print('[omitted]')
    for chat in chat_history:
        print('role:[omitted]')
        print('[omitted]')
    print('[omitted]')
