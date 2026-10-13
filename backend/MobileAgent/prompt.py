def get_subtask_prompt(instruction, clickable_infos, subtask_history, action_history, last_summary, last_action, add_info, error_flag, completed_content, memory):
    prompt = "## 1. Task Background and Context\n"
    prompt += f"- **User's Ultimate Goal**: {instruction}\n"
    if len(subtask_history) > 0:
        prompt += "- **Historical Context**: To understand the current state, review the sequence of previously completed subtasks. The next subtask must be a logical continuation of this history.\n"
        for i, summary in enumerate(subtask_history):
            prompt += f"    - Step-{i+1}: {summary.split(' to ')[0].strip()}\n"
    prompt += "\n"

    prompt += "## 2. Input Information\n"
    prompt += "You are provided with the following information to analyze the current screen:\n\n"
    prompt += "### UI Element Data (Ground Truth)\n"
    prompt += "This is the definitive, structured data of all interactable UI elements on the current screen. Treat this information as the **single source of truth**. Each element has four key attributes:\n"
    prompt += "- **name**: The resource ID or unique identifier of the node.\n"
    prompt += "- **text**: The text content displayed on the UI element.\n"
    prompt += "- **contentDescription**: The accessibility text description of the UI element.\n"
    prompt += "- **children**: The direct child nodes of the element, reflecting the UI's hierarchical relationship.\n"
    prompt += f"```json\n{clickable_infos}\n```\n\n"

    if add_info:
        prompt += f"### Additional Tips\n"
        prompt += f"{add_info}\n\n"

    prompt += "## 3. Your Core Task and Guidelines\n"
    prompt += "Your core task is to analyze all the provided information and define the **next subtask** required to achieve the user's ultimate goal. When defining this subtask, you **MUST** strictly adhere to the following guidelines:\n\n"

    prompt += "1.  **Focus on Intent, Not Operation (Most Important)**: The subtask description **MUST** be a general user **intent**. It must describe what the user \"**wants to do**\" at a high level, not the specific UI operation they will perform. \n"
    prompt += "    - **Correct Examples**: `Select a store`, `Enter the checkout page`, `Search for a specific product`.\n"
    prompt += "    - **Incorrect Examples**: `Click the \"KFC\" button`, `Click the shopping cart icon`, `Type \"hamburger\" in the search box`.\n\n"

    prompt += "2.  **Single Intent Principle**: Each subtask should contain only one core user intent. **DO NOT** combine multiple distinct intents into a single subtask.\n"
    prompt += "    - **Correct Example**: `Select a car model`. (The next task might be `Call a vehicle`.)\n"
    prompt += "    - **Incorrect Example**: `Select a car model and then call a vehicle`.\n\n"

    prompt += "3.  **Follow History, Step-by-Step**: The new subtask **MUST** be a logical continuation of the historical steps. Skipping necessary steps is not allowed. If a required precursor action (e.g., `Select a city`) is not in the history, your next subtask **MUST** be `Select a city`, even if the screen appears to have a city pre-selected. If you have already completed a step before, do not repeat a step. e.g. if you have already chosen a hospital before, do not choose a hospital again.\n\n"
    
    prompt += "4.  **Handle Multiple Valid Paths (OR Condition)**: If the current screen offers several different but equally logical paths to advance the user's goal, you **MUST** identify these parallel possibilities. Frame the subtask as a choice using '或' (OR).\n"
    prompt += "    - **Correct Example**: `选择一个美食分类 或 选择一家特定的餐厅` (Select a food category OR select a specific restaurant).\n"
    prompt += "    - **Incorrect Example**: `选择美食分类和餐厅` (Select food category and restaurant).\n\n"


    prompt += "## 4. Output Format\n"
    prompt += "Your output **MUST** strictly include the following three sections in Chinese. **DO NOT** add any extra comments or explanations outside of these sections.\n\n"

    prompt += "### Thought ###\n"
    prompt += "Please provide a detailed analysis of your decision-making process in Chinese. Combine the user's goal, screen information, and historical context to deduce the next logical subtask. If there are multiple valid paths, explain why each is a reasonable choice and how they relate to the overall goal. Explain how your deduction conforms to the guidelines.\n\n"

    prompt += "### Subtask ###\n"
    prompt += "Based on your analysis, provide a brief, intent-focused description of the next subtask in Chinese. If multiple valid paths exist, present them as a choice using '或'.\n\n"

    prompt += "### Screen ###\n"
    prompt += "Provide a single, concise sentence in Chinese describing the main purpose of the current screen. **DO NOT** mention specific UI elements, layouts, or operations.\n\n"

    prompt += "**Example of Expected Output:**\n"
    prompt += "*(Scenario: User wants to order a hamburger. The screen shows both cuisine categories and a list of restaurants.)*\n\n"
    prompt += "### Thought ###\n"
    prompt += "用户的最终目标是“点一个汉堡”。当前屏幕是应用首页，没有历史记录。屏幕上既提供了“汉堡薯条”、“美食”等分类入口，也直接展示了“肯德基”、“麦当劳”等具体的商家列表。为了完成用户的目标，下一步合理的意图可以是先从分类入手，点击“汉堡薯条”分类来筛选商家；同样合理的意图也可以是直接在屏幕上显示的商家中选择一个看起来可能卖汉堡的，比如“肯德基”。这两个都是达成目标的有效路径，且互不依赖。因此，下一个子任务应该是这两个并列选项的或关系，这符合“处理多个有效路径”的准则。这个定义也遵循了“意图优先”的原则，描述的是“做什么”而不是“点哪里”。\n\n"
    prompt += "### Subtask ###\n"
    prompt += "选择一个美食分类 或 选择一家特定的餐厅\n\n"
    prompt += "### Screen ###\n"
    prompt += "这是一个包含美食分类和推荐餐厅的点餐应用主界面。\n"

    return prompt
