"""Immutable data for the existing fixed Planning/Decision/Classification flow."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPreset:
    instruction: str
    planning_hint: str
    decision_hint: str
    classification_hint: str


HOSPITAL_PRESET = TaskPreset(
    instruction='我要去皮肤科挂号',
    planning_hint="1. When you can't find an element directly related to a subtask in the current interface, consider whether the category to which the sub-element belongs is present in the interface\n2. 已经做过的子任务就不要再做了，如已经选择过医院，就不要再选择医院了\n3. 皮肤属于皮肤科，所以皮肤科是和任务相关的元素\n",
    decision_hint='1. 如果页面里有“皮肤”这个元素，它代表着皮肤科相关的元素，记得选择。\n        2. 根据科室选择医院的卡片的时候，应该把所有医院都选上。即不要根据医院名字是否和疾病相关来筛选医院，应该都选上\n        3. 选择医生的时候，应该把所有医生都选上，不要自己根据疾病来筛选\n        ',
    classification_hint="1. '去挂号'是不清晰的动作点，需要额外的上下文元素来说明动作的目标。",
)

_BURGER_HINT = "1. When you can't find an element directly related to a subtask in the current interface, consider whether the category to which the sub-element belongs is present in the interface, e.g. KFC belongs to Burger and Burger belongs to Food. So Food is relevant to the task.\n2. When you find that the screen has a sidebar to select categories, you should prioritize it as one of your tasks\n3. 如果你要选择汉堡的类别，你应该选择“汁汁牛堡”和“汉堡/卷”两个类别\n4. 选择商品之前一定要先选择商品的类别\n5. 美食也可能包含汉堡"

BURGER_PRESET = TaskPreset(
    instruction='我要点一份汉堡外卖',
    planning_hint=_BURGER_HINT,
    decision_hint=_BURGER_HINT,
    classification_hint="1. '添加按钮'是不清晰的动作点，需要额外的上下文元素来说明动作的目标。2. 汁汁牛堡也属于汉堡的类别",
)
