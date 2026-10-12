#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EPISODE_MANIFEST_PATH = REPO_ROOT / "evaluation" / "selected_episodes.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "results" / "episode_replay_line"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expand a dataset screen or episode ID into the full AndroidControl task trace, "
            "including step instructions, cached screenshots/UI trees, and local result artifacts."
        )
    )
    parser.add_argument(
        "identifier",
        help="Either a screen ID like ac_ep00140_obs01 or an episode ID like ac_ep00140.",
    )
    parser.add_argument(
        "--episode-manifest-path",
        type=Path,
        default=DEFAULT_EPISODE_MANIFEST_PATH,
        help="Path to the hierarchical episode manifest JSON.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing per-screen result JSON files and visualizations.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path to write the output. Defaults to stdout.",
    )
    return parser.parse_args()


def format_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def load_episode_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError(f"Manifest {manifest_path} does not contain an 'episodes' list.")
    return episodes


def find_episode(
    episodes: List[Dict[str, Any]], identifier: str
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    for episode in episodes:
        if episode.get("episode_task_id") == identifier:
            return episode, None
        for step in episode.get("steps", []):
            if step.get("screen_id") == identifier:
                return episode, step
    raise ValueError(f"Could not find screen/episode identifier: {identifier}")


def build_step_payload(
    step: Dict[str, Any],
    anchor_screen_id: Optional[str],
    selected_decision_screen_ids: List[str],
    results_dir: Path,
) -> Dict[str, Any]:
    screenshot_path = Path(step["screenshot_path"])
    ui_tree_path = Path(step["ui_tree_path"])
    result_json_path = results_dir / f"{step['screen_id']}.json"
    visualization_dir = results_dir / "visualizations" / step["screen_id"]
    visualization_paths = sorted(
        str(path.resolve())
        for path in visualization_dir.glob("*")
        if path.is_file()
    )

    payload: Dict[str, Any] = {
        "screen_id": step["screen_id"],
        "observation_index": step["observation_index"],
        "is_anchor_screen": step["screen_id"] == anchor_screen_id,
        "is_selected_decision_screen": step["screen_id"] in selected_decision_screen_ids,
        "is_decision_screen": step.get("is_decision_screen", True),
        "decision_reason": step.get("decision_reason", "accepted"),
        "current_step_instruction": step.get("current_step_instruction", ""),
        "action_history": step.get("action_history", []),
        "completed_subtasks": step.get("completed_subtasks", []),
        "current_action_json": step.get("current_action_json"),
        "option_count": step.get("option_count", 0),
        "option_labels": step.get("option_labels", []),
        "screenshot_path": str(screenshot_path.resolve()),
        "ui_tree_path": str(ui_tree_path.resolve()),
        "result_json_path": str(result_json_path.resolve()) if result_json_path.exists() else None,
        "visualization_dir": str(visualization_dir.resolve()) if visualization_dir.exists() else None,
        "visualization_paths": visualization_paths,
    }
    return payload


def build_trace_payload(
    episode: Dict[str, Any], anchor_step: Optional[Dict[str, Any]], results_dir: Path
) -> Dict[str, Any]:
    selected_decision_screen_ids = list(episode.get("selected_decision_screen_ids", []))
    anchor_screen_id = anchor_step["screen_id"] if anchor_step else None
    episode_steps_in_order = [
        build_step_payload(
            step=step,
            anchor_screen_id=anchor_screen_id,
            selected_decision_screen_ids=selected_decision_screen_ids,
            results_dir=results_dir,
        )
        for step in episode.get("steps", [])
    ]
    steps = episode_steps_in_order
    anchor_step_details: Optional[Dict[str, Any]] = None
    if anchor_screen_id:
        anchor_index = next(
            (index for index, step in enumerate(episode_steps_in_order) if step["screen_id"] == anchor_screen_id),
            None,
        )
        if anchor_index is not None:
            steps = episode_steps_in_order[anchor_index:] + episode_steps_in_order[:anchor_index]
            anchor_step_details = episode_steps_in_order[anchor_index]

    return {
        "query": {
            "identifier": anchor_screen_id or episode["episode_task_id"],
            "query_type": "screen_id" if anchor_screen_id else "episode_task_id",
        },
        "episode": {
            "episode_task_id": episode["episode_task_id"],
            "episode_id": episode["episode_id"],
            "app_name": episode["app_name"],
            "app_package": episode["app_package"],
            "app_category": episode["app_category"],
            "domain_group": episode["domain_group"],
            "window_title": episode["window_title"],
            "task_objective": episode["task_objective"],
            "shard_url": episode["shard_url"],
            "step_count": episode["step_count"],
            "decision_screen_count": episode["decision_screen_count"],
            "selected_decision_screen_ids": selected_decision_screen_ids,
        },
        "anchor_step": dict(anchor_step) if anchor_step else None,
        "anchor_step_details": anchor_step_details,
        "steps": steps,
        "episode_steps_in_order": episode_steps_in_order,
    }


def render_text(trace: Dict[str, Any]) -> str:
    episode = trace["episode"]
    anchor_step = trace["anchor_step"]
    anchor_step_details = trace.get("anchor_step_details")
    lines = [
        f"Identifier: {trace['query']['identifier']} ({trace['query']['query_type']})",
        f"Episode: {episode['episode_task_id']} (episode_id={episode['episode_id']})",
        f"App: {episode['app_name']} [{episode['app_category']} / {episode['domain_group']}]",
        f"Window: {episode['window_title']}",
        f"Task Objective: {episode['task_objective']}",
        f"Step Count: {episode['step_count']}",
        f"Decision Screens: {episode['decision_screen_count']}",
        f"Selected Decision Screen IDs: {', '.join(episode['selected_decision_screen_ids']) or 'None'}",
    ]
    if anchor_step:
        lines.append(
            "Anchor Step: "
            f"{anchor_step['screen_id']} | obs={anchor_step['observation_index']} | "
            f"instruction={anchor_step['current_step_instruction']}"
        )
    if anchor_step_details:
        lines.append(
            "Trace Order: anchor-first "
            f"(starts from obs{anchor_step_details['observation_index']:02d} for screen_id queries)"
        )
    else:
        lines.append("Trace Order: chronological")

    lines.append("")
    lines.append("Trace:")
    for step in trace["steps"]:
        marker_parts: List[str] = []
        if step["is_anchor_screen"]:
            marker_parts.append("anchor")
        if step["is_selected_decision_screen"]:
            marker_parts.append("selected_decision")
        if step["is_decision_screen"] and not step["is_selected_decision_screen"]:
            marker_parts.append("decision")
        marker = f" [{' | '.join(marker_parts)}]" if marker_parts else ""
        lines.append(
            f"- obs{step['observation_index']:02d} {step['screen_id']}{marker}: "
            f"{step['current_step_instruction']}"
        )
        lines.append(f"  screenshot: {format_path(Path(step['screenshot_path']))}")
        lines.append(f"  ui_tree: {format_path(Path(step['ui_tree_path']))}")
        action_json = json.dumps(step["current_action_json"], ensure_ascii=False)
        lines.append(f"  action: {action_json}")
        if step["result_json_path"]:
            lines.append(f"  result_json: {format_path(Path(step['result_json_path']))}")
        if step["visualization_dir"]:
            lines.append(f"  visualizations: {format_path(Path(step['visualization_dir']))}")
        if step["option_labels"]:
            preview = "; ".join(step["option_labels"][:5])
            if len(step["option_labels"]) > 5:
                preview += f" ... (+{len(step['option_labels']) - 5} more)"
            lines.append(f"  options: {preview}")
    return "\n".join(lines)


def emit_output(content: str, output_path: Optional[Path]) -> None:
    if output_path:
        output_path.write_text(content, encoding="utf-8")
        print(output_path.resolve())
        return
    print(content)


def main() -> int:
    args = parse_args()
    episodes = load_episode_manifest(args.episode_manifest_path.resolve())
    episode, anchor_step = find_episode(episodes, args.identifier)
    trace = build_trace_payload(episode=episode, anchor_step=anchor_step, results_dir=args.results_dir.resolve())

    if args.format == "json":
        content = json.dumps(trace, ensure_ascii=False, indent=2)
    else:
        content = render_text(trace)
    emit_output(content, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