def get_talk_prompt(instruction, category_items_json):
    # 函数签名已更改，以反映新的输入参数
    
    prompt = "### Background\n"
    prompt += f"I will give you the user's instruction and a JSON object called 'categoryItems' which contains all relevant UI elements, grouped by category. Your task is to identify which category the user is asking about.\nThe user's instruction is: {instruction}.\n\n"
    
    # --- MODIFICATION 1: Reworked the entire data description section ---
    prompt += "### UI Categories and Items (categoryItems)\n"
    prompt += "The UI information is provided in a `categoryItems` JSON object. Its structure is as follows:\n"
    prompt += "- The top-level keys are human-readable category names (e.g., \"餐厅名称\", \"评分\", \"月售\"). **These are the exact category names you need to identify and output.**\n"
    prompt += "- The value for each category is a dictionary. Inside this dictionary, keys are element IDs, and values contain the element's display text.\n\n"
    prompt += "Here is the `categoryItems` information for the current screen:\n"
    prompt += f"{category_items_json}\n\n"
    
    prompt += "### Your Task\n"
    prompt += "1. Analyze the user's instruction.\n"
    prompt += "2. Decide if the user wants to go back (Mode A) or get information about a category (Mode B).\n"
    prompt += "3. If Mode B, determine which category name from the `categoryItems` keys the user is referring to.\n\n"

    prompt += "### Mode Choosing ###\n"
    prompt += "Analyze the user's intent to choose a mode.\n"
    prompt += "A: The user wants to go back to the previous step.\n"
    prompt += "B: The user wants to know more information about one or more UI categories shown on the screen.\n\n"

    # --- MODIFICATION 2: Simplified and clarified the choosing instruction ---
    prompt += "### Displayed UI Choosing ###\n"
    prompt += "If you chose 'B', which UI category is the user asking about? Your answer must be one of the top-level keys from the `categoryItems` JSON provided above.\n\n"

    prompt += "### Output format \n"
    prompt += "Your output consists of the following 2 parts:\n"
    prompt += "### Thought ###\nBased on the requirements and information above, think about the behavior you gonna do. Output in Chinese.\n"
    prompt += "### Mode ###\nA or B\n"
    
    # --- MODIFICATION 3: Made the output instruction extremely specific ---
    prompt += "### Displayed UI ###\n"
    prompt += "If Mode is B, output the name of the category (or categories, comma-separated) that the user is interested in. This name MUST exactly match one of the top-level keys in the `categoryItems` JSON. If Mode is A, leave this section empty.\n"
    
    return prompt

