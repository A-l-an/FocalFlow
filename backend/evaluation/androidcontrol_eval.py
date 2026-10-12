#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import json
import logging
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from json import JSONDecoder
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import requests
from tfrecord import example_pb2

from android_env.proto.a11y import android_accessibility_forest_pb2

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from MobileAgent.config import validate_config_value

from MobileAgent.chat import (
    add_response,
    init_classify_chat,
    init_decision_chat,
    init_subtask_chat,
)
from MobileAgent.controller import filter_json_elements
from MobileAgent.prompt import (
    get_classify_prompt,
    get_decision_prompt,
    get_subtask_prompt,
)


DATASET_BASE_URL = "https://storage.googleapis.com/gresearch/android_control"
SHARD_URLS = [
    f"{DATASET_BASE_URL}/android_control-{shard:05d}-of-00020" for shard in range(20)
]
SPLITS_URL = f"{DATASET_BASE_URL}/splits.json"
TEST_SUBSPLITS_URL = f"{DATASET_BASE_URL}/test_subsplits.json"
SCREEN_CACHE_DIR = REPO_ROOT / "evaluation" / "androidcontrol_cache"
DEFAULT_DECISION_SCREEN_MANIFEST_PATH = REPO_ROOT / "evaluation" / "selected_decision_screens.json"
DEFAULT_EPISODE_MANIFEST_PATH = REPO_ROOT / "evaluation" / "selected_episodes.json"
DEFAULT_EPISODE_REPLAY_MANIFEST_PATH = REPO_ROOT / "evaluation" / "episode_replay_screens.json"
DEFAULT_MANIFEST_PATH = DEFAULT_DECISION_SCREEN_MANIFEST_PATH
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"
HTTP_TIMEOUT_SECONDS = 120
MODEL_NAME = "gpt-4"
NUM_REPEAT_RUNS = 5
VISUALIZATION_DIRNAME = "visualizations"
STANDARD_QUERIES = [
    "What categories of additional information are available on this screen?",
    "Can you describe the differences between the first and second option?",
]
LEGACY_SCREEN_MANIFEST_PATH = REPO_ROOT / "evaluation" / "selected_screens.json"
_PIL_MODULES: Optional[Tuple[Any, Any, Any]] = None


# ============================================================
# CATEGORY CONFIGURATION — MODIFY THIS BLOCK TO CHANGE SELECTION
# ============================================================
CATEGORY_CONFIG = {
    "in_domain": {
        "Transportation": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Health & Fitness": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
    },
    "out_domain": {
        "Shopping": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Flights": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Recipes": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Email": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Notes & Todos": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Maps": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Weather": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Finance": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Messaging": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
        "Productivity & Office": {
            "num_apps": 4,
            "tasks_per_app": 2,
            "decision_screens_per_task": 2,
            "example_apps": [],
        },
    },
}


# ============================================================
# MANUAL APP / PACKAGE -> CATEGORY MAP — MODIFY THIS BLOCK FIRST
# ============================================================
APP_DOMAIN_MAP = {
    "amazon": "Shopping",
    "in.amazon.mshop.android.shopping": "Shopping",
    "snapdeal": "Shopping",
    "com.snapdeal.main": "Shopping",
    "flipkart": "Shopping",
    "com.flipkart.android": "Shopping",
    "etsy": "Shopping",
    "com.etsy.android": "Shopping",
    "ebay": "Shopping",
    "com.ebay.mobile": "Shopping",
    "uber": "Transportation",
    "com.ubercab": "Transportation",
    "lyft": "Transportation",
    "me.lyft.android": "Transportation",
    "ola": "Transportation",
    "com.olacabs.customer": "Transportation",
    "grab": "Transportation",
    "com.grabtaxi.passenger": "Transportation",
    "google fit": "Health & Fitness",
    "com.google.android.apps.fitness": "Health & Fitness",
    "fitbit": "Health & Fitness",
    "com.fitbit.fitbitmobile": "Health & Fitness",
    "myfitnesspal": "Health & Fitness",
    "com.myfitnesspal.android": "Health & Fitness",
    "healthifyme": "Health & Fitness",
    "com.healthifyme.basic": "Health & Fitness",
    "kayak": "Flights",
    "com.kayak.android": "Flights",
    "skyscanner": "Flights",
    "com.skyscanner.android.main": "Flights",
    "hopper": "Flights",
    "com.hopper.mountainview.play": "Flights",
    "kitchen stories": "Recipes",
    "com.kitchenstories.android": "Recipes",
    "yummly": "Recipes",
    "com.yummly.android": "Recipes",
    "allrecipes": "Recipes",
    "com.allrecipes.spinner.free": "Recipes",
    "cookpad": "Recipes",
    "com.mufumbo.android.recipe.search": "Recipes",
    "calendar": "Calendar",
    "com.google.android.calendar": "Calendar",
    "gmail": "Email",
    "com.google.android.gm": "Email",
    "outlook": "Email",
    "com.microsoft.office.outlook": "Email",
    "yahoo mail": "Email",
    "com.yahoo.mobile.client.android.mail": "Email",
    "google keep": "Notes & Todos",
    "com.google.android.keep": "Notes & Todos",
    "todoist": "Notes & Todos",
    "com.todoist": "Notes & Todos",
    "microsoft to do": "Notes & Todos",
    "com.microsoft.todos": "Notes & Todos",
    "any.do": "Notes & Todos",
    "com.anydo": "Notes & Todos",
    "google maps": "Maps",
    "maps": "Maps",
    "com.google.android.apps.maps": "Maps",
    "waze": "Maps",
    "com.waze": "Maps",
    "weather": "Weather",
    "com.google.android.apps.weather": "Weather",
    "accuweather": "Weather",
    "com.accuweather.android": "Weather",
    "the weather channel": "Weather",
    "com.weather.Weather": "Weather",
    "paypal": "Finance",
    "com.paypal.android.p2pmobile": "Finance",
    "venmo": "Finance",
    "com.venmo": "Finance",
    "cash app": "Finance",
    "com.squareup.cash": "Finance",
    "robinhood": "Finance",
    "com.robinhood.android": "Finance",
    "contacts": "Contacts",
    "com.google.android.contacts": "Contacts",
    "spotify": "Music",
    "com.spotify.music": "Music",
    "youtube music": "Music",
    "com.google.android.apps.youtube.music": "Music",
    "soundcloud": "Music",
    "com.soundcloud.android": "Music",
    "zillow": "Real estate",
    "com.zillow.android.zillowmap": "Real estate",
    "realtor": "Real estate",
    "com.move.realtor": "Real estate",
    "redfin": "Real estate",
    "com.redfin.android": "Real estate",
    "messages": "Messaging",
    "com.google.android.apps.messaging": "Messaging",
    "messenger": "Messaging",
    "com.facebook.orca": "Messaging",
    "whatsapp": "Messaging",
    "com.whatsapp": "Messaging",
    "telegram": "Messaging",
    "org.telegram.messenger": "Messaging",
    "signal": "Messaging",
    "org.thoughtcrime.securesms": "Messaging",
    "zoho meeting": "Productivity & Office",
    "com.zoho.meeting": "Productivity & Office",
    "google meet": "Productivity & Office",
    "com.google.android.apps.meetings": "Productivity & Office",
    "zoom": "Productivity & Office",
    "us.zoom.videomeetings": "Productivity & Office",
    "google docs": "Productivity & Office",
    "com.google.android.apps.docs.editors.docs": "Productivity & Office",
    "google drive": "Productivity & Office",
    "com.google.android.apps.docs": "Productivity & Office",
    "slack": "Productivity & Office",
    "com.slack": "Productivity & Office",
    "files": "Files",
    "files by google": "Files",
    "com.google.android.apps.nbu.files": "Files",
    "dropbox": "Files",
    "com.dropbox.android": "Files",
}


GENERIC_OPTION_LABELS = {
    "back",
    "search",
    "menu",
    "more options",
    "settings",
    "close",
    "home",
    "profile",
    "open navigation drawer",
}
LOGIN_PATTERNS = [
    "sign in",
    "log in",
    "login",
    "password",
    "create account",
    "register",
    "verification",
    "otp",
    "forgot password",
]
CONFIRM_DIALOG_LABELS = {
    "ok",
    "cancel",
    "allow",
    "deny",
    "yes",
    "no",
    "confirm",
    "done",
    "not now",
    "continue",
}
IGNORED_WINDOW_PACKAGES = {
    "com.google.android.inputmethod.latin",
    "com.google.android.apps.nexuslauncher",
}
IGNORED_WINDOW_TITLES = {
    "english us qwerty",
    "home",
}


@dataclass
class RuntimeSettings:
    api_url: str
    api_token: str
    model: str
    add_info_subtask: str
    add_info_decision: str
    add_info_classify: str
    error_flag: bool


@dataclass
class ScreenSelection:
    screen_id: str
    episode_id: int
    observation_index: int
    episode_task_id: str
    app_name: str
    app_package: str
    app_category: str
    domain_group: str
    window_title: str
    task_objective: str
    current_step_instruction: str
    action_history: List[str]
    completed_subtasks: List[str]
    current_action_json: Optional[Dict[str, Any]]
    screenshot_width: int
    screenshot_height: int
    screenshot_path: str
    ui_tree_path: str
    is_decision_screen: bool
    decision_reason: str
    option_count: int
    option_labels: List[str]
    shard_url: str


@dataclass
class EpisodeSelection:
    episode_task_id: str
    episode_id: int
    app_name: str
    app_package: str
    app_category: str
    domain_group: str
    window_title: str
    task_objective: str
    shard_url: str
    step_count: int
    decision_screen_count: int
    selected_decision_screen_ids: List[str]
    steps: List[ScreenSelection]


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def normalize_key(value: Optional[str]) -> str:
    if not value:
        return ""
    lowered = value.casefold()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


NORMALIZED_APP_DOMAIN_MAP = {
    normalize_key(key): value for key, value in APP_DOMAIN_MAP.items() if normalize_key(key)
}


def slugify(value: str) -> str:
    value = normalize_key(value).replace(" ", "_")
    return value or "unknown"


def unique_preserve_order(items: Iterable[Any]) -> List[Any]:
    seen = set()
    ordered: List[Any] = []
    for item in items:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else item
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(item)
    return ordered


def parse_literal_assignments(run_py_path: Path) -> Dict[str, Any]:
    tree = ast.parse(run_py_path.read_text(encoding="utf-8"))
    values: Dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except Exception:
            continue
    return values


def load_runtime_settings(repo_root: Path) -> RuntimeSettings:
    run_settings = parse_literal_assignments(repo_root / "run.py")
    api_url = validate_config_value(os.getenv("FOCALFLOW_API_URL") or os.getenv("FOCALFLOW_CHAT_API_URL"), "FOCALFLOW_API_URL / FOCALFLOW_CHAT_API_URL")
    api_token = validate_config_value(os.getenv("FOCALFLOW_API_TOKEN") or os.getenv("FOCALFLOW_CHAT_API_TOKEN"), "FOCALFLOW_API_TOKEN / FOCALFLOW_CHAT_API_TOKEN")


    flag_burger = int(run_settings.get("flag_burger", 0) or 0)
    add_info_subtask = run_settings.get(
        "add_info_burger" if flag_burger else "add_info_hospital",
        "",
    )

    add_info_decision = (
        "1. When you can't find an element directly related to a subtask in the current interface, "
        "consider whether the category to which the sub-element belongs is present in the interface, "
        "e.g. KFC belongs to Burger and Burger belongs to Food. So Food is relevant to the task.\n"
        "2. When you find that the screen has a sidebar to select categories, you should prioritize it "
        "as one of your tasks\n"
        "3. 如果你要选择汉堡的类别，你应该选择“汁汁牛堡”和“汉堡/卷”两个类别\n"
        "4. 选择商品之前一定要先选择商品的类别\n"
        "5. 美食也可能包含汉堡"
        if flag_burger
        else "1. 如果页面里有“皮肤”这个元素，它代表着皮肤科相关的元素，记得选择。\n"
        "2. 根据科室选择医院的卡片的时候，应该把所有医院都选上。即不要根据医院名字是否和疾病相关来筛选医院，应该都选上\n"
        "3. 选择医生的时候，应该把所有医生都选上，不要自己根据疾病来筛选"
    )

    add_info_classify = (
        "1. '添加按钮'是不清晰的动作点，需要额外的上下文元素来说明动作的目标。"
        "2. 汁汁牛堡也属于汉堡的类别"
        if flag_burger
        else "1. '去挂号'是不清晰的动作点，需要额外的上下文元素来说明动作的目标。"
    )

    return RuntimeSettings(
        api_url=api_url,
        api_token=api_token,
        model=MODEL_NAME,
        add_info_subtask=add_info_subtask,
        add_info_decision=add_info_decision,
        add_info_classify=add_info_classify,
        error_flag=bool(run_settings.get("error_flag", False)),
    )


