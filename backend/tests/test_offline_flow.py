"""Synthetic integration checks; the example must execute real production code."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OfflineFlowTests(unittest.TestCase):
    def demo(self):
        try:
            return importlib.import_module('examples.offline_demo')
        except ModuleNotFoundError as exc:
            self.fail('The real-production offline demo entry is missing: ' + exc.name)

    def run_demo(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.demo().run_demo(**kwargs)

    def test_real_entry_parses_selects_and_sends_actual_nodes(self):
        # Removing a transition, parser, VAT rewrite or send must fail this check.
        result = self.run_demo()
        self.demo().verify_outcome(result)
        self.assertEqual(result['leaving_states'], ['waiting', 'subtask', 'decision'])
        self.assertEqual(result['agent'].subtask, 'Open the sample item.')
        self.assertEqual(result['agent'].curScreenIntro, 'A fictional sample shelf.')
        self.assertEqual(result['agent'].relevantAreaList, ['element-card'])
        self.assertEqual(result['agent'].all_classified_info['categories']['说明'],
                         {'element-hint': {'text': 'A fictional note'}})
        self.assertEqual(result['calls'],
                         ['acquire', 'planning', 'tts', 'decision', 'classification', 'beep'])
        actual_card = result['agent'].ui_layout_info_original['children']['element-card']
        self.assertIs(result['agent'].relevantAreaAllInfoList['element-card'], actual_card)
        self.assertEqual(result['external_calls'], [])
        self.assertFalse(Path(result['agent'].screenshot_file).exists())
        self.assertFalse(Path(result['agent'].ui_layout_info_original_path).exists())

    def test_corrupt_action_mapping_is_rejected_by_production(self):
        # The same Step04 mutation must now fail closed at production validation.
        responses = self.demo().load_responses()
        responses['classification'] = responses['classification'].replace(
            '"action_point": "element-open"', '"action_point": "missing-element"')
        result = self.run_demo(responses=responses)
        self.assertEqual(result['agent'].state, 'waiting')
        self.assertIsNone(result['agent'].target_element)
        self.assertIn('error', json.loads(result['sent'][0]))
        self.assertNotIn('payload', json.loads(result['sent'][0]))
        with self.assertRaisesRegex(AssertionError, 'production returned an error'):
            self.demo().verify_outcome(result)

    def test_corrupt_virtual_id_is_rejected_by_production(self):
        tree = self.demo().load_tree()
        tree['children']['element-card']['children']['element-open']['virtualNodeId'] = 'broken-reference'
        result = self.run_demo(tree=tree)
        self.assertEqual(result['calls'], ['acquire'])
        self.assertIn('error', json.loads(result['sent'][0]))
        self.assertNotIn('payload', json.loads(result['sent'][0]))
        with self.assertRaisesRegex(AssertionError, 'production returned an error'):
            self.demo().verify_outcome(result)

    def test_fixed_talk_response_adds_the_actual_hint_node(self):
        result = self.run_demo(include_talk=True)
        self.demo().verify_outcome(result)
        self.assertEqual(result['leaving_states'],
                         ['waiting', 'subtask', 'decision', 'waiting', 'talk'])
        self.assertEqual(set(result['agent'].target_element),
                         {'element-open', 'element-title', 'element-hint'})

    def test_fresh_cli_without_credentials_or_historical_file_access(self):
        # Audit only access metadata; never read old files to compare their contents.
        script = r'''
import os, pathlib, runpy, sys
root = pathlib.Path(sys.argv[1]).resolve()
violations = []
def audit(event, args):
    if event != 'open' or not isinstance(args[0], (str, bytes)):
        return
    path = pathlib.Path(os.fsdecode(args[0])).resolve()
    in_repo = root == path or root in path.parents
    # The integrated source may itself live below the historical parent.
    # Only this exact checkout is admitted by the source/fixture allowlist.
    historical = not in_repo and '/[02] FocalFlow/[13] Code/' in str(path)
    mode, flags = args[1:3]
    writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
        isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
    source = False
    if in_repo:
        source = path.suffix in {'.py', '.pyc'} and (
            path.parent in {root, root / '__pycache__'} or
            path.relative_to(root).parts[0] in {'MobileAgent', 'examples'})
    fixture = in_repo and path.parent == root / 'examples' / 'fixtures'
    if historical or (in_repo and (writing or not (source or fixture))):
        violations.append('historical or unexpected repository file access')
        raise BaseException(violations[-1])
sys.addaudithook(audit)
runpy.run_module('examples.offline_demo', run_name='__main__')
assert violations == []
assert not any(k.startswith('FOCALFLOW_') or 'API_KEY' in k or 'API_TOKEN' in k for k in os.environ)
print('fresh process: credentials=0; historical_file_access=0; repository_writes=0')
'''
        env = {'PATH': os.defpath, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', script, str(ROOT)],
                                    cwd=directory, env=env, capture_output=True,
                                    text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fixed model responses', result.stdout)
        self.assertIn('external_calls=0', result.stdout)
        self.assertIn('historical_file_access=0; repository_writes=0', result.stdout)


if __name__ == '__main__':
    unittest.main()