def get_classify_prompt(instruction, current_subtask, element_json, add_info):
    prompt = ""
    # 1. Task Background & Context
    prompt += "## Task Background & Context\n"
    prompt += f"- **User's Ultimate Goal**: {instruction}\n"
    prompt += "\n"

    # 2. Input Information
    prompt += "## Input Information\n"
    prompt += "You will receive two main types of information to understand the current screen:\n\n"
    
    prompt += "### 1. UI Element Data (Ground Truth)\n"
    prompt += "The `element_json` data you receive is a **filtered collection of task-relevant 'cards,' not all elements on the entire screen**. Each independent JSON object within this data represents a distinct card or list item.\n"
    prompt += "Please consider this information the **sole source of truth** regarding 'what elements are inside these cards, what their properties are, and what text they contain.' Each UI element includes the following properties:\n"
    prompt += "    - `name`: A unique name for the UI element, used as an identifier in the output.\n"
    prompt += "    - `text`: The text displayed on the element.\n"
    prompt += "    - `contentDescription`: The accessibility text description for the element.\n"
    prompt += "    - `children`: A list of direct child elements, reflecting the UI's hierarchical structure.\n"
    prompt += "    - `isCheckable`: A boolean value indicating whether the element can be checked or clicked.\n"
    prompt += f"```json\n{element_json}\n```\n"
    
    prompt += "### 2. Screenshot (Visual Context)\n"
    prompt += "A screenshot of the current page is provided along with the data. Its purpose is to offer **visual context** for the JSON data, showing how these cards are arranged and designed on the screen. Specifically, use the screenshot to understand:\n"
    prompt += "- **Spatial Layout and Grouping**: Crucially, use the screenshot to identify visually distinct groupings, such as cards, list items, or dialogs, and to understand the layout relationships of elements within each card.\n\n"
    
    prompt += f"### 3. Current Subtask\n"
    prompt += f"Your immediate goal is to complete: **{current_subtask}**\n\n"

    # 3. Core Task and Analysis Criteria
    prompt += "## Your Task and Analysis Criteria\n"
    prompt += "You need to accomplish two main tasks: first, categorize all provided elements based on their content. Second, based on the categorization and subtask, select the best action point for each card.\n"
    prompt += "When analyzing, you must strictly adhere to the following criteria:\n"
    prompt += "1.  **Semantic Categorization**: Analyze all input elements and assign them to different categories based on their **content and meaning** (e.g., `地址`, `评分`, `用户名`, `价格`). Use **Chinese** for category names.\n"
    prompt += "2.  **Process Every Card**: Your selection task must cover **every** card object in the input data.\n"
    prompt += "3.  **Find the Best Action Point**: Within **each card**, find the most relevant element for the subtask. This selection **must be clickable** (`isCheckable: true`).\n"
    prompt += "4.  **Handle Non-Clickable Targets**: If the most relevant element (e.g., a specific text label) is **not clickable**, you must find and select its **smallest, directly clickable parent element**.\n"
    prompt += "5.  **Select the Most Specific Element**: If multiple nested elements within a card are relevant and clickable, you must choose the **most functionally specific, smallest unit**. For example, choose an `ActionButton` instead of the entire `ListItem` that contains it.\n"
    prompt += "6.  **One-to-One Correspondence**: The final list of selected action points should correspond one-to-one with the input set of cards.\n"
    prompt += "7.  **Ensure Action Context**: If the selected action point (`action_point`) is generic or lacks descriptive text (e.g., a button simply labeled 'Select' or an icon), you **must** include other key text elements from the same card in the `context_elements` field to clarify the action's target.\n"
    prompt += "\n"
    
    if add_info:
        prompt += f"8.  **Additional Tip**: {add_info}\n"

    # 4. Output Format Requirements
    prompt += "## Output Format Requirements\n"
    prompt += "Your output must strictly include the following three sections and adhere to the format requirements:\n\n"
    prompt += "### Thought ###\n"
    prompt += "Please provide your decision-making analysis process in **Chinese**. First, explain how you defined the semantic categories and classified all elements based on their content. Then, for each input card, explain how you selected the most appropriate clickable element and, crucially, why you decided to include (or not include) context elements based on the new rules.\n\n"
    prompt += "### Categories ###\n"
    prompt += "Output a complete JSON object mapping each **Chinese category name** to its elements. Each element's exact input identifier must be the key, and its value must contain only the `text` field: {\"Chinese category\": {\"exact_input_element_id\": {\"text\": \"element text\"}}}. Copy identifiers exactly from the input; never shorten, reconstruct, or invent them. Do not repeat a `name` field inside Categories entries. The `name` field remains required for context objects in SelectedUI below.\n\n"
    prompt += "### SelectedUI ###\n"
    prompt += "Output a **list of JSON objects**. Each object corresponds to one card and must contain two keys:\n"
    prompt += "1.  `action_point`: The `name` (string) of the single, most relevant and clickable element you selected for the action.\n"
    prompt += "2.  `context_elements`: A **list of objects**, where each object represents a contextual UI element and contains its `name` (string) and `text` (string). This list is used to provide essential context when the `action_point` itself is not descriptive. If the `action_point` is sufficiently descriptive, this list can be empty `[]`.\n"

    prompt += "\n**Example 1: Basic Selection with Context**\n"
    prompt += "Assume the subtask is 'view the details for each restaurant'.\n"
    prompt += "### Thought ###\n"
    prompt += "第一步，我识别出“餐厅名称”、“评分”和“卡片容器”等类别。第二步，我遍历所有卡片以完成“查看详情”任务。对于第一家餐厅'Gourmet Garden Bistro'，整个卡片`restaurant_card_1`都是可点击的，并且是完成任务的最佳点击目标。为了明确这个动作是针对哪个餐厅，我将'Gourmet Garden Bistro'的名称元素`name_1`作为上下文信息加入。对第二家餐厅'Ocean's Catch Seafood'执行相同操作，选择可点击的卡片`restaurant_card_2`作为动作点，并加入其名称`name_2`作为上下文。\n"
    prompt += "### Categories ###\n"
    prompt += "```json\n"
    prompt += '''{
    "餐厅名称": {
      "name_1": {"text": "Gourmet Garden Bistro"},
      "name_2": {"text": "Ocean's Catch Seafood"}
    },
    "评分": {
      "rating_1": {"text": "4.5 stars"},
      "rating_2": {"text": "4.8 stars"}
    },
    "卡片容器": {
      "restaurant_card_1": {"text": ""},
      "restaurant_card_2": {"text": ""}
    }
}
'''
    prompt += "```\n"
    prompt += "### SelectedUI ###\n"
    prompt += "```json\n"
    prompt += '''[
  {
    "action_point": "restaurant_card_1",
    "context_elements": [
      {
        "name": "name_1",
        "text": "Gourmet Garden Bistro"
      }
    ]
  },
  {
    "action_point": "restaurant_card_2",
    "context_elements": [
      {
        "name": "name_2",
        "text": "Ocean's Catch Seafood"
      }
    ]
  }
]
'''
    prompt += "```\n"

    prompt += "\n**Example 2: Handling Non-Clickable Target**\n"
    prompt += "Assume the subtask is 'click on the user profile for Jane Doe'.\n"
    prompt += "### Thought ###\n"
    prompt += "第一步，我根据元素内容识别出“用户卡片”和“用户名”两个类别。子任务要求点击'Jane Doe'的个人资料。我定位到了包含文本'Jane Doe'的元素“user_name_jane”，但它不可点击。根据规则，我需要寻找它最小的可点击父节点，即“profile_container_jane”。因此，我选择“profile_container_jane”作为`action_point`。由于动作点本身没有描述性文本，为了明确点击的是谁的个人资料，我必须将原始目标“user_name_jane”作为`context_elements`加入。\n"
    prompt += "### Categories ###\n"
    prompt += "```json\n"
    prompt += '''{
    "用户卡片": {
      "profile_container_jane": {"text": ""}
    },
    "用户名": {
      "user_name_jane": {"text": "Jane Doe"}
    }
}
'''
    prompt += "```\n"
    prompt += "### SelectedUI ###\n"
    prompt += "```json\n"
    prompt += '''[
  {
    "action_point": "profile_container_jane",
    "context_elements": [
      {
        "name": "user_name_jane",
        "text": "Jane Doe"
      }
    ]
  }
]
'''
    prompt += "```\n"

    prompt += "\n**Example 3: Handling Generic Button with Context**\n"
    prompt += "Assume the subtask is 'select the product named Super Blender'.\n"
    prompt += "### Thought ###\n"
    prompt += "第一步，我识别出“商品名称”和“选择按钮”两个类别。子任务是选择'Super Blender'。我发现每个商品卡片都有一个文本为'Select'的按钮。对于包含'Super Blender'的卡片，最适合的点击目标是`select_button_1`。然而，这个按钮的文本'Select'是通用的，无法区分它具体选择的是哪个商品。根据规则7（确保动作上下文），我必须提供额外信息。因此，我将`action_point`设为`select_button_1`，并把能明确标识商品的元素`product_name_1`（文本为'Super Blender'）作为`context_elements`添加进去。\n"
    prompt += "### Categories ###\n"
    prompt += "```json\n"
    prompt += '''{
    "商品名称": {
      "product_name_1": {"text": "Super Blender"},
      "product_name_2": {"text": "Mega Juicer"}
    },
    "选择按钮": {
      "select_button_1": {"text": "Select"},
      "select_button_2": {"text": "Select"}
    }
}
'''
    prompt += "```\n"
    prompt += "### SelectedUI ###\n"
    prompt += "```json\n"
    prompt += '''[
  {
    "action_point": "select_button_1",
    "context_elements": [
      {
        "name": "product_name_1",
        "text": "Super Blender"
      }
    ]
  }
]
'''
    prompt += "```\n"

    return prompt