def fetch_json(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.load(response)


def load_split_ids(split_name: str) -> set[int]:
    splits = fetch_json(SPLITS_URL)
    if split_name not in splits:
        raise KeyError(f"Unknown split '{split_name}'. Available: {sorted(splits)}")
    return set(int(value) for value in splits[split_name])


def load_test_subsplit_ids(subsplit_name: Optional[str]) -> Optional[set[int]]:
    if not subsplit_name:
        return None
    splits = fetch_json(TEST_SUBSPLITS_URL)
    if subsplit_name not in splits:
        raise KeyError(f"Unknown test subsplit '{subsplit_name}'. Available: {sorted(splits)}")
    return set(int(value) for value in splits[subsplit_name])


def stream_tfrecord_examples(url: str) -> Iterator[example_pb2.Example]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to open shard {url}: {exc}") from exc

    with response:
        with gzip.GzipFile(fileobj=response) as gz:
            while True:
                try:
                    length_bytes = gz.read(8)
                except EOFError:
                    break
                if not length_bytes:
                    break
                if len(length_bytes) < 8:
                    break
                length = struct.unpack("<Q", length_bytes)[0]

                try:
                    if len(gz.read(4)) < 4:
                        break
                    record_bytes = gz.read(length)
                    if len(record_bytes) < length:
                        break
                    if len(gz.read(4)) < 4:
                        break
                except EOFError:
                    break

                example = example_pb2.Example()
                example.ParseFromString(record_bytes)
                yield example


def bytes_feature(example: example_pb2.Example, key: str) -> List[bytes]:
    return list(example.features.feature[key].bytes_list.value)


def int_feature(example: example_pb2.Example, key: str) -> List[int]:
    return list(example.features.feature[key].int64_list.value)


def decode_example(example: example_pb2.Example) -> Dict[str, Any]:
    return {
        "episode_id": int_feature(example, "episode_id")[0],
        "goal": bytes_feature(example, "goal")[0].decode("utf-8", "replace").strip(),
        "screenshots": bytes_feature(example, "screenshots"),
        "accessibility_trees": bytes_feature(example, "accessibility_trees"),
        "screenshot_widths": int_feature(example, "screenshot_widths"),
        "screenshot_heights": int_feature(example, "screenshot_heights"),
        "actions": [
            json.loads(payload.decode("utf-8", "replace")) for payload in bytes_feature(example, "actions")
        ],
        "step_instructions": [
            payload.decode("utf-8", "replace").strip() for payload in bytes_feature(example, "step_instructions")
        ],
    }


def choose_primary_window(
    forest: android_accessibility_forest_pb2.AndroidAccessibilityForest,
) -> Optional[android_accessibility_forest_pb2.AndroidAccessibilityWindowInfo]:
    candidate_windows = [
        window
        for window in forest.windows
        if window.tree.nodes and window.tree.nodes[0].package_name != "com.android.systemui"
    ]
    filtered_candidates = [
        window
        for window in candidate_windows
        if window.tree.nodes[0].package_name not in IGNORED_WINDOW_PACKAGES
    ]
    if filtered_candidates:
        candidate_windows = filtered_candidates
    if not candidate_windows:
        candidate_windows = [window for window in forest.windows if window.tree.nodes]
    if not candidate_windows:
        return None
    return max(candidate_windows, key=lambda window: (len(window.tree.nodes), bool(window.title), window.id))


def adapt_accessibility_tree(
    tree_bytes: bytes,
    episode_id: int,
    observation_index: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    forest = android_accessibility_forest_pb2.AndroidAccessibilityForest()
    forest.ParseFromString(tree_bytes)
    window = choose_primary_window(forest)
    if window is None:
        raise ValueError("No usable accessibility window found.")

    nodes = {node.unique_id: node for node in window.tree.nodes}
    parent_lookup: Dict[int, int] = {}
    for node in window.tree.nodes:
        for child_id in node.child_ids:
            parent_lookup[child_id] = node.unique_id

    root_ids = [node.unique_id for node in window.tree.nodes if node.unique_id not in parent_lookup]
    root_id = root_ids[0] if root_ids else window.tree.nodes[0].unique_id

    def build_node(node_id: int) -> Dict[str, Any]:
        node = nodes[node_id]
        bounds = {
            "left": int(node.bounds_in_screen.left),
            "top": int(node.bounds_in_screen.top),
            "right": int(node.bounds_in_screen.right),
            "bottom": int(node.bounds_in_screen.bottom),
        }
        center_x = int((bounds["left"] + bounds["right"]) / 2)
        center_y = int((bounds["top"] + bounds["bottom"]) / 2)
        converted: Dict[str, Any] = {
            "className": node.class_name or None,
            "text": node.text or None,
            "contentDescription": node.content_description or None,
            "viewIdResourceName": node.view_id_resource_name or None,
            "isClickable": bool(node.is_clickable),
            "isCheckable": bool(node.is_checkable),
            "isChecked": bool(node.is_checked),
            "isFocusable": bool(node.is_focusable),
            "isEnabled": bool(node.is_enabled),
            "isPassword": bool(node.is_password),
            "isSelected": bool(node.is_selected),
            "centerCoordinates": f"{center_x},{center_y}",
            "bounds": bounds,
            "isVirtualFocusNode": False,
            "virtualNodeId": f"element_{node_id}",
        }
        children: Dict[str, Any] = {}
        for child_id in node.child_ids:
            if child_id in nodes:
                children[f"element_{child_id}"] = build_node(child_id)
        if children:
            converted["children"] = children
        return converted

    tree_json = build_node(root_id)
    tree_json["captureTimestamp"] = f"android_control_ep_{episode_id}_obs_{observation_index}"
    metadata = {
        "window_title": window.title,
        "window_id": int(window.id),
        "package_name": window.tree.nodes[0].package_name if window.tree.nodes else "",
        "node_count": len(window.tree.nodes),
    }
    return tree_json, metadata


def iter_tree_nodes(root: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    def walk(node_id: str, node: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
        yield node_id, node
        for child_id, child in node.get("children", {}).items():
            yield from walk(child_id, child)

    for child_id, child in root.get("children", {}).items():
        yield from walk(child_id, child)


def build_tree_index(root: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    children_by_id: Dict[str, List[str]] = {}
    for node_id, node in iter_tree_nodes(root):
        nodes_by_id[node_id] = node
        children_by_id[node_id] = list(node.get("children", {}).keys())
    return nodes_by_id, children_by_id


def collect_texts_from_subtree(node: Dict[str, Any]) -> List[str]:
    values: List[str] = []

    def walk(current: Dict[str, Any]) -> None:
        text = current.get("text")
        content_description = current.get("contentDescription")
        if isinstance(text, str) and text.strip():
            values.append(text.strip())
        if isinstance(content_description, str) and content_description.strip():
            values.append(content_description.strip())
        for child in current.get("children", {}).values():
            walk(child)

    walk(node)
    return unique_preserve_order(values)


def summarize_subtree_label(node: Dict[str, Any], max_items: int = 4) -> str:
    texts = collect_texts_from_subtree(node)
    return " | ".join(texts[:max_items]).strip()


def all_screen_text(root: Dict[str, Any]) -> str:
    texts: List[str] = []
    for _, node in iter_tree_nodes(root):
        for field_name in ("text", "contentDescription"):
            value = node.get(field_name)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
    return " ".join(texts)


def node_bounds(node: Dict[str, Any]) -> Tuple[int, int, int, int]:
    bounds = node.get("bounds", {})
    return (
        int(bounds.get("left", 0)),
        int(bounds.get("top", 0)),
        int(bounds.get("right", 0)),
        int(bounds.get("bottom", 0)),
    )


def node_area(node: Dict[str, Any]) -> int:
    left, top, right, bottom = node_bounds(node)
    return max(0, right - left) * max(0, bottom - top)


def action_to_label(action: Optional[Dict[str, Any]]) -> str:
    if not action:
        return ""
    action_type = action.get("action_type", "")
    if action_type == "open_app":
        return f"open_app:{action.get('app_name', '')}".strip(":")
    if action_type == "click":
        return f"click:{action.get('x', '')},{action.get('y', '')}"
    if action_type == "scroll":
        return f"scroll:{action.get('direction', '')}"
    if action_type == "input_text":
        return f"input_text:{action.get('text', '')}"
    return action_type


def dedupe_consecutive(values: Sequence[str]) -> List[str]:
    deduped: List[str] = []
    previous = object()
    for value in values:
        if value == previous:
            continue
        deduped.append(value)
        previous = value
    return deduped


def resolve_category(
    open_app_name: Optional[str],
    window_title: Optional[str],
    package_name: Optional[str],
) -> Optional[str]:
    package_normalized = normalize_key(package_name)
    title_normalized = normalize_key(window_title)

    for candidate in (package_name, window_title):
        normalized = normalize_key(candidate)
        if normalized in NORMALIZED_APP_DOMAIN_MAP:
            return NORMALIZED_APP_DOMAIN_MAP[normalized]

    if not package_normalized and not title_normalized:
        normalized_open_app = normalize_key(open_app_name)
        if normalized_open_app in NORMALIZED_APP_DOMAIN_MAP:
            return NORMALIZED_APP_DOMAIN_MAP[normalized_open_app]
    return None


def option_candidates(root: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for node_id, node in iter_tree_nodes(root):
        if not node.get("isClickable") and not node.get("isCheckable"):
            continue
        if node_area(node) < 4000:
            continue
        label = summarize_subtree_label(node)
        normalized_label = normalize_key(label)
        if not normalized_label:
            continue
        if normalized_label in GENERIC_OPTION_LABELS:
            continue
        bounds = node_bounds(node)
        signature = (normalized_label, bounds)
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(
            {
                "node_id": node_id,
                "label": label,
                "normalized_label": normalized_label,
                "bounds": bounds,
            }
        )
    return candidates


def is_login_like_screen(root: Dict[str, Any]) -> bool:
    screen_text = normalize_key(all_screen_text(root))
    return any(pattern in screen_text for pattern in LOGIN_PATTERNS)


def is_confirmation_like_screen(candidates: Sequence[Dict[str, Any]]) -> bool:
    if not candidates or len(candidates) > 3:
        return False
    normalized = {candidate["normalized_label"] for candidate in candidates}
    return normalized.issubset(CONFIRM_DIALOG_LABELS)


def is_decision_point_screen(root: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str]:
    candidates = option_candidates(root)
    if is_login_like_screen(root):
        return False, candidates, "login_like"
    if len(candidates) < 3:
        return False, candidates, "too_few_options"
    if is_confirmation_like_screen(candidates):
        return False, candidates, "confirmation_dialog"
    return True, candidates, "accepted"


def category_targets(config: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    targets: Dict[str, Dict[str, Any]] = {}
    for domain_group, categories in config.items():
        for category_name, category_settings in categories.items():
            targets[category_name] = {
                "domain_group": domain_group,
                "num_apps": int(category_settings["num_apps"]),
                "tasks_per_app": int(category_settings["tasks_per_app"]),
                "decision_screens_per_task": int(category_settings["decision_screens_per_task"]),
                "example_apps": [normalize_key(value) for value in category_settings.get("example_apps", [])],
            }
    return targets


def benchmark_target_totals(targets: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    category_count = 0
    app_count = 0
    episode_count = 0
    decision_screen_count = 0
    for target in targets.values():
        if target["num_apps"] <= 0 or target["tasks_per_app"] <= 0:
            continue
        category_count += 1
        app_count += target["num_apps"]
        episode_count += target["num_apps"] * target["tasks_per_app"]
        decision_screen_count += (
            target["num_apps"] * target["tasks_per_app"] * target["decision_screens_per_task"]
        )
    return {
        "categories": category_count,
        "apps": app_count,
        "episodes": episode_count,
        "decision_screens": decision_screen_count,
    }


def app_selection_key(app_package: str, app_name: str, window_title: str) -> str:
    return normalize_key(app_package or app_name or window_title)


def choose_evenly_spaced_indices(total_items: int, desired_items: int) -> List[int]:
    if desired_items <= 0 or total_items <= 0:
        return []
    if desired_items >= total_items:
        return list(range(total_items))
    if desired_items == 1:
        return [0]

    chosen = []
    last_index = total_items - 1
    for rank in range(desired_items):
        index = round(rank * last_index / (desired_items - 1))
        if chosen and index <= chosen[-1]:
            index = min(last_index, chosen[-1] + 1)
        chosen.append(index)
    return chosen[:desired_items]


def select_decision_screen_ids(
    decision_screens: Sequence[ScreenSelection],
    decision_screens_per_task: int,
) -> List[str]:
    indices = choose_evenly_spaced_indices(len(decision_screens), decision_screens_per_task)
    return [decision_screens[index].screen_id for index in indices]


def write_screen_artifacts(
    selection: ScreenSelection,
    screenshot_bytes: bytes,
    tree_json: Dict[str, Any],
) -> None:
    screenshot_path = Path(selection.screenshot_path)
    ui_tree_path = Path(selection.ui_tree_path)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    ui_tree_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(screenshot_bytes)
    ui_tree_path.write_text(json.dumps(tree_json, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_accept_episode(
    selected: Dict[str, Dict[str, List[EpisodeSelection]]],
    episode: EpisodeSelection,
    targets: Dict[str, Dict[str, Any]],
) -> bool:
    target = targets.get(episode.app_category)
    if not target or target["num_apps"] <= 0 or target["tasks_per_app"] <= 0:
        return False

    app_key = app_selection_key(episode.app_package, episode.app_name, episode.window_title)
    example_apps = target["example_apps"]
    if example_apps and app_key not in example_apps and normalize_key(episode.app_name) not in example_apps:
        return False

    category_bucket = selected[episode.app_category]
    if app_key in category_bucket:
        if len(category_bucket[app_key]) >= target["tasks_per_app"]:
            return False
        category_bucket[app_key].append(episode)
        return True

    if len(category_bucket) >= target["num_apps"]:
        return False

    category_bucket[app_key].append(episode)
    return True


def episode_quotas_satisfied(
    selected: Dict[str, Dict[str, List[EpisodeSelection]]],
    targets: Dict[str, Dict[str, Any]],
) -> bool:
    for category_name, target in targets.items():
        if target["num_apps"] <= 0 or target["tasks_per_app"] <= 0:
            continue
        category_bucket = selected.get(category_name, {})
        if len(category_bucket) < target["num_apps"]:
            return False
        if any(len(episodes) < target["tasks_per_app"] for episodes in category_bucket.values()):
            return False
    return True


def build_episode_selection(
    decoded: Dict[str, Any],
    shard_url: str,
    targets: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[EpisodeSelection], List[Tuple[ScreenSelection, bytes, Dict[str, Any]]], Optional[str]]:
    episode_id = decoded["episode_id"]
    actions = decoded["actions"]
    step_instructions = decoded["step_instructions"]
    observations = min(len(actions), len(decoded["screenshots"]), len(decoded["accessibility_trees"]))
    open_app_name = next(
        (
            action.get("app_name", "")
            for action in actions
            if action.get("action_type") == "open_app" and action.get("app_name")
        ),
        "",
    )

    step_artifacts: List[Tuple[ScreenSelection, bytes, Dict[str, Any]]] = []
    decision_screens: List[ScreenSelection] = []
    app_name = ""
    app_package = ""
    app_category: Optional[str] = None
    domain_group = ""
    window_title = ""

    for observation_index in range(observations):
        try:
            tree_json, window_metadata = adapt_accessibility_tree(
                decoded["accessibility_trees"][observation_index],
                episode_id=episode_id,
                observation_index=observation_index,
            )
        except Exception as exc:
            return None, [], f"tree_adaptation_error:{exc}"

        current_category = resolve_category(
            open_app_name=open_app_name,
            window_title=window_metadata.get("window_title"),
            package_name=window_metadata.get("package_name"),
        )
        if app_category is None and current_category in targets:
            app_category = current_category
            domain_group = targets[current_category]["domain_group"]
            app_name = (
                window_metadata.get("window_title")
                or open_app_name
                or window_metadata.get("package_name", "")
            )
            app_package = window_metadata.get("package_name", "")
            window_title = window_metadata.get("window_title", "")

        current_step_instruction = (
            step_instructions[observation_index] if observation_index < len(step_instructions) else ""
        )
        action_history = step_instructions[:observation_index]
        completed_subtasks = dedupe_consecutive(action_history)
        screen_id = f"ac_ep{episode_id:05d}_obs{observation_index:02d}"

        accepted, candidates, reason = is_decision_point_screen(tree_json)
        screen = ScreenSelection(
            screen_id=screen_id,
            episode_id=episode_id,
            observation_index=observation_index,
            episode_task_id=f"ac_ep{episode_id:05d}",
            app_name=app_name or window_metadata.get("window_title") or open_app_name or window_metadata.get("package_name", ""),
            app_package=app_package or window_metadata.get("package_name", ""),
            app_category=app_category or current_category or "",
            domain_group=domain_group,
            window_title=window_title or window_metadata.get("window_title", ""),
            task_objective=decoded["goal"],
            current_step_instruction=current_step_instruction,
            action_history=action_history,
            completed_subtasks=completed_subtasks,
            current_action_json=actions[observation_index] if observation_index < len(actions) else None,
            screenshot_width=decoded["screenshot_widths"][observation_index],
            screenshot_height=decoded["screenshot_heights"][observation_index],
            screenshot_path=str(SCREEN_CACHE_DIR / f"{screen_id}.png"),
            ui_tree_path=str(SCREEN_CACHE_DIR / f"{screen_id}.json"),
            is_decision_screen=accepted,
            decision_reason=reason,
            option_count=len(candidates),
            option_labels=[candidate["label"] for candidate in candidates],
            shard_url=shard_url,
        )
        step_artifacts.append((screen, decoded["screenshots"][observation_index], tree_json))
        if accepted:
            decision_screens.append(screen)

    if not app_category or app_category not in targets:
        return None, [], "unmapped_category"

    for index, (screen, screenshot_bytes, tree_json) in enumerate(step_artifacts):
        if screen.app_category != app_category or not screen.domain_group:
            step_artifacts[index] = (
                ScreenSelection(
                    screen_id=screen.screen_id,
                    episode_id=screen.episode_id,
                    observation_index=screen.observation_index,
                    episode_task_id=screen.episode_task_id,
                    app_name=app_name or screen.app_name,
                    app_package=app_package or screen.app_package,
                    app_category=app_category,
                    domain_group=domain_group,
                    window_title=window_title or screen.window_title,
                    task_objective=screen.task_objective,
                    current_step_instruction=screen.current_step_instruction,
                    action_history=screen.action_history,
                    completed_subtasks=screen.completed_subtasks,
                    current_action_json=screen.current_action_json,
                    screenshot_width=screen.screenshot_width,
                    screenshot_height=screen.screenshot_height,
                    screenshot_path=screen.screenshot_path,
                    ui_tree_path=screen.ui_tree_path,
                    is_decision_screen=screen.is_decision_screen,
                    decision_reason=screen.decision_reason,
                    option_count=screen.option_count,
                    option_labels=screen.option_labels,
                    shard_url=screen.shard_url,
                ),
                screenshot_bytes,
                tree_json,
            )

    decision_screens = [screen for screen, _, _ in step_artifacts if screen.is_decision_screen]
    required_decision_screens = targets[app_category]["decision_screens_per_task"]
    if len(decision_screens) < required_decision_screens:
        return None, [], "too_few_decision_screens"

    selected_decision_screen_ids = select_decision_screen_ids(decision_screens, required_decision_screens)
    episode = EpisodeSelection(
        episode_task_id=f"ac_ep{episode_id:05d}",
        episode_id=episode_id,
        app_name=app_name or open_app_name or app_package,
        app_package=app_package,
        app_category=app_category,
        domain_group=domain_group,
        window_title=window_title,
        task_objective=decoded["goal"],
        shard_url=shard_url,
        step_count=len(step_artifacts),
        decision_screen_count=len(decision_screens),
        selected_decision_screen_ids=selected_decision_screen_ids,
        steps=[screen for screen, _, _ in step_artifacts],
    )
    return episode, step_artifacts, None


def flatten_episode_steps(episodes: Sequence[EpisodeSelection]) -> List[ScreenSelection]:
    flattened: List[ScreenSelection] = []
    for episode in episodes:
        flattened.extend(sorted(episode.steps, key=lambda step: step.observation_index))
    return flattened


def extract_selected_decision_screens(episodes: Sequence[EpisodeSelection]) -> List[ScreenSelection]:
    selected_screens: List[ScreenSelection] = []
    for episode in episodes:
        selected_ids = set(episode.selected_decision_screen_ids)
        selected_screens.extend(
            step
            for step in sorted(episode.steps, key=lambda item: item.observation_index)
            if step.screen_id in selected_ids
        )
    return selected_screens


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_selection_metadata(
    *,
    split_name: str,
    test_subsplit: Optional[str],
    max_episodes: int,
    scanned_matching_episodes: int,
    targets: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "split": split_name,
        "test_subsplit": test_subsplit,
        "max_matching_episodes_scanned": max_episodes,
        "scanned_matching_episodes": scanned_matching_episodes,
        "target_config": CATEGORY_CONFIG,
        "target_totals": benchmark_target_totals(targets),
    }


def serialize_episode_manifest(
    *,
    episodes: Sequence[EpisodeSelection],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "manifest_type": "episode_benchmark",
        "metadata": metadata,
        "episodes": [asdict(episode) for episode in episodes],
    }


def serialize_screen_manifest(
    *,
    screens: Sequence[ScreenSelection],
    metadata: Dict[str, Any],
    benchmark_line: str,
) -> Dict[str, Any]:
    return {
        "manifest_type": "screen_benchmark",
        "benchmark_line": benchmark_line,
        "metadata": metadata,
        "screens": [asdict(screen) for screen in screens],
    }


def select_benchmarks_from_dataset(
    split_name: str,
    test_subsplit: Optional[str],
    max_episodes: int,
    episode_manifest_path: Path,
    decision_screen_manifest_path: Path,
    episode_replay_manifest_path: Path,
) -> Tuple[List[EpisodeSelection], List[ScreenSelection], List[ScreenSelection]]:
    split_ids = load_split_ids(split_name)
    subsplit_ids = load_test_subsplit_ids(test_subsplit)
    targets = category_targets(CATEGORY_CONFIG)
    selected: Dict[str, Dict[str, List[EpisodeSelection]]] = defaultdict(lambda: defaultdict(list))
    scanned = 0

    for shard_url in SHARD_URLS:
        logging.info("Scanning shard: %s", shard_url)
        for example in stream_tfrecord_examples(shard_url):
            decoded = decode_example(example)
            episode_id = decoded["episode_id"]
            if episode_id not in split_ids:
                continue
            if subsplit_ids is not None and episode_id not in subsplit_ids:
                continue

            scanned += 1
            episode, step_artifacts, rejection_reason = build_episode_selection(decoded, shard_url, targets)
            if episode is None:
                logging.debug("Rejected episode %s (%s)", episode_id, rejection_reason or "unknown_reason")
            elif maybe_accept_episode(selected, episode, targets):
                for screen, screenshot_bytes, tree_json in step_artifacts:
                    write_screen_artifacts(screen, screenshot_bytes, tree_json)
                logging.info(
                    "Selected episode %s | %s | %s | steps=%s | decision_screens=%s | sampled=%s",
                    episode.episode_task_id,
                    episode.app_name,
                    episode.app_category,
                    episode.step_count,
                    episode.decision_screen_count,
                    len(episode.selected_decision_screen_ids),
                )

            if scanned >= max_episodes or episode_quotas_satisfied(selected, targets):
                break

        if scanned >= max_episodes or episode_quotas_satisfied(selected, targets):
            break

    episodes = sorted(
        [episode for category in selected.values() for episodes in category.values() for episode in episodes],
        key=lambda item: (item.domain_group, item.app_category, normalize_key(item.app_name), item.episode_task_id),
    )
    episode_replay_screens = flatten_episode_steps(episodes)
    decision_screens = extract_selected_decision_screens(episodes)
    metadata = build_selection_metadata(
        split_name=split_name,
        test_subsplit=test_subsplit,
        max_episodes=max_episodes,
        scanned_matching_episodes=scanned,
        targets=targets,
    )

    write_json(
        episode_manifest_path,
        serialize_episode_manifest(episodes=episodes, metadata=metadata),
    )
    write_json(
        decision_screen_manifest_path,
        serialize_screen_manifest(
            screens=decision_screens,
            metadata=metadata,
            benchmark_line="decision_screen",
        ),
    )
    write_json(
        episode_replay_manifest_path,
        serialize_screen_manifest(
            screens=episode_replay_screens,
            metadata=metadata,
            benchmark_line="episode_replay",
        ),
    )
    logging.info("Wrote %s selected episodes to %s", len(episodes), episode_manifest_path)
    logging.info("Wrote %s decision screens to %s", len(decision_screens), decision_screen_manifest_path)
    logging.info(
        "Wrote %s replay screens to %s",
        len(episode_replay_screens),
        episode_replay_manifest_path,
    )
    return episodes, decision_screens, episode_replay_screens


def load_manifest_payload(manifest_path: Path) -> Dict[str, Any]:
    resolved_path = manifest_path
    if not resolved_path.exists():
        if (
            manifest_path.name == DEFAULT_DECISION_SCREEN_MANIFEST_PATH.name
            and LEGACY_SCREEN_MANIFEST_PATH.exists()
        ):
            logging.warning(
                "Manifest %s not found. Falling back to legacy manifest %s.",
                manifest_path,
                LEGACY_SCREEN_MANIFEST_PATH,
            )
            resolved_path = LEGACY_SCREEN_MANIFEST_PATH
        else:
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"manifest_type": "screen_benchmark", "metadata": {}, "screens": raw}
    if isinstance(raw, dict):
        return raw
    raise TypeError(f"Unsupported manifest format in {resolved_path}")


def screen_selection_from_dict(item: Dict[str, Any]) -> ScreenSelection:
    screen_dict = dict(item)
    screen_dict.setdefault("episode_task_id", f"ac_ep{int(screen_dict.get('episode_id', 0)):05d}")
    screen_dict.setdefault("is_decision_screen", True)
    screen_dict.setdefault("decision_reason", "accepted")
    return ScreenSelection(**screen_dict)


def load_screen_manifest(manifest_path: Path) -> List[ScreenSelection]:
    payload = load_manifest_payload(manifest_path)
    raw_screens = payload.get("screens")
    if not isinstance(raw_screens, list):
        raise ValueError(f"Manifest {manifest_path} does not contain a 'screens' list.")
    return [screen_selection_from_dict(item) for item in raw_screens]


def load_episode_manifest(manifest_path: Path) -> List[EpisodeSelection]:
    payload = load_manifest_payload(manifest_path)
    raw_episodes = payload.get("episodes")
    if not isinstance(raw_episodes, list):
        raise ValueError(f"Manifest {manifest_path} does not contain an 'episodes' list.")

    episodes: List[EpisodeSelection] = []
    for item in raw_episodes:
        steps = [screen_selection_from_dict(step) for step in item.get("steps", [])]
        episode_dict = dict(item)
        episode_dict["steps"] = steps
        episodes.append(EpisodeSelection(**episode_dict))
    return episodes


def get_element_json(data: Dict[str, Any], target: str) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict):
        for key, value in data.items():
            if key == target:
                return value
            if isinstance(value, dict):
                result = get_element_json(value, target)
                if result:
                    return result
    return None


def descendant_ids_for_root(root_tree: Dict[str, Any], target_id: str) -> List[str]:
    def gather(node_id: str, node: Dict[str, Any]) -> List[str]:
        descendants = [node_id]
        for child_id, child in node.get("children", {}).items():
            descendants.extend(gather(child_id, child))
        return descendants

    for child_id, child in root_tree.get("children", {}).items():
        if child_id == target_id:
            return gather(child_id, child)
        descendant_match = descendant_ids_for_root(child, target_id)
        if descendant_match:
            return descendant_match
    return []


def extract_section(text: str, section_name: str, next_sections: Optional[Sequence[str]] = None) -> str:
    pattern = re.escape(section_name)
    matches = list(re.finditer(pattern, text))
    if not matches:
        return ""
    start_index = matches[0].end()
    end_index = len(text)
    for next_section in next_sections or []:
        next_pattern = re.escape(next_section)
        next_match = re.search(next_pattern, text[start_index:])
        if next_match:
            end_index = min(end_index, start_index + next_match.start())
    return text[start_index:end_index].strip()


def parse_json_section(section: str, fallback: Any) -> Any:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", section, flags=re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else section.strip()
    if not candidate:
        return fallback

    decoder = JSONDecoder()
    for marker in ("[", "{"):
        index = candidate.find(marker)
        if index == -1:
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[index:])
            return parsed
        except json.JSONDecodeError:
            continue
    return fallback


def build_request_messages(chat_history: List[List[Any]]) -> List[Dict[str, Any]]:
    return [{"role": role, "content": content} for role, content in chat_history]


def extract_chat_completion_content(response: requests.Response) -> str:
    try:
        response_json = response.json()
    except ValueError as exc:
        snippet = response.text[:1000]
        raise RuntimeError(
            f"Chat completion response was not valid JSON. status={response.status_code}, body={snippet!r}"
        ) from exc

    if "choices" not in response_json:
        error_payload = response_json.get("error", response_json)
        raise RuntimeError(
            f"Chat completion response missing 'choices'. status={response.status_code}, body={json.dumps(error_payload, ensure_ascii=False)[:1000]}"
        )

    try:
        return response_json["choices"][0]["message"]["content"]
    except (IndexError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"Chat completion response had unexpected 'choices' shape. status={response.status_code}, body={json.dumps(response_json, ensure_ascii=False)[:1000]}"
        ) from exc


def call_chat_completion(
    chat_history: List[List[Any]],
    runtime_settings: RuntimeSettings,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep_between_calls_seconds: float,
) -> Tuple[str, float]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {runtime_settings.api_token}",
    }
    payload = {
        "model": runtime_settings.model,
        "messages": build_request_messages(chat_history),
        "max_tokens": 2048,
        "temperature": 0.0,
        "seed": 1234,
    }

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        start_time = time.perf_counter()
        try:
            response = requests.post(
                runtime_settings.api_url,
                headers=headers,
                json=payload,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = extract_chat_completion_content(response)
            latency_seconds = time.perf_counter() - start_time
            if sleep_between_calls_seconds > 0:
                time.sleep(sleep_between_calls_seconds)
            return content, latency_seconds
        except Exception as exc:
            last_error = exc
            logging.warning("Chat completion attempt %s/%s failed: %s", attempt + 1, max_retries, exc)
            if attempt < max_retries - 1:
                time.sleep(retry_backoff_seconds * (2**attempt))

    raise RuntimeError(f"Chat completion failed after {max_retries} attempts: {last_error}") from last_error


def run_planning_agent(
    screen: ScreenSelection,
    runtime_settings: RuntimeSettings,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep_between_calls_seconds: float,
) -> Tuple[str, Dict[str, Any], float]:
    ui_tree = json.loads(Path(screen.ui_tree_path).read_text(encoding="utf-8"))
    pruned_tree = filter_json_elements(ui_tree)
    last_summary = screen.completed_subtasks[-1] if screen.completed_subtasks else ""
    last_action = action_to_label(screen.current_action_json)
    prompt = get_subtask_prompt(
        screen.task_objective,
        pruned_tree,
        screen.completed_subtasks,
        screen.action_history,
        last_summary,
        last_action,
        runtime_settings.add_info_subtask,
        runtime_settings.error_flag,
        "",
        "",
    )
    chat = init_subtask_chat()
    chat = add_response("user", prompt, chat, screen.screenshot_path)
    raw_output, latency_seconds = call_chat_completion(
        chat,
        runtime_settings,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        sleep_between_calls_seconds=sleep_between_calls_seconds,
    )
    parsed_output = {
        "screen_overview": extract_section(raw_output, "### Screen ###"),
        "subtask_instruction": extract_section(raw_output, "### Subtask ###", ["### Screen ###"]),
        "thought": extract_section(raw_output, "### Thought ###", ["### Subtask ###"]),
    }
    return raw_output, parsed_output, latency_seconds


def run_decision_agent(
    screen: ScreenSelection,
    runtime_settings: RuntimeSettings,
    current_subtask: str,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep_between_calls_seconds: float,
) -> Tuple[str, Dict[str, Any], float]:
    ui_tree = json.loads(Path(screen.ui_tree_path).read_text(encoding="utf-8"))
    pruned_tree = filter_json_elements(ui_tree)

    decision_prompt = get_decision_prompt(
        screen.task_objective,
        pruned_tree,
        screen.completed_subtasks,
        screen.action_history,
        current_subtask,
        action_to_label(screen.current_action_json),
        runtime_settings.add_info_decision,
        runtime_settings.error_flag,
        "",
        "",
        current_subtask,
    )
    decision_chat = init_decision_chat()
    decision_chat = add_response("user", decision_prompt, decision_chat, screen.screenshot_path)
    raw_decision_output, decision_latency = call_chat_completion(
        decision_chat,
        runtime_settings,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        sleep_between_calls_seconds=sleep_between_calls_seconds,
    )
    relevant_area_list = parse_json_section(
        extract_section(raw_decision_output, "### Output ###"),
        [],
    )
    if not isinstance(relevant_area_list, list):
        relevant_area_list = []

    relevant_area_all_info = {
        root_id: get_element_json(ui_tree, root_id) for root_id in relevant_area_list if isinstance(root_id, str)
    }
    classify_prompt = get_classify_prompt(
        screen.task_objective,
        current_subtask,
        json.dumps(relevant_area_all_info, ensure_ascii=False, indent=2),
        runtime_settings.add_info_classify,
    )
    classify_chat = init_classify_chat()
    classify_chat = add_response("user", classify_prompt, classify_chat, screen.screenshot_path)
    raw_classify_output, classify_latency = call_chat_completion(
        classify_chat,
        runtime_settings,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        sleep_between_calls_seconds=sleep_between_calls_seconds,
    )

    categories_json = parse_json_section(
        extract_section(raw_classify_output, "### Categories ###", ["### SelectedUI ###"]),
        {},
    )
    if not isinstance(categories_json, dict):
        categories_json = {}

    selected_ui_json = parse_json_section(
        extract_section(raw_classify_output, "### SelectedUI ###"),
        [],
    )
    if not isinstance(selected_ui_json, list):
        selected_ui_json = []

    all_node_ids = [node_id for node_id, _ in iter_tree_nodes(ui_tree)]
    scb_node_ids = [
        descendant_ids_for_root(ui_tree, root_id) for root_id in relevant_area_list if isinstance(root_id, str)
    ]
    scb_node_ids = [ids for ids in scb_node_ids if ids]

    top_most_relevant_ids: List[str] = []
    context_element_ids: List[str] = []
    for item in selected_ui_json:
        if not isinstance(item, dict):
            continue
        action_point = item.get("action_point")
        if isinstance(action_point, str) and action_point:
            top_most_relevant_ids.append(action_point)
        for context_item in item.get("context_elements", []):
            if isinstance(context_item, dict):
                context_name = context_item.get("name")
                if isinstance(context_name, str) and context_name:
                    context_element_ids.append(context_name)

    top_most_relevant_ids = unique_preserve_order(top_most_relevant_ids)
    context_element_ids = unique_preserve_order(context_element_ids)
    scb_member_ids = unique_preserve_order([node_id for ids in scb_node_ids for node_id in ids])
    decision_support_ids = [node_id for node_id in scb_member_ids if node_id not in top_most_relevant_ids]
    irrelevant_ids = [node_id for node_id in all_node_ids if node_id not in scb_member_ids]

    parsed_output = {
        "scb_root_ids": relevant_area_list,
        "scb_node_ids": scb_node_ids,
        "top_most_relevant_ids": top_most_relevant_ids,
        "decision_support_ids": decision_support_ids,
        "irrelevant_ids": irrelevant_ids,
        "raw_classification_context_ids": context_element_ids,
        "raw_categories": categories_json,
        "raw_selected_ui": selected_ui_json,
        "raw_decision_thought": extract_section(raw_decision_output, "### Thought ###", ["### Output ###"]),
        "raw_classify_thought": extract_section(raw_classify_output, "### Thought ###", ["### Categories ###"]),
    }
    total_latency_seconds = decision_latency + classify_latency
    raw_output = json.dumps(
        {
            "decision_raw": raw_decision_output,
            "classification_raw": raw_classify_output,
        },
        ensure_ascii=False,
    )
    return raw_output, parsed_output, total_latency_seconds


def init_dataset_eval_talk_chat() -> List[List[Any]]:
    return [[
        "system",
        [{
            "type": "text",
            "text": (
                "You are an AI assistant for technical evaluation of mobile screen understanding. "
                "You must answer questions directly about a static Android screen using the screenshot "
                "and provided UI structure. Do not decide navigation policy, do not ask follow-up questions, "
                "and do not pretend there is a live user conversation."
            ),
        }],
    ]]


def get_dataset_eval_talk_prompt(
    *,
    query: str,
    task_objective: str,
    current_subtask: str,
    pruned_tree: Dict[str, Any],
    categories_json: Dict[str, Any],
) -> str:
    prompt = "## Dataset Evaluation Context\n"
    prompt += (
        "You are answering a technical-evaluation question about a static Android screen from a dataset. "
        "There is no live end user in the loop. Do not decide whether to go back or adjust focus. "
        "Your only job is to answer the question directly based on the current screen.\n\n"
    )

    prompt += "## Available Inputs\n"
    prompt += f"- User's overall task objective: {task_objective}\n"
    if current_subtask:
        prompt += f"- Current subtask for context: {current_subtask}\n"
    prompt += "- A screenshot of the current screen is attached and should be used as visual evidence.\n"
    prompt += "- A pruned UI tree is provided below as structured evidence.\n"
    prompt += "- Optional semantic categories from the Decision/Classification stage are also provided below.\n\n"

    prompt += "### Pruned UI Tree\n"
    prompt += f"```json\n{json.dumps(pruned_tree, ensure_ascii=False, indent=2)}\n```\n\n"

    prompt += "### Semantic Categories From Decision Stage\n"
    prompt += f"```json\n{json.dumps(categories_json, ensure_ascii=False, indent=2)}\n```\n\n"

    prompt += "## Question To Answer\n"
    prompt += f"{query}\n\n"

    prompt += "## Answering Rules\n"
    prompt += "1. Answer the question directly in Chinese.\n"
    prompt += "2. Use both the screenshot and the structured UI evidence when possible.\n"
    prompt += "3. If the question compares the first and second option, interpret option order by visible reading order: top-to-bottom, and left-to-right within the same row.\n"
    prompt += "4. If the screen does not provide enough evidence for a reliable answer, say what is missing instead of guessing.\n"
    prompt += "5. If semantic categories help answer the question, list the category names you relied on. Otherwise leave that section empty.\n\n"

    prompt += "## Output Format\n"
    prompt += "Your output must strictly contain the following three sections and nothing else.\n\n"
    prompt += "### Thought ###\n"
    prompt += "Brief reasoning in Chinese.\n\n"
    prompt += "### Answer ###\n"
    prompt += "A direct Chinese answer to the question.\n\n"
    prompt += "### Referenced Categories ###\n"
    prompt += "Comma-separated category names from the semantic category JSON that helped answer the question. Leave empty if none were used.\n"
    return prompt


def run_talk_agent(
    screen: ScreenSelection,
    current_subtask: str,
    query: str,
    categories_json: Dict[str, Any],
    runtime_settings: RuntimeSettings,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep_between_calls_seconds: float,
) -> Tuple[str, Dict[str, Any], float]:
    ui_tree = json.loads(Path(screen.ui_tree_path).read_text(encoding="utf-8"))
    pruned_tree = filter_json_elements(ui_tree)
    prompt = get_dataset_eval_talk_prompt(
        query=query,
        task_objective=screen.task_objective,
        current_subtask=current_subtask,
        pruned_tree=pruned_tree,
        categories_json=categories_json,
    )
    chat = init_dataset_eval_talk_chat()
    chat = add_response("user", prompt, chat, screen.screenshot_path)
    raw_output, latency_seconds = call_chat_completion(
        chat,
        runtime_settings,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        sleep_between_calls_seconds=sleep_between_calls_seconds,
    )
    answer = extract_section(raw_output, "### Answer ###", ["### Referenced Categories ###"])
    referenced_categories_raw = extract_section(raw_output, "### Referenced Categories ###")
    categories = [
        value.strip()
        for value in referenced_categories_raw.replace("，", ",").split(",")
        if value.strip()
    ]
    expanded_element_ids: List[str] = []
    for category_name in categories:
        if category_name in categories_json and isinstance(categories_json[category_name], dict):
            expanded_element_ids.extend(categories_json[category_name].keys())
    parsed_output = {
        "mode": "QA",
        "displayed_ui_categories": categories,
        "expanded_element_ids": unique_preserve_order(expanded_element_ids),
        "answer": answer.strip(),
        "answer_source": "dataset_eval_prompt",
        "thought": extract_section(raw_output, "### Thought ###", ["### Answer ###"]),
    }
    return raw_output, enrich_talk_output(query, parsed_output), latency_seconds


def safe_mean(values: Sequence[Optional[float]]) -> Optional[float]:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def build_summary_row_from_screen_result(screen_result: Dict[str, Any]) -> Dict[str, Any]:
    planning_runs = screen_result.get("planning_agent", {}).get("runs", [])
    decision_runs = screen_result.get("decision_agent", {}).get("runs", [])
    talk_queries = screen_result.get("talk_agent", {}).get("queries", [])
    talk_runs = [run for query in talk_queries for run in query.get("runs", [])]
    return {
        "screen_id": screen_result.get("screen_id"),
        "episode_task_id": screen_result.get("episode_task_id"),
        "app_name": screen_result.get("app_name"),
        "app_package": screen_result.get("app_package"),
        "category": screen_result.get("app_category"),
        "domain_group": screen_result.get("domain_group"),
        "planning_latency_mean": safe_mean([run.get("latency_seconds") for run in planning_runs]),
        "decision_latency_mean": safe_mean([run.get("latency_seconds") for run in decision_runs]),
        "talk_latency_mean": safe_mean([run.get("latency_seconds") for run in talk_runs]),
        "is_decision_screen": screen_result.get("is_decision_screen"),
        "option_count": screen_result.get("option_count"),
    }


def runs_all_successful(runs: Sequence[Dict[str, Any]]) -> bool:
    return bool(runs) and all(not run.get("error") for run in runs)


def result_is_fully_successful(screen_result: Dict[str, Any]) -> bool:
    planning_runs = screen_result.get("planning_agent", {}).get("runs", [])
    decision_runs = screen_result.get("decision_agent", {}).get("runs", [])
    talk_queries = screen_result.get("talk_agent", {}).get("queries", [])
    talk_runs = [run for query in talk_queries for run in query.get("runs", [])]
    return (
        runs_all_successful(planning_runs)
        and runs_all_successful(decision_runs)
        and runs_all_successful(talk_runs)
    )


def get_pillow_modules() -> Tuple[Any, Any, Any]:
    global _PIL_MODULES
    if _PIL_MODULES is not None:
        return _PIL_MODULES
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        raise RuntimeError(
            "Pillow is unavailable in the current Python environment. "
            "Sampling/evaluation can still run, but visualization image generation is disabled."
        ) from exc
    _PIL_MODULES = (Image, ImageDraw, ImageFont)
    return _PIL_MODULES


def load_annotation_font(size: int) -> ImageFont.ImageFont:
    _, _, ImageFont = get_pillow_modules()
    font_candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for font_path in font_candidates:
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_text_for_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> List[str]:
    if not text:
        return [""]

    lines: List[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = f"{current}{char}"
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if current and (bbox[2] - bbox[0]) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines or [""]


def build_visualization_node_lookup(root_tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    nodes_by_id, _ = build_tree_index(root_tree)
    root_node_id = root_tree.get("virtualNodeId")
    if isinstance(root_node_id, str) and root_node_id:
        nodes_by_id[root_node_id] = root_tree
    return nodes_by_id


def lookup_box(
    nodes_by_id: Dict[str, Dict[str, Any]],
    node_id: str,
    image_width: int,
    image_height: int,
) -> Optional[Tuple[int, int, int, int]]:
    node = nodes_by_id.get(node_id)
    if not node:
        return None
    left, top, right, bottom = node_bounds(node)
    left = max(0, min(left, image_width))
    right = max(0, min(right, image_width))
    top = max(0, min(top, image_height))
    bottom = max(0, min(bottom, image_height))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def render_box_set(
    image: Image.Image,
    header_height: int,
    boxes: Sequence[Tuple[int, int, int, int]],
    color: Tuple[int, int, int, int],
    line_width: int,
) -> None:
    Image, ImageDraw, _ = get_pillow_modules()
    if not boxes:
        return
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    for left, top, right, bottom in boxes:
        draw.rectangle(
            [left, top + header_height, right, bottom + header_height],
            outline=color,
            width=line_width,
        )
    image.alpha_composite(overlay)


def build_talk_answer(
    query: str,
    mode: str,
    displayed_ui_categories: Sequence[str],
) -> Dict[str, str]:
    normalized_mode = (mode or "").strip().upper()
    categories_text = "、".join(category for category in displayed_ui_categories if category)
    if normalized_mode == "A":
        return {
            "answer_type": "back_navigation",
            "answer": "Talk Agent 将该问询判定为返回上一步，而不是继续展开当前界面信息。",
        }
    if not categories_text:
        return {
            "answer_type": "empty_category_mapping",
            "answer": "Talk Agent 没有识别到与该问询匹配的界面信息类别。",
        }
    if normalize_key(query) == normalize_key(STANDARD_QUERIES[0]):
        return {
            "answer_type": "category_mapping",
            "answer": f"该问询对应的附加信息类别为：{categories_text}。",
        }
    if normalize_key(query) == normalize_key(STANDARD_QUERIES[1]):
        return {
            "answer_type": "category_mapping",
            "answer": f"该问询被 Talk Agent 映射到以下类别以供后续展开：{categories_text}。",
        }
    return {
        "answer_type": "category_mapping",
        "answer": f"Talk Agent 识别到该问询对应的类别为：{categories_text}。",
    }


def enrich_talk_output(query: str, parsed_output: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(parsed_output)
    categories = output.get("displayed_ui_categories", [])
    if not isinstance(categories, list):
        categories = []
    displayed_ui_raw = ", ".join(
        category for category in categories if isinstance(category, str) and category.strip()
    )
    output["displayed_ui_raw"] = displayed_ui_raw
    if not str(output.get("answer", "")).strip():
        output.update(
            build_talk_answer(
                query=query,
                mode=str(output.get("mode", "")),
                displayed_ui_categories=categories,
            )
        )
    elif not str(output.get("answer_type", "")).strip():
        output["answer_type"] = "direct_answer"
    return output


def render_decision_visualizations(
    *,
    screen_id: str,
    run_id: int,
    screenshot_path: Path,
    ui_tree_path: Path,
    current_subtask: str,
    decision_output: Dict[str, Any],
    talk_annotations: Sequence[Dict[str, str]],
    results_dir: Path,
) -> Dict[str, str]:
    results_dir = results_dir.resolve()
    Image, ImageDraw, _ = get_pillow_modules()
    screenshot = Image.open(screenshot_path).convert("RGBA")
    ui_tree = json.loads(ui_tree_path.read_text(encoding="utf-8"))
    nodes_by_id = build_visualization_node_lookup(ui_tree)

    image_width, image_height = screenshot.size
    scb_root_ids = [
        node_id for node_id in decision_output.get("scb_root_ids", []) if isinstance(node_id, str)
    ]
    top_most_relevant_ids = [
        node_id for node_id in decision_output.get("top_most_relevant_ids", []) if isinstance(node_id, str)
    ]
    decision_support_ids = [
        node_id for node_id in decision_output.get("decision_support_ids", []) if isinstance(node_id, str)
    ]

    def collect_boxes(node_ids: Sequence[str]) -> List[Tuple[int, int, int, int]]:
        boxes: List[Tuple[int, int, int, int]] = []
        seen = set()
        for node_id in node_ids:
            bounds = lookup_box(nodes_by_id, node_id, image_width, image_height)
            if not bounds or bounds in seen:
                continue
            seen.add(bounds)
            boxes.append(bounds)
        return boxes

    scb_boxes = collect_boxes(scb_root_ids)
    top_boxes = collect_boxes(top_most_relevant_ids)
    support_boxes = collect_boxes(decision_support_ids)

    margin = max(16, image_width // 40)
    title_font = load_annotation_font(max(42, image_width // 18))
    meta_font = load_annotation_font(max(30, image_width // 26))
    body_font = load_annotation_font(max(32, image_width // 28))
    measure_image = Image.new("RGBA", (image_width, 10), (255, 255, 255, 0))
    measure_draw = ImageDraw.Draw(measure_image)

    header_title = f"Current Subtask / 当前子任务: {current_subtask or 'N/A'}"
    header_meta = [
        f"Screen: {screen_id}    Decision Run: {run_id}",
        f"SCB Roots: {len(scb_boxes)}    Top Relevant: {len(top_boxes)}    Decision Support: {len(support_boxes)}",
    ]
    if talk_annotations:
        header_meta.append(f"Talk Answers Shown: Run {run_id}")
    wrapped_title_lines = wrap_text_for_width(
        measure_draw,
        header_title,
        title_font,
        max(100, image_width - 2 * margin),
    )

    talk_lines: List[str] = []
    for index, item in enumerate(talk_annotations, start=1):
        query = str(item.get("query", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if query:
            talk_lines.append(f"Talk Q{index}: {query}")
        if answer:
            talk_lines.append(f"Answer: {answer}")
        categories = str(item.get("displayed_ui_raw", "")).strip()
        if categories:
            talk_lines.append(f"Mapped Categories: {categories}")
        talk_lines.append("")
    if talk_lines and not talk_lines[-1]:
        talk_lines.pop()
    if not talk_lines:
        talk_lines = ["Talk Agent outputs are not available for this run."]

    wrapped_talk_lines: List[str] = []
    for talk_line in talk_lines:
        wrapped_talk_lines.extend(
            wrap_text_for_width(
                measure_draw,
                talk_line,
                body_font,
                max(100, image_width - 2 * margin),
            )
        )

    title_height = title_font.size + 8
    meta_height = meta_font.size + 6
    legend_height = meta_font.size + 14
    footer_line_height = body_font.size + 10
    header_height = (
        margin
        + len(wrapped_title_lines) * title_height
        + len(header_meta) * meta_height
        + legend_height
        + margin // 2
    )
    footer_height = margin + len(wrapped_talk_lines) * footer_line_height + margin

    line_width = max(3, min(image_width, image_height) // 220)
    colors = {
        "scb": (220, 38, 38, 255),
        "top": (22, 163, 74, 255),
        "support": (37, 99, 235, 255),
    }
    output_dir = results_dir / VISUALIZATION_DIRNAME / screen_id
    output_dir.mkdir(parents=True, exist_ok=True)

    def draw_header(base: Image.Image) -> None:
        draw = ImageDraw.Draw(base)
        draw.rectangle([0, 0, base.width, header_height], fill=(255, 255, 255, 255))
        y = margin // 2
        for line in wrapped_title_lines:
            draw.text((margin, y), line, font=title_font, fill=(0, 0, 0, 255))
            y += title_height
        for meta_line in header_meta:
            draw.text((margin, y), meta_line, font=meta_font, fill=(0, 0, 0, 255))
            y += meta_height

        legend_y = header_height - legend_height
        legend_items = [
            ("SCB Roots", colors["scb"]),
            ("Top Relevant Elements", colors["top"]),
            ("Decision Support Elements", colors["support"]),
        ]
        legend_x = margin
        for label, color in legend_items:
            draw.rectangle(
                [legend_x, legend_y + 4, legend_x + 18, legend_y + 22],
                outline=color,
                width=3,
            )
            legend_x += 28
            draw.text((legend_x, legend_y), label, font=meta_font, fill=(0, 0, 0, 255))
            legend_x += int(draw.textlength(label, font=meta_font)) + 28

    def draw_footer(base: Image.Image) -> None:
        draw = ImageDraw.Draw(base)
        footer_top = header_height + image_height
        draw.rectangle([0, footer_top, base.width, base.height], fill=(255, 255, 255, 255))
        y = footer_top + margin // 2
        for line in wrapped_talk_lines:
            draw.text((margin, y), line, font=body_font, fill=(0, 0, 0, 255))
            y += footer_line_height

    def build_canvas() -> Image.Image:
        canvas = Image.new(
            "RGBA",
            (image_width, image_height + header_height + footer_height),
            (255, 255, 255, 255),
        )
        canvas.paste(screenshot, (0, header_height))
        draw_header(canvas)
        draw_footer(canvas)
        return canvas

    canvas = build_canvas()
    render_box_set(
        canvas,
        header_height=header_height,
        boxes=scb_boxes,
        color=colors["scb"],
        line_width=line_width,
    )
    render_box_set(
        canvas,
        header_height=header_height,
        boxes=support_boxes,
        color=colors["support"],
        line_width=line_width,
    )
    render_box_set(
        canvas,
        header_height=header_height,
        boxes=top_boxes,
        color=colors["top"],
        line_width=line_width + 1,
    )
    output_path = output_dir / f"decision_run_{run_id:02d}_annotated.png"
    canvas.convert("RGB").save(output_path)
    return {"annotated": str(output_path)}


def render_talk_visualization(
    *,
    screen_id: str,
    query_index: int,
    run_id: int,
    screenshot_path: Path,
    ui_tree_path: Path,
    current_subtask: str,
    query: str,
    talk_output: Dict[str, Any],
    results_dir: Path,
) -> Dict[str, str]:
    results_dir = results_dir.resolve()
    Image, ImageDraw, _ = get_pillow_modules()
    screenshot = Image.open(screenshot_path).convert("RGBA")
    ui_tree = json.loads(ui_tree_path.read_text(encoding="utf-8"))
    nodes_by_id = build_visualization_node_lookup(ui_tree)
    image_width, image_height = screenshot.size

    expanded_element_ids = [
        node_id for node_id in talk_output.get("expanded_element_ids", []) if isinstance(node_id, str)
    ]
    expanded_boxes: List[Tuple[int, int, int, int]] = []
    seen_boxes = set()
    for node_id in expanded_element_ids:
        bounds = lookup_box(nodes_by_id, node_id, image_width, image_height)
        if not bounds or bounds in seen_boxes:
            continue
        seen_boxes.add(bounds)
        expanded_boxes.append(bounds)

    margin = max(16, image_width // 40)
    title_font = load_annotation_font(max(42, image_width // 18))
    meta_font = load_annotation_font(max(30, image_width // 26))
    body_font = load_annotation_font(max(32, image_width // 28))
    measure_image = Image.new("RGBA", (image_width, 10), (255, 255, 255, 0))
    measure_draw = ImageDraw.Draw(measure_image)

    title_lines = wrap_text_for_width(
        measure_draw,
        f"Talk Agent / 当前子任务: {current_subtask or 'N/A'}",
        title_font,
        max(100, image_width - 2 * margin),
    )
    meta_lines = [
        f"Screen: {screen_id}    Query: {query_index}    Run: {run_id}",
        f"Mode: {str(talk_output.get('mode', '')).strip() or 'N/A'}    Highlighted Elements: {len(expanded_boxes)}",
    ]
    body_lines_source = [
        f"Talk Question / 问题: {query}",
        f"Talk Answer / 答案: {str(talk_output.get('answer', '')).strip() or 'N/A'}",
    ]
    displayed_ui_raw = str(talk_output.get("displayed_ui_raw", "")).strip()
    if displayed_ui_raw:
        body_lines_source.append(f"Mapped Categories / 映射类别: {displayed_ui_raw}")
    thought = str(talk_output.get("thought", "")).strip()
    if thought:
        body_lines_source.append(f"Talk Thought / 思考: {thought}")

    wrapped_body_lines: List[str] = []
    for line in body_lines_source:
        wrapped_body_lines.extend(
            wrap_text_for_width(
                measure_draw,
                line,
                body_font,
                max(100, image_width - 2 * margin),
            )
        )

    title_height = title_font.size + 10
    meta_height = meta_font.size + 8
    body_height = body_font.size + 10
    legend_height = meta_font.size + 16
    header_height = (
        margin
        + len(title_lines) * title_height
        + len(meta_lines) * meta_height
        + len(wrapped_body_lines) * body_height
        + legend_height
        + margin
    )

    line_width = max(4, min(image_width, image_height) // 180)
    highlight_color = (234, 88, 12, 255)

    canvas = Image.new(
        "RGBA",
        (image_width, image_height + header_height),
        (255, 255, 255, 255),
    )
    canvas.paste(screenshot, (0, header_height))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, canvas.width, header_height], fill=(255, 255, 255, 255))

    y = margin // 2
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill=(0, 0, 0, 255))
        y += title_height
    for line in meta_lines:
        draw.text((margin, y), line, font=meta_font, fill=(0, 0, 0, 255))
        y += meta_height
    for line in wrapped_body_lines:
        draw.text((margin, y), line, font=body_font, fill=(0, 0, 0, 255))
        y += body_height

    legend_y = header_height - legend_height
    draw.rectangle(
        [margin, legend_y + 4, margin + 24, legend_y + 28],
        outline=highlight_color,
        width=4,
    )
    draw.text(
        (margin + 34, legend_y),
        "Talk Expanded Elements",
        font=meta_font,
        fill=(0, 0, 0, 255),
    )

    render_box_set(
        canvas,
        header_height=header_height,
        boxes=expanded_boxes,
        color=highlight_color,
        line_width=line_width,
    )

    output_dir = results_dir / VISUALIZATION_DIRNAME / screen_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"talk_query_{query_index:02d}_run_{run_id:02d}_annotated.png"
    canvas.convert("RGB").save(output_path)
    return {"annotated": str(output_path)}


def augment_result_payload(
    screen_result: Dict[str, Any],
    results_dir: Path,
) -> Dict[str, Any]:
    decision_agent = screen_result.setdefault("decision_agent", {})
    planning_agent = screen_result.get("planning_agent", {})
    planning_runs = planning_agent.get("runs", []) if isinstance(planning_agent, dict) else []
    current_subtask = ""
    for run in planning_runs:
        if not isinstance(run, dict):
            continue
        output = run.get("output")
        if isinstance(output, dict):
            current_subtask = str(output.get("subtask_instruction", "")).strip()
        if current_subtask:
            break
    if not current_subtask:
        current_subtask = str(screen_result.get("current_step_instruction", "")).strip()
    decision_agent["current_subtask_seed"] = current_subtask

    screen_visualization_dir = results_dir / VISUALIZATION_DIRNAME / str(screen_result.get("screen_id", ""))
    if screen_visualization_dir.exists():
        shutil.rmtree(screen_visualization_dir)

    talk_agent = screen_result.get("talk_agent", {})
    talk_by_run: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    if isinstance(talk_agent, dict):
        for query_index, query_block in enumerate(talk_agent.get("queries", []), start=1):
            if not isinstance(query_block, dict):
                continue
            query = str(query_block.get("query", ""))
            for run in query_block.get("runs", []):
                if not isinstance(run, dict):
                    continue
                run["current_subtask"] = current_subtask
                run["visualizations"] = {}
                output = run.get("output")
                if isinstance(output, dict):
                    enriched_output = enrich_talk_output(query, output)
                    run["output"] = enriched_output
                    run_id = int(run.get("run_id", 0) or 0)
                    talk_by_run[run_id].append(
                        {
                            "query": query,
                            "answer": str(enriched_output.get("answer", "")),
                            "displayed_ui_raw": str(enriched_output.get("displayed_ui_raw", "")),
                        }
                    )
                    if not run.get("error"):
                        try:
                            run["visualizations"] = render_talk_visualization(
                                screen_id=str(screen_result.get("screen_id", "")),
                                query_index=query_index,
                                run_id=run_id,
                                screenshot_path=Path(screen_result["screenshot_path"]),
                                ui_tree_path=Path(screen_result["ui_tree_path"]),
                                current_subtask=current_subtask,
                                query=query,
                                talk_output=enriched_output,
                                results_dir=results_dir,
                            )
                            run["visualization_error"] = None
                        except Exception as exc:
                            run["visualization_error"] = str(exc)
                else:
                    run["visualization_error"] = None

    screenshot_path = Path(screen_result["screenshot_path"])
    ui_tree_path = Path(screen_result["ui_tree_path"])
    for run in decision_agent.get("runs", []):
        if not isinstance(run, dict):
            continue
        run["current_subtask"] = current_subtask
        run["visualizations"] = {}
        output = run.get("output")
        if not isinstance(output, dict) or run.get("error"):
            continue
        try:
            visualizations = render_decision_visualizations(
                screen_id=str(screen_result.get("screen_id", "")),
                run_id=int(run.get("run_id", 0) or 0),
                screenshot_path=screenshot_path,
                ui_tree_path=ui_tree_path,
                current_subtask=current_subtask,
                decision_output=output,
                talk_annotations=talk_by_run.get(int(run.get("run_id", 0) or 0), []),
                results_dir=results_dir,
            )
            run["visualizations"] = visualizations
            run["visualization_error"] = None
        except Exception as exc:
            run["visualization_error"] = str(exc)
    return screen_result


def backfill_results(results_dir: Path) -> None:
    results_dir = results_dir.resolve()
    result_paths = sorted(path for path in results_dir.glob("*.json") if path.is_file())
    if not result_paths:
        logging.warning("No result JSON files found in %s", results_dir)
        return
    for result_path in result_paths:
        screen_result = json.loads(result_path.read_text(encoding="utf-8"))
        updated_result = augment_result_payload(screen_result, results_dir=results_dir)
        result_path.write_text(
            json.dumps(updated_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info("Backfilled artifacts for %s", result_path.name)


def estimate_api_calls(screen_count: int, repeat_runs: int = NUM_REPEAT_RUNS) -> Dict[str, int]:
    planning_calls = screen_count * repeat_runs
    decision_calls = screen_count * repeat_runs * 2
    talk_calls = screen_count * len(STANDARD_QUERIES) * repeat_runs
    return {
        "planning_calls": planning_calls,
        "decision_and_classification_calls": decision_calls,
        "talk_calls": talk_calls,
        "total_calls": planning_calls + decision_calls + talk_calls,
    }


def evaluate_manifest(
    manifest_path: Path,
    results_dir: Path,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep_between_calls_seconds: float,
    run_api: bool,
    resume_existing: bool,
) -> None:
    results_dir = results_dir.resolve()
    screens = load_screen_manifest(manifest_path)
    manifest_payload = load_manifest_payload(manifest_path)
    api_call_estimate = estimate_api_calls(len(screens))
    logging.info("Manifest contains %s screens.", len(screens))
    logging.info("Manifest type: %s", manifest_payload.get("manifest_type", "unknown"))
    logging.info("Benchmark line: %s", manifest_payload.get("benchmark_line", "unspecified"))
    logging.info("Estimated API calls: %s", api_call_estimate)

    if not run_api:
        print(json.dumps({"screen_count": len(screens), "api_call_estimate": api_call_estimate}, indent=2))
        return

    runtime_settings = load_runtime_settings(REPO_ROOT)
    results_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict[str, Any]] = []
    for screen in screens:
        logging.info("Evaluating %s (%s / %s)", screen.screen_id, screen.app_name, screen.app_category)
        result_path = results_dir / f"{screen.screen_id}.json"
        if resume_existing and result_path.exists():
            try:
                existing_result = json.loads(result_path.read_text(encoding="utf-8"))
                if result_is_fully_successful(existing_result):
                    summary_rows.append(build_summary_row_from_screen_result(existing_result))
                    logging.info(
                        "Skipping %s because %s is already fully successful.",
                        screen.screen_id,
                        result_path.name,
                    )
                    continue
                logging.info(
                    "Recomputing %s because %s contains failed or partial runs.",
                    screen.screen_id,
                    result_path.name,
                )
            except Exception as exc:
                logging.warning(
                    "Failed to load existing result for %s from %s: %s. Recomputing.",
                    screen.screen_id,
                    result_path.name,
                    exc,
                )

        planning_runs: List[Dict[str, Any]] = []
        first_planning_subtask = ""
        for run_id in range(1, NUM_REPEAT_RUNS + 1):
            try:
                raw_output, parsed_output, latency_seconds = run_planning_agent(
                    screen,
                    runtime_settings,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                    sleep_between_calls_seconds=sleep_between_calls_seconds,
                )
                if run_id == 1:
                    first_planning_subtask = parsed_output.get("subtask_instruction", "").strip()
                planning_runs.append(
                    {
                        "run_id": run_id,
                        "output": {
                            "screen_overview": parsed_output.get("screen_overview", ""),
                            "subtask_instruction": parsed_output.get("subtask_instruction", ""),
                            "thought": parsed_output.get("thought", ""),
                        },
                        "raw_output": raw_output,
                        "latency_seconds": latency_seconds,
                        "error": None,
                    }
                )
            except Exception as exc:
                planning_runs.append(
                    {
                        "run_id": run_id,
                        "output": None,
                        "raw_output": None,
                        "latency_seconds": None,
                        "error": str(exc),
                    }
                )

        if not first_planning_subtask:
            first_planning_subtask = screen.current_step_instruction or ""

        decision_runs: List[Dict[str, Any]] = []
        talk_seed_categories: Dict[str, Any] = {}
        for run_id in range(1, NUM_REPEAT_RUNS + 1):
            try:
                raw_output, parsed_output, latency_seconds = run_decision_agent(
                    screen,
                    runtime_settings,
                    current_subtask=first_planning_subtask,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                    sleep_between_calls_seconds=sleep_between_calls_seconds,
                )
                if run_id == 1:
                    talk_seed_categories = parsed_output.get("raw_categories", {})
                decision_runs.append(
                    {
                        "run_id": run_id,
                        "current_subtask": first_planning_subtask,
                        "output": parsed_output,
                        "visualizations": {},
                        "raw_output": raw_output,
                        "latency_seconds": latency_seconds,
                        "visualization_error": None,
                        "error": None,
                    }
                )
            except Exception as exc:
                decision_runs.append(
                    {
                        "run_id": run_id,
                        "current_subtask": first_planning_subtask,
                        "output": None,
                        "visualizations": {},
                        "raw_output": None,
                        "latency_seconds": None,
                        "visualization_error": None,
                        "error": str(exc),
                    }
                )

        talk_queries: List[Dict[str, Any]] = []
        for query in STANDARD_QUERIES:
            talk_runs: List[Dict[str, Any]] = []
            for run_id in range(1, NUM_REPEAT_RUNS + 1):
                try:
                    raw_output, parsed_output, latency_seconds = run_talk_agent(
                        screen=screen,
                        current_subtask=first_planning_subtask,
                        query=query,
                        categories_json=talk_seed_categories,
                        runtime_settings=runtime_settings,
                        max_retries=max_retries,
                        retry_backoff_seconds=retry_backoff_seconds,
                        sleep_between_calls_seconds=sleep_between_calls_seconds,
                    )
                    talk_runs.append(
                        {
                            "run_id": run_id,
                            "output": parsed_output,
                            "raw_output": raw_output,
                            "latency_seconds": latency_seconds,
                            "error": None,
                        }
                    )
                except Exception as exc:
                    talk_runs.append(
                        {
                            "run_id": run_id,
                            "output": None,
                            "raw_output": None,
                            "latency_seconds": None,
                            "error": str(exc),
                        }
                    )
            talk_queries.append({"query": query, "runs": talk_runs})

        screen_result = {
            "screen_id": screen.screen_id,
            "episode_id": screen.episode_id,
            "observation_index": screen.observation_index,
            "episode_task_id": screen.episode_task_id,
            "app_name": screen.app_name,
            "app_package": screen.app_package,
            "app_category": screen.app_category,
            "domain_group": screen.domain_group,
            "task_objective": screen.task_objective,
            "current_step_instruction": screen.current_step_instruction,
            "action_history": screen.action_history,
            "completed_subtasks": screen.completed_subtasks,
            "screenshot_path": screen.screenshot_path,
            "ui_tree_path": screen.ui_tree_path,
            "is_decision_screen": screen.is_decision_screen,
            "decision_reason": screen.decision_reason,
            "option_count": screen.option_count,
            "option_labels": screen.option_labels,
            "planning_agent": {"runs": planning_runs},
            "decision_agent": {
                "current_subtask_seed": first_planning_subtask,
                "runs": decision_runs,
            },
            "talk_agent": {"queries": talk_queries},
        }
        screen_result = augment_result_payload(screen_result, results_dir=results_dir)
        result_path.write_text(
            json.dumps(screen_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary_rows.append(build_summary_row_from_screen_result(screen_result))

    summary_path = results_dir / "summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "screen_id",
                "episode_task_id",
                "app_name",
                "app_package",
                "category",
                "domain_group",
                "planning_latency_mean",
                "decision_latency_mean",
                "talk_latency_mean",
                "is_decision_screen",
                "option_count",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    logging.info("Wrote results to %s", results_dir)


def inspect_dataset(
    split_name: str,
    test_subsplit: Optional[str],
    max_episodes: int,
) -> None:
    split_ids = load_split_ids(split_name)
    subsplit_ids = load_test_subsplit_ids(test_subsplit)
    category_counter: Counter[str] = Counter()
    app_counter: Counter[Tuple[str, str, str]] = Counter()
    example_tree_schema: Optional[Dict[str, Any]] = None

    scanned = 0
    for shard_url in SHARD_URLS:
        logging.info("Inspecting shard: %s", shard_url)
        for example in stream_tfrecord_examples(shard_url):
            decoded = decode_example(example)
            episode_id = decoded["episode_id"]
            if episode_id not in split_ids:
                continue
            if subsplit_ids is not None and episode_id not in subsplit_ids:
                continue
            scanned += 1

            actions = decoded["actions"]
            open_app_name = next(
                (
                    action.get("app_name", "")
                    for action in actions
                    if action.get("action_type") == "open_app" and action.get("app_name")
                ),
                "",
            )
            for observation_index in range(min(len(decoded["screenshots"]), len(decoded["accessibility_trees"]))):
                try:
                    tree_json, metadata = adapt_accessibility_tree(
                        decoded["accessibility_trees"][observation_index],
                        episode_id=episode_id,
                        observation_index=observation_index,
                    )
                except Exception:
                    continue

                category = resolve_category(
                    open_app_name=open_app_name,
                    window_title=metadata.get("window_title"),
                    package_name=metadata.get("package_name"),
                )
                if category:
                    category_counter[category] += 1
                app_counter[
                    (
                        metadata.get("window_title", ""),
                        metadata.get("package_name", ""),
                        category or "UNMAPPED",
                    )
                ] += 1
                if example_tree_schema is None:
                    sample_child_id = next(iter(tree_json.get("children", {})), None)
                    example_tree_schema = {
                        "top_level_keys": list(tree_json.keys()),
                        "sample_child_id": sample_child_id,
                        "sample_child_keys": list(tree_json.get("children", {}).get(sample_child_id, {}).keys())
                        if sample_child_id
                        else [],
                    }
                    break

            if scanned >= max_episodes and example_tree_schema is not None:
                break
        if scanned >= max_episodes and example_tree_schema is not None:
            break

    print("Mapped categories discovered:")
    for category_name, count in category_counter.most_common():
        print(f"  {category_name}: {count}")

    print("\nObserved apps:")
    for (title, package, category), count in app_counter.most_common():
        title_text = title or "<no title>"
        package_text = package or "<no package>"
        print(f"  {category:22} | {title_text:30} | {package_text} | {count}")

    if example_tree_schema:
        print("\nExample adapted tree schema:")
        print(json.dumps(example_tree_schema, ensure_ascii=False, indent=2))


def print_episode_manifest_summary(manifest_path: Path) -> None:
    payload = load_manifest_payload(manifest_path)
    metadata = payload.get("metadata", {})
    episodes = load_episode_manifest(manifest_path)
    by_category: Dict[str, List[EpisodeSelection]] = defaultdict(list)
    for episode in episodes:
        by_category[episode.app_category].append(episode)

    total_steps = sum(episode.step_count for episode in episodes)
    total_selected_decision_screens = sum(len(episode.selected_decision_screen_ids) for episode in episodes)
    print(f"Manifest: {manifest_path}")
    print("Manifest type: episode_benchmark")
    print(f"Total episodes: {len(episodes)}")
    print(f"Total replay screens: {total_steps}")
    print(f"Total selected decision screens: {total_selected_decision_screens}")
    if metadata:
        print(f"Scanned matching episodes: {metadata.get('scanned_matching_episodes')}")
        if metadata.get("target_totals"):
            print("Target totals:")
            print(json.dumps(metadata["target_totals"], indent=2, ensure_ascii=False))

    print("Selected episodes:")
    for episode in episodes:
        print(
            f"  {episode.episode_task_id} | {episode.domain_group:10} | {episode.app_category:22} | "
            f"{episode.app_name:25} | steps={episode.step_count} | decision_pool={episode.decision_screen_count} | "
            f"sampled={len(episode.selected_decision_screen_ids)}"
        )

    print("\nPer-category counts:")
    for category_name in sorted(by_category):
        apps = unique_preserve_order(episode.app_name for episode in by_category[category_name])
        tasks = len(by_category[category_name])
        steps = sum(episode.step_count for episode in by_category[category_name])
        sampled_screens = sum(len(episode.selected_decision_screen_ids) for episode in by_category[category_name])
        print(
            f"  {category_name:22} | apps={len(apps)} | tasks={tasks} | "
            f"replay_screens={steps} | decision_screens={sampled_screens}"
        )


def print_screen_manifest_summary(manifest_path: Path) -> None:
    payload = load_manifest_payload(manifest_path)
    screens = load_screen_manifest(manifest_path)
    by_category: Dict[str, List[ScreenSelection]] = defaultdict(list)
    for screen in screens:
        by_category[screen.app_category].append(screen)

    print(f"Manifest: {manifest_path}")
    print(f"Manifest type: {payload.get('manifest_type', 'screen_benchmark')}")
    print(f"Benchmark line: {payload.get('benchmark_line', 'unspecified')}")
    print(f"Total screens: {len(screens)}")
    if payload.get("metadata"):
        print(f"Scanned matching episodes: {payload['metadata'].get('scanned_matching_episodes')}")
    print("Selected screens:")
    for screen in screens:
        print(
            f"  {screen.screen_id} | {screen.domain_group:10} | {screen.app_category:22} | "
            f"{screen.app_name:25} | decision={str(screen.is_decision_screen):5} | options={screen.option_count}"
        )

    print("\nPer-category counts:")
    for category_name in sorted(by_category):
        apps = unique_preserve_order(screen.app_name for screen in by_category[category_name])
        tasks = unique_preserve_order(screen.episode_task_id for screen in by_category[category_name])
        print(
            f"  {category_name:22} | screens={len(by_category[category_name])} | "
            f"apps={len(apps)} | tasks={len(tasks)}"
        )

    print("\nAPI call estimate:")
    print(json.dumps(estimate_api_calls(len(screens)), indent=2))


def print_manifest_summary(manifest_path: Path) -> None:
    payload = load_manifest_payload(manifest_path)
    if payload.get("manifest_type") == "episode_benchmark" or "episodes" in payload:
        print_episode_manifest_summary(manifest_path)
        return
    print_screen_manifest_summary(manifest_path)


def print_benchmark_bundle_summary(
    episode_manifest_path: Path,
    decision_screen_manifest_path: Path,
    episode_replay_manifest_path: Path,
) -> None:
    print_episode_manifest_summary(episode_manifest_path)
    print()
    print_screen_manifest_summary(decision_screen_manifest_path)
    print()
    print_screen_manifest_summary(episode_replay_manifest_path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AndroidControl evaluation pipeline for FocalFlow.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect mapped apps and an example adapted tree.")
    inspect_parser.add_argument("--split", default="test", help="Dataset split to inspect.")
    inspect_parser.add_argument(
        "--test-subsplit",
        default=None,
        help="Optional test subsplit: IDD, category_unseen, app_unseen, or task_unseen.",
    )
    inspect_parser.add_argument("--max-episodes", type=int, default=100, help="Max matching episodes to scan.")

    sample_parser = subparsers.add_parser(
        "sample",
        help="Select benchmark episodes, cache all task steps, and emit both decision-screen and replay manifests.",
    )
    sample_parser.add_argument("--split", default="test", help="Dataset split to sample from.")
    sample_parser.add_argument(
        "--test-subsplit",
        default=None,
        help="Optional test subsplit: IDD, category_unseen, app_unseen, or task_unseen.",
    )
    sample_parser.add_argument(
        "--max-episodes",
        type=int,
        default=2000,
        help="Max matching episodes to scan before stopping, even if quotas are not yet filled.",
    )
    sample_parser.add_argument(
        "--episode-manifest-path",
        type=Path,
        default=DEFAULT_EPISODE_MANIFEST_PATH,
        help="Path to write the hierarchical selected episode manifest JSON.",
    )
    sample_parser.add_argument(
        "--decision-screen-manifest-path",
        type=Path,
        default=DEFAULT_DECISION_SCREEN_MANIFEST_PATH,
        help="Path to write the decision-screen benchmark manifest JSON.",
    )
    sample_parser.add_argument(
        "--episode-replay-manifest-path",
        type=Path,
        default=DEFAULT_EPISODE_REPLAY_MANIFEST_PATH,
        help="Path to write the full episode-replay screen manifest JSON.",
    )

    summary_parser = subparsers.add_parser("summary", help="Summarize a previously created manifest.")
    summary_parser.add_argument(
        "--manifest-path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Manifest path to summarize.",
    )

    summary_bundle_parser = subparsers.add_parser(
        "summary-benchmarks",
        help="Summarize the episode manifest plus both screen-level benchmark manifests together.",
    )
    summary_bundle_parser.add_argument(
        "--episode-manifest-path",
        type=Path,
        default=DEFAULT_EPISODE_MANIFEST_PATH,
        help="Episode manifest path to summarize.",
    )
    summary_bundle_parser.add_argument(
        "--decision-screen-manifest-path",
        type=Path,
        default=DEFAULT_DECISION_SCREEN_MANIFEST_PATH,
        help="Decision-screen manifest path to summarize.",
    )
    summary_bundle_parser.add_argument(
        "--episode-replay-manifest-path",
        type=Path,
        default=DEFAULT_EPISODE_REPLAY_MANIFEST_PATH,
        help="Episode-replay screen manifest path to summarize.",
    )

    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Run the LLM agents on a flat screen manifest. Use the decision-screen or episode-replay manifest.",
    )
    eval_parser.add_argument(
        "--manifest-path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Flat screen manifest path to evaluate.",
    )
    eval_parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory for per-screen JSON files and summary.csv.",
    )
    eval_parser.add_argument("--max-retries", type=int, default=3, help="API retry attempts.")
    eval_parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=2.0,
        help="Base backoff between failed retries.",
    )
    eval_parser.add_argument(
        "--sleep-between-calls-seconds",
        type=float,
        default=1.0,
        help="Delay between successful API calls.",
    )
    eval_parser.add_argument(
        "--run-api",
        action="store_true",
        help="Actually execute API calls. Without this flag the command only prints the call estimate.",
    )
    eval_parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip only screens whose existing JSON result is fully successful; recompute failed/partial screens and rebuild summary.csv.",
    )

    backfill_parser = subparsers.add_parser(
        "backfill-results",
        help="Add visualization artifacts and researcher-facing talk answers to existing result JSON files.",
    )
    backfill_parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing per-screen JSON files to backfill.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    if args.command == "inspect":
        inspect_dataset(args.split, args.test_subsplit, args.max_episodes)
        return 0
    if args.command == "sample":
        select_benchmarks_from_dataset(
            split_name=args.split,
            test_subsplit=args.test_subsplit,
            max_episodes=args.max_episodes,
            episode_manifest_path=args.episode_manifest_path,
            decision_screen_manifest_path=args.decision_screen_manifest_path,
            episode_replay_manifest_path=args.episode_replay_manifest_path,
        )
        print_benchmark_bundle_summary(
            args.episode_manifest_path,
            args.decision_screen_manifest_path,
            args.episode_replay_manifest_path,
        )
        return 0
    if args.command == "summary":
        print_manifest_summary(args.manifest_path)
        return 0
    if args.command == "summary-benchmarks":
        print_benchmark_bundle_summary(
            args.episode_manifest_path,
            args.decision_screen_manifest_path,
            args.episode_replay_manifest_path,
        )
        return 0
    if args.command == "evaluate":
        evaluate_manifest(
            manifest_path=args.manifest_path,
            results_dir=args.results_dir,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            sleep_between_calls_seconds=args.sleep_between_calls_seconds,
            run_api=args.run_api,
            resume_existing=args.resume,
        )
        return 0
    if args.command == "backfill-results":
        backfill_results(args.results_dir)
        return 0
    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
