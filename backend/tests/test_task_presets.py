"""Real fixed-stage prompt parity and per-agent preset ownership (no providers)."""
import contextlib
import copy
from dataclasses import FrozenInstanceError
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run as runtime
from examples import offline_demo as demo


def make_agent(module=runtime, **kwargs):
    calls, replies = [], []
    responses = demo.load_responses()
    stages = iter(('planning', 'decision', 'classification', 'talk'))
    def chat(messages, model):
        stage = next(stages)
        calls.append({'stage': stage, 'model': model, 'messages': copy.deepcopy(messages)})
        return responses[stage]
    agent = module.MobileAgentStateMachine(chat=chat, tts=lambda text: None,
        voice=lambda *args: 'Show the notes.', beep=lambda: None, **kwargs)
    agent.ui_layout_info_original = demo.load_tree()
    agent.screenshot_file = str(demo.FIXTURES / 'synthetic.png')
    owner = module.UIListener(agent, send=replies.append)
    agent.guard = module.Work(owner, demo.message("REQUEST_UI_UPDATE"), owner._connection, None)
    owner._active = agent.guard
    agent.ui_listener = SimpleNamespace(reply=replies.append)
    return agent, calls, replies


def drive(agent):
    with demo.offline_boundaries(), contextlib.redirect_stdout(io.StringIO()):
        agent.receive_normal()
        agent.receive_change()


class TaskPresetTests(unittest.TestCase):
    def expected(self, name):
        return json.loads((Path(__file__).parent / 'fixtures/task_preset_prompts.json').read_text())[name]

    def test_legacy_selection_at_construction_uses_one_coherent_preset(self):
        # Before the fix, flipping this after import selects burger everywhere except Planning.
        with patch.object(runtime, 'flag_burger', 1):
            agent, calls, replies = make_agent()
            drive(agent)
        self.assertEqual(calls, self.expected('burger'))
        self.assertEqual(agent.state, 'waiting')
        self.assertEqual(len(replies), 2)

    def test_later_legacy_flag_change_cannot_change_existing_agent(self):
        with patch.object(runtime, 'flag_burger', 0):
            agent, calls, _ = make_agent()
        with patch.object(runtime, 'flag_burger', 1):
            drive(agent)
        self.assertEqual(calls, self.expected('hospital'))

    def test_default_preserves_complete_expected_prompts_and_models(self):
        self.assertEqual(runtime.flag_burger, 0)
        agent, calls, _ = make_agent()
        drive(agent)
        self.assertEqual(calls, self.expected('hospital'))

    def test_explicit_presets_are_isolated_for_two_simultaneous_agents(self):
        from MobileAgent.task_presets import BURGER_PRESET, HOSPITAL_PRESET
        hospital, hc, _ = make_agent(task_preset=HOSPITAL_PRESET)
        burger, bc, _ = make_agent(task_preset=BURGER_PRESET)
        with patch.object(runtime, 'flag_burger', 1):
            drive(hospital)
        with patch.object(runtime, 'flag_burger', 0):
            drive(burger)
        self.assertEqual(hc, self.expected('hospital'))
        self.assertEqual(bc, self.expected('burger'))

    def test_custom_preset_reaches_each_existing_stage_without_stage_edits(self):
        from MobileAgent.task_presets import TaskPreset
        preset = TaskPreset('synthetic goal', 'synthetic planning hint',
                            'synthetic decision hint', 'synthetic classification hint')
        agent, calls, _ = make_agent(task_preset=preset)
        drive(agent)
        for index, hint in enumerate((preset.planning_hint, preset.decision_hint, preset.classification_hint)):
            with self.subTest(stage=calls[index]['stage']):
                prompt = calls[index]['messages'][-1][1][0]['text']
                self.assertIn(preset.instruction, prompt)
                self.assertIn(hint, prompt)
                for other in (preset.planning_hint, preset.decision_hint, preset.classification_hint):
                    if other != hint: self.assertNotIn(other, prompt)
        self.assertEqual(agent.state, 'waiting')
        with self.assertRaises(FrozenInstanceError):
            preset.planning_hint = 'changed'


if __name__ == '__main__':
    unittest.main()