def get_decision_prompt(instruction, clickable_infos, summary_history, action_history, last_summary, last_action, add_info, error_flag, completed_content, memory, current_subtask):
    prompt = ""
    # 1. Task Background and Context
    prompt += "## Task Background and Context\n"
    prompt += f"- **User's Ultimate Goal**: {instruction}\n"
    if memory:
        prompt += f"- **Historical Memory**: In previous operations, you recorded the following important information: {memory}\n"
    prompt += "\n"

    # 2. Input Information
    prompt += "## Input Information\n"
    prompt += "You are provided with two primary sources of information to understand the current screen:\n\n"
    
    prompt += "### 1. UI Element Data (Ground Truth)\n"
    prompt += "This is the definitive, structured data of all interactable UI elements on the screen. Treat this information as the **single source of truth** for what elements exist and what text they contain. Each element contains four properties:\n"
    prompt += "    - `name`: The resource ID or unique identifier of the node.\n"
    prompt += "    - `text`: The text displayed on the element.\n"
    prompt += "    - `contentDescription`: The accessibility text description of the element.\n"
    prompt += "    - `children`: A list of direct child elements, reflecting the UI's hierarchical relationship.\n"
    prompt += f"```json\n{clickable_infos}\n```\n"
    
    prompt += "### 2. Screenshot (Visual Context)\n"
    prompt += "A screenshot of the current page is provided alongside this data. Its purpose is to provide **visual context** for how the elements in the JSON are arranged and styled. Use the image to understand:\n"
    prompt += "- **Spatial Layout and Grouping**: Crucially, use the screenshot to identify visually distinct groups, such as cards, list items, or dialog boxes.\n\n"
    
    prompt += f"### 3. Current Subtask\n"
    prompt += f"Your immediate objective is: **{current_subtask}**\n\n"

    if add_info:
        prompt += f"4.  **Additional Tip**: {add_info}\n"
    prompt += "\n"
    
    # 3. Core Task and Analysis Criteria
    prompt += "## Your Task and Analysis Criteria\n"
    prompt += "Your core task is: **Using the Visual Context from the screenshot, identify the self-contained 'card' or 'list item' that is most relevant to the 'Current Subtask'. Then, output the unique `name` of the minimal container element that acts as the root for that entire card.**\n"
    prompt += "When analyzing, you must strictly adhere to the following criteria:\n"
    prompt += "1.  **Visually Identify the Card First**: Your primary analysis should start with the screenshot. Look for visual containers (cards, rows, panels) that hold information related to the subtask.\n"
    prompt += "2.  **Map Visuals to Ground Truth**: Once you identify a relevant visual card, locate its corresponding parent element in the **UI Element Data (JSON)**. The text *within* the card that makes it relevant must be present in the JSON data of that element or its children.\n"
    prompt += "3.  **Output the Card's Root Element (Minimal Enclosing Container)**: This is a critical rule. You must select the element that serves as the root for a single visual card. Think of it as the **smallest possible container** whose descendants (children, grandchildren, etc.) include **all** the text and UI elements for that one card, and nothing more.\n"
    prompt += "    -   **DO NOT** select a high-level container that groups multiple cards together (e.g., the entire list).\n"
    prompt += "    -   **DO NOT** select a specific element *inside* the card (e.g., just the title text or a button).\n"
    prompt += "    -   You **MUST** select the parent element that perfectly encapsulates one single, self-contained card.\n"
    prompt += "4.  **Comprehensive Selection**: If multiple distinct cards on the screen appear equally relevant to the subtask, you must select and output the root element `name` for **every** one of them.\n"
    prompt += "\n"

    # 5. Output Format Requirements
    prompt += "## Output Format\n"
    prompt += "Your output must include the following two sections, strictly adhering to the format requirements:\n\n"
    prompt += "### Thought ###\n"
    prompt += "Please provide a detailed analysis of your decision-making process in Chinese. Clearly explain how you used the visual information from the screenshot to identify a relevant 'card'. Then, describe how you found the corresponding root element in the JSON and why it's the correct minimal container for that card, and why its contents are relevant to the 'Current Subtask'.\n\n"
    prompt += "### Output ###\n"
    prompt += "Based on your analysis, output the filtered UI element names as a **JSON array (a list of strings)**.\n"
    prompt += "- The list should contain the `name` (unique ID) of each selected card's root element.\n"
    prompt += "\n**Example:**\n"
    prompt += "### Thought ###\n"
    prompt += "在用户的当前子任务“选择一家提供汉堡的餐厅”中，我们需要在屏幕截图中找到与“汉堡”相关的餐厅卡片。通过查看截图，我们可以看到几个餐厅的卡片，其中“肯德基宅急送（东涌店）”和“塔斯汀·中国汉堡（南沙东兴二路店）”都与汉堡相关。肯德基是一个知名的快餐品牌，提供汉堡，而塔斯汀·中国汉堡的名字中直接包含“汉堡”字样。\n"
    prompt += "\n"
    prompt += "接下来，我们需要在提供的UI元素数据中找到这些餐厅卡片的根元素，即刚好包裹住每张卡片所有信息的最小容器。通过匹配截图中的文本信息和JSON数据中的文本字段，我们可以确认以下两个元素是我们需要的：\n"
    prompt += "\n"
    prompt += "1. **肯德基宅急送（东涌店）**：在JSON数据中，`element_19a40dabf2524d7cb73c13a970bd6180`是这张卡片的根元素，它的子孙节点包含了店名、评分、销量等全部信息。\n"
    prompt += "2. **塔斯汀·中国汉堡（南沙东兴二路店）**：在JSON数据中，`element_c8139b6e625747789718ad9f3d38448e`是这张卡片的根元素，它同样完整地包含了该餐厅卡片的所有内容。\n"
    prompt += "\n"
    prompt += "### Output ###\n"
    prompt += "```json\n"
    prompt += "[\n"
    prompt += "  \"element_19a40dabf2524d7cb73c13a970bd6180\",\n"
    prompt += "  \"element_c8139b6e625747789718ad9f3d38448e\"\n"
    prompt += "]\n"
    prompt += "```\n"
    
    return prompt

def get_action_prompt(instruction, clickable_infos, width, height, keyboard, summary_history, action_history, last_summary, last_action, add_info, error_flag, completed_content, memory):
    prompt = "### Background ###\n"
    prompt += f"This image is a phone screenshot. Its width is {width} pixels and its height is {height} pixels. The user\'s instruction is: {instruction}.\n\n"
    
    prompt += "### Screenshot information ###\n"
    prompt += "In order to help you better perceive the content in this screenshot, we extract some information on the current screenshot through system files. "
    prompt += "This information consists of two parts: coordinates; content. "
    prompt += "The format of the coordinates is [x, y], x is the pixel from left to right and y is the pixel from top to bottom; the content is a text or an icon description respectively. "
    prompt += "The information is as follow:\n"

    for clickable_info in clickable_infos:
        if clickable_info['text'] != "" and clickable_info['text'] != "icon: None" and clickable_info['coordinates'] != (0, 0):
            prompt += f"{clickable_info['coordinates']}; {clickable_info['text']}\n"
    
    prompt += "Please note that this information is not necessarily accurate. You need to combine the screenshot to understand."
    prompt += "\n\n"
    
    prompt += "### Keyboard status ###\n"
    prompt += "We extract the keyboard status of the current screenshot and it is whether the keyboard of the current screenshot is activated.\n"
    prompt += "The keyboard status is as follow:\n"
    if keyboard:
        prompt += "The keyboard has been activated and you can type."
    else:
        prompt += "The keyboard has not been activated and you can\'t type."
    prompt += "\n\n"
    
    if add_info != "":
        prompt += "### Hint ###\n"
        prompt += "There are hints to help you complete the user\'s instructions. The hints are as follow:\n"
        prompt += add_info
        prompt += "\n\n"
    
    if len(action_history) > 0:
        prompt += "### History operations ###\n"
        prompt += "Before reaching this page, some operations have been completed. You need to refer to the completed operations to decide the next operation. These operations are as follow:\n"
        for i in range(len(action_history)):
            prompt += f"Step-{i+1}: [Operation: " + summary_history[i].split(" to ")[0].strip() + "; Action: " + action_history[i] + "]\n"
        prompt += "\n"
    
    if completed_content != "":
        prompt += "### Progress ###\n"
        prompt += "After completing the history operations, you have the following thoughts about the progress of user\'s instruction completion:\n"
        prompt += "Completed contents:\n" + completed_content + "\n\n"
    
    if memory != "":
        prompt += "### Memory ###\n"
        prompt += "During the operations, you record the following contents on the screenshot for use in subsequent operations:\n"
        prompt += "Memory:\n" + memory + "\n"
    
    if error_flag:
        prompt += "### Last operation ###\n"
        prompt += f"You previously wanted to perform the operation \"{last_summary}\" on this page and executed the Action \"{last_action}\". But you find that this operation does not meet your expectation. You need to reflect and revise your operation this time."
        prompt += "\n\n"
    
    prompt += "### Response requirements ###\n"
    prompt += "Now you need to combine all of the above to perform just one action on the current page. You must choose one of the six actions below:\n"
    prompt += "Open app (app name): If the current page is desktop, you can use this action to open the app named \"app name\" on the desktop.\n"
    prompt += "Tap (x, y): Tap the position (x, y) in current page.\n"
    prompt += "Swipe (x1, y1), (x2, y2): Swipe from position (x1, y1) to position (x2, y2).\n"
    if keyboard:
        prompt += "Type (text): Type the \"text\" in the input box.\n"
    else:
        prompt += "Unable to Type. You cannot use the action \"Type\" because the keyboard has not been activated. If you want to type, please first activate the keyboard by tapping on the input box on the screen.\n"
    prompt += "Home: Return to home page.\n"
    prompt += "Stop: If you think all the requirements of user\'s instruction have been completed and no further operation is required, you can choose this action to terminate the operation process."
    prompt += "\n\n"
    
    prompt += "### Output format ###\n"
    prompt += "Your output consists of the following three parts:\n"
    prompt += "### Thought ###\nThink about the requirements that have been completed in previous operations and the requirements that need to be completed in the next one operation.\n"
    prompt += "### Action ###\nYou can only choose one from the six actions above. Make sure that the coordinates or text in the \"()\".\n"
    prompt += "### Operation ###\nPlease generate a brief natural language description for the operation in Action based on your Thought."
    
    return prompt


def get_reflect_prompt(instruction, clickable_infos1, clickable_infos2, width, height, keyboard1, keyboard2, summary, action, add_info):
    prompt = f"These images are two phone screenshots before and after an operation. Their widths are {width} pixels and their heights are {height} pixels.\n\n"
    
    prompt += "In order to help you better perceive the content in this screenshot, we extract some information on the current screenshot through system files. "
    prompt += "The information consists of two parts, consisting of format: coordinates; content. "
    prompt += "The format of the coordinates is [x, y], x is the pixel from left to right and y is the pixel from top to bottom; the content is a text or an icon description respectively "
    prompt += "The keyboard status is whether the keyboard of the current page is activated."
    prompt += "\n\n"
    
    prompt += "### Before the current operation ###\n"
    prompt += "Screenshot information:\n"
    for clickable_info in clickable_infos1:
        if clickable_info['text'] != "" and clickable_info['text'] != "icon: None" and clickable_info['coordinates'] != (0, 0):
            prompt += f"{clickable_info['coordinates']}; {clickable_info['text']}\n"
    prompt += "Keyboard status:\n"
    if keyboard1:
        prompt += f"The keyboard has been activated."
    else:
        prompt += "The keyboard has not been activated."
    prompt += "\n\n"
            
    prompt += "### After the current operation ###\n"
    prompt += "Screenshot information:\n"
    for clickable_info in clickable_infos2:
        if clickable_info['text'] != "" and clickable_info['text'] != "icon: None" and clickable_info['coordinates'] != (0, 0):
            prompt += f"{clickable_info['coordinates']}; {clickable_info['text']}\n"
    prompt += "Keyboard status:\n"
    if keyboard2:
        prompt += f"The keyboard has been activated."
    else:
        prompt += "The keyboard has not been activated."
    prompt += "\n\n"
    
    prompt += "### Current operation ###\n"
    prompt += f"The user\'s instruction is: {instruction}. You also need to note the following requirements: {add_info}. In the process of completing the requirements of instruction, an operation is performed on the phone. Below are the details of this operation:\n"
    prompt += "Operation thought: " + summary.split(" to ")[0].strip() + "\n"
    prompt += "Operation action: " + action
    prompt += "\n\n"
    
    prompt += "### Response requirements ###\n"
    prompt += "Now you need to output the following content based on the screenshots before and after the current operation:\n"
    prompt += "Whether the result of the \"Operation action\" meets your expectation of \"Operation thought\"?\n"
    prompt += "A: The result of the \"Operation action\" meets my expectation of \"Operation thought\".\n"
    prompt += "B: The \"Operation action\" results in a wrong page and I need to return to the previous page.\n"
    prompt += "C: The \"Operation action\" produces no changes."
    prompt += "\n\n"
    
    prompt += "### Output format ###\n"
    prompt += "Your output format is:\n"
    prompt += "### Thought ###\nYour thought about the question\n"
    prompt += "### Answer ###\nA or B or C"
    
    return prompt


def get_memory_prompt(insight):
    if insight != "":
        prompt  = "### Important content ###\n"
        prompt += insight
        prompt += "\n\n"
    
        prompt += "### Response requirements ###\n"
        prompt += "Please think about whether there is any content closely related to ### Important content ### on the current page? If there is, please output the content. If not, please output \"None\".\n\n"
    
    else:
        prompt  = "### Response requirements ###\n"
        prompt += "Please think about whether there is any content closely related to user\'s instrcution on the current page? If there is, please output the content. If not, please output \"None\".\n\n"
    
    prompt += "### Output format ###\n"
    prompt += "Your output format is:\n"
    prompt += "### Important content ###\nThe content or None. Please do not repeatedly output the information in ### Memory ###."
    
    return prompt

def get_process_prompt(instruction, thought_history, summary_history, action_history, completed_content, add_info):
    prompt = "### Background ###\n"
    prompt += f"There is an user\'s instruction which is: {instruction}. You are a mobile phone operating assistant and are helping the user to operate their mobile phone.\n\n"
    
    if add_info != "":
        prompt += "### Hint ###\n"
        prompt += "There are hints to help you complete the user\'s instructions. The hints are as follow:\n"
        prompt += add_info
        prompt += "\n\n"
    
    if len(thought_history) > 1:
        prompt += "### History operations ###\n"
        prompt += "To complete the requirements of user\'s instruction, the user has performed a series of operations. These operations are as follow:\n"
        for i in range(len(summary_history)):
            operation = summary_history[i].split(" to ")[0].strip() # TODO: Think about deleting the Operation thought
            prompt += f"Step-{i+1}: [Operation thought: " + operation + "; Operation action: " + action_history[i] + "]\n"
        prompt += "\n"
        
        prompt += "### Progress thinking ###\n"
        prompt += "After completing the history operations, you have the following thoughts about the progress of user\'s instruction completion:\n"
        prompt += "Completed contents:\n" + completed_content + "\n\n"
        
        prompt += "### Response requirements ###\n"
        prompt += "Now you need to update the \"Completed contents\". Completed contents is a general summary of the current contents that have been completed based on the ### History operations ###.\n\n"
        
        prompt += "### Output format ###\n"
        prompt += "Your output format is:\n"
        prompt += "### Completed contents ###\nUpdated Completed contents. Don\'t output the purpose of any operation. Just summarize the contents that have been actually completed in the ### History operations ###."
        
    else:
        prompt += "### Current operation ###\n"
        prompt += "To complete the requirements of user\'s instruction, the user has performed an operation. The user\'s operation thought and action of this operation are as follows:\n"
        prompt += f"Operation thought: {thought_history[-1]}\n"
        operation = summary_history[-1].split(" to ")[0].strip() # TODO: Think about deleting the Operation thought
        prompt += f"Operation action: {operation}\n\n"
        
        prompt += "### Response requirements ###\n"
        prompt += "Now you need to combine all of the above to generate the \"Completed contents\".\n"
        prompt += "Completed contents is a general summary of the current contents that have been completed. You need to first focus on the requirements of user\'s instruction, and then summarize the contents that have been completed.\n\n"
        
        prompt += "### Output format ###\n"
        prompt += "Your output format is:\n"
        prompt += "### Completed contents ###\nGenerated Completed contents. Don\'t output the purpose of any operation. Just summarize the contents that have been actually completed in the ### Current operation ###.\n"
        prompt += "(Please use English to output)"
        
    return prompt
