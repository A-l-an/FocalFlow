"""Production-path validation regressions using only synthetic external responses."""
import contextlib
import copy
import io
import json
import unittest
from examples import offline_demo as demo


class OutputValidationTests(unittest.TestCase):
    def run_flow(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            result = demo.run_demo(**kwargs)
        self.assertEqual(result['external_calls'], [])
        self.assertTrue(result['fixture_unchanged'])
        return result

    def assert_rejected(self, result):
        self.assertEqual(len(result['sent']), 1)
        message = json.loads(result['sent'][0])
        self.assertIn('error', message)
        self.assertNotIn('payload', message)
        agent = result['agent']
        self.assertEqual(agent.state, 'waiting')
        self.assertIsNone(agent.current_request_id)
        self.assertIsNone(agent.target_element)
        self.assertEqual(agent.subtask_history, [])
        # The request's admitted interaction remains a fact even if acquisition
        # or a derived model result fails; only derived state is rolled back.
        self.assertEqual(agent.action_history, ['Open fictional shelf'])
        self.assertEqual(agent.subtask, '')
        self.assertFalse(getattr(agent, 'all_classified_info', None))
        self.assertFalse(getattr(agent, 'relevantAreaList', None))
        self.assertFalse(getattr(agent, 'relevantAreaAllInfoList', None))
        self.assertFalse(getattr(agent, 'ui_layout_info_focused', None))

    def test_real_tree_changes_only_real_node_flags_and_preserves_raw(self):
        source = demo.load_tree()
        source['metadata'] = {'bounds': {'fake': 1}, 'children': {'not-a-node': {}},
                              'isVirtualFocusNode': 'opaque-metadata'}
        result = self.run_flow(tree=source)
        demo.verify_outcome(result)
        self.assertEqual(result['agent'].ui_layout_info_original, source)
        candidate = json.loads(result['sent'][0])['payload']
        expected = copy.deepcopy(source)
        expected['children']['element-card']['children']['element-hint']['isVirtualFocusNode'] = False
        expected['children']['element-other']['isVirtualFocusNode'] = False
        self.assertEqual(candidate, expected)

    def test_source_null_category_reaches_ui_and_talk_without_changing_raw_values(self):
        source = demo.load_tree()
        node = source['children']['element-card']['children']['element-open']
        node['text'] = None
        node['contentDescription'] = 'Synthetic open icon'
        node['metadata'] = {'text': None, 'children': {'opaque': [False, 3]}}
        original = copy.deepcopy(source)
        responses = demo.load_responses()
        responses['classification'] = responses['classification'].replace('"text": "Open"', '"text": null')
        original_responses = copy.deepcopy(responses)
        result = self.run_flow(tree=source, responses=responses, include_talk=True)
        demo.verify_outcome(result)
        self.assertEqual(source, original)
        self.assertEqual(result['agent'].ui_layout_info_original, original)
        self.assertEqual(responses, original_responses)
        self.assertIsNone(result['agent'].all_classified_info['categories']['操作']['element-open']['text'])
        expected = copy.deepcopy(original)
        expected['children']['element-other']['isVirtualFocusNode'] = False
        for number, serialized in enumerate(result['sent']):
            expected['children']['element-card']['children']['element-hint']['isVirtualFocusNode'] = bool(number)
            self.assertEqual(json.loads(serialized)['payload'], expected)

    def test_source_null_context_reaches_ui_and_keeps_the_context_target(self):
        source = demo.load_tree()
        node = source['children']['element-card']['children']['element-title']
        node['text'] = None
        node['contentDescription'] = 'Synthetic item description'
        original = copy.deepcopy(source)
        responses = demo.load_responses()
        prefix, selected = responses['classification'].split('### SelectedUI ###')
        responses['classification'] = prefix + '### SelectedUI ###' + selected.replace('"text": "Sample item"', '"text": null')
        result = self.run_flow(tree=source, responses=responses)
        demo.verify_outcome(result)
        self.assertEqual(source, original)
        self.assertEqual(result['agent'].ui_layout_info_original, original)
        self.assertEqual(result['agent'].target_element, ['element-open', 'element-title'])
        self.assertIsNone(result['agent'].all_classified_info['topmost_ui'][0]['context_elements'][0]['text'])

    def test_nullable_text_validation_preserves_model_values_and_source(self):
        from MobileAgent.validation import categories, selections, tree_index
        for text in (None, '', ' \t\n中🙂 e\u0301 '):
            with self.subTest(text=text):
                source = demo.load_tree()
                source['children']['element-card']['children']['element-title']['text'] = text
                index = tree_index(source)
                grouped = {'Synthetic': {'element-title': {'text': text}}}
                selected = [{'action_point': 'element-open',
                             'context_elements': [{'name': 'element-title', 'text': text}]}]
                before = json.dumps([source, grouped, selected], ensure_ascii=False).encode('utf-8')
                self.assertIs(categories(grouped, index), grouped)
                self.assertEqual(selections(selected, index), ['element-open', 'element-title'])
                self.assertEqual(json.dumps([source, grouped, selected], ensure_ascii=False).encode('utf-8'), before)

    def test_nullable_text_does_not_coerce_types_or_accept_null_for_nonnull_source(self):
        from MobileAgent.validation import ValidationError, categories, selections, tree_index
        cases = [(None, bad) for bad in (0, 1.5, False, [], {})]
        cases += [(nonnull, None) for nonnull in ('Sample item', '', 0, False, [], {})]
        cases += [('missing', None)]
        for source_text, model_text in cases:
            with self.subTest(source_text=source_text, model_text=model_text):
                source = demo.load_tree()
                node = source['children']['element-card']['children']['element-title']
                node['text'] = source_text
                if source_text == 'missing':
                    del node['text']
                index = tree_index(source)
                with self.assertRaises(ValidationError):
                    categories({'Synthetic': {'element-title': {'text': model_text}}}, index)
                with self.assertRaises(ValidationError):
                    selections([{'action_point': 'element-open',
                                 'context_elements': [{'name': 'element-title', 'text': model_text}]}], index)

    def test_nullable_text_still_requires_known_refs_and_exact_fields(self):
        from MobileAgent.validation import ValidationError, categories, selections, tree_index
        source = demo.load_tree()
        source['children']['element-card']['children']['element-title']['text'] = None
        index = tree_index(source)
        for alias in ('missing-element', 'element-title'):
            info = {'text': None} if alias == 'missing-element' else {'text': None, 'extra': None}
            with self.subTest(alias=alias):
                with self.assertRaises(ValidationError):
                    categories({'Synthetic': {alias: info}}, index)
                with self.assertRaises(ValidationError):
                    selections([{'action_point': 'element-open',
                                 'context_elements': [dict(info, name=alias)]}], index)

    def test_unknown_selection_rolls_back_all_derived_state(self):
        responses = demo.load_responses()
        responses['classification'] = responses['classification'].replace('"action_point": "element-open"', '"action_point": "other-snapshot-node"')
        result = self.run_flow(responses=responses)
        self.assert_rejected(result)
        self.assertEqual(result['agent'].ui_layout_info_original, demo.load_tree())

    def test_model_boundaries_reject_invalid_results(self):
        original = demo.load_responses()
        variants = [
            ('planning', 'missing markers'),
            ('planning', original['planning'].replace('Open the sample item.', '')),
            ('planning', None),
            ('planning', original['planning'].replace('Use the fictional sample card.', 'x' * (64 * 1024))),
            ('planning', original['planning'].replace('Use the fictional sample card.', '中' * 22000)),
            ('planning', original['planning'] + '\n### Command ### forbidden'),
            ('decision', '### Thought ### ok ### Output ### {bad json}'),
            ('decision', '### Thought ### ok ### Output ### []'),
            ('decision', '### Thought ### ok ### Output ### ["element-card","element-card"]'),
            ('decision', '### Thought ### ok ### Output ### [1]'),
            ('decision', '### Thought ### ok ### Output ### ["bounds"]'),
            ('decision', '### Thought ### ok ### Output ### ["00000000-0000-4000-8000-000000000002"]'),
            ('decision', '### Thought ### ok ### Output ### ["other-snapshot-node"]'),
            ('classification', original['classification'].replace('"action_point"', '"command"')),
            ('classification', original['classification'].replace('"action_point": "element-open",', '"action_point": "element-open", "command": "touch /tmp/never",')),
            ('classification', original['classification'].replace('"context_elements": [', '"context_elements": false, "extra": [')),
            ('classification', original['classification'].replace('"text": "Sample item"', '"text": 5')),
            ('classification', original['classification'].replace('"标题": {', '"标题": {}, "标题": {')),
            ('classification', original['classification'].replace('"element-title": {', '"element-title": {"text":"x"}, "element-title": {')),
            ('classification', original['classification'].replace('"name": "element-title"', '"name": "element-other"')),
            ('classification', '### Thought ### ok ### Categories ### {} ### SelectedUI ### []'),
            ('classification', '### Thought ### ok ### Categories ### ' + '[' * 1500 + '0' + ']' * 1500 + ' ### SelectedUI ### []'),
        ]
        for stage, value in variants:
            with self.subTest(stage=stage, case=variants.index((stage, value))):
                responses = dict(original)
                responses[stage] = value
                self.assert_rejected(self.run_flow(responses=responses))

    def test_talk_invalid_category_does_not_partially_expand(self):
        responses = demo.load_responses()
        responses['talk'] = responses['talk'].replace('说明', '说明,unknown')
        result = self.run_flow(responses=responses, include_talk=True)
        self.assertEqual(len(result['sent']), 2)
        self.assertIn('error', json.loads(result['sent'][1]))
        self.assertNotIn('payload', json.loads(result['sent'][1]))
        self.assertEqual(set(result['agent'].target_element), {'element-open', 'element-title'})
        self.assertEqual(result['agent'].ui_layout_info_focused, json.loads(result['sent'][0])['payload'])
        self.assertEqual(result['agent'].state, 'waiting')

    def test_duplicate_uuid_or_wrong_focus_rejected_before_model(self):
        for field, value in [('virtualNodeId', 'broken-reference'), ('virtualNodeId', '00000000-0000-4000-8000-000000000001'), ('isVirtualFocusNode', 1)]:
            tree = demo.load_tree()
            tree['children']['element-card'][field] = value
            result = self.run_flow(tree=tree)
            self.assert_rejected(result)
            self.assertEqual(result['calls'], ['acquire'])

    def test_raw_tree_rejects_malformed_duplicate_keys_and_parser_depth(self):
        good = json.dumps(demo.load_tree())
        for text in ('{bad', '{}', '[]', good.replace('"className":', '"className": null, "className":', 1),
                     '[' * 1500 + '0' + ']' * 1500, ' ' * (8 * 1024 * 1024 + 1)):
            result = self.run_flow(raw_tree=text)
            self.assert_rejected(result)
            self.assertEqual(result['calls'], ['acquire'])

    def test_tree_limits_reject_oversize_deep_and_excess_nodes(self):
        variants = []
        oversized = demo.load_tree()
        oversized['metadata'] = 'x' * (8 * 1024 * 1024)
        variants.append(oversized)
        deep = demo.load_tree()
        parent = deep['children']['element-other']
        for n in range(127):
            child = {'virtualNodeId': '10000000-0000-4000-8000-%012d' % n,
                     'isVirtualFocusNode': False}
            parent['children'] = {'deep-%d' % n: child}
            parent = child
        variants.append(deep)
        many = demo.load_tree()
        for n in range(9995):
            many['children']['extra-%d' % n] = {
                'virtualNodeId': '10000000-0000-4000-8000-%012d' % n,
                'isVirtualFocusNode': False}
        variants.append(many)
        for tree in variants:
            result = self.run_flow(tree=tree)
            self.assert_rejected(result)
            self.assertEqual(result['calls'], ['acquire'])

    def test_maximum_node_depth_still_runs_valid_selection(self):
        tree = demo.load_tree()
        parent = tree['children']['element-other']
        for n in range(126):
            child = {'virtualNodeId': '10000000-0000-4000-8000-%012d' % n,
                     'isVirtualFocusNode': False}
            parent['children'] = {'deep-%d' % n: child}
            parent = child
        result = self.run_flow(tree=tree)
        demo.verify_outcome(result)
        self.assertEqual(result['agent'].ui_layout_info_original, tree)

    def test_duplicate_alias_and_wrong_children_rejected(self):
        tree = demo.load_tree()
        tree['children']['element-card']['children']['element-other'] = tree['children'].pop('element-other')
        tree['children']['element-other'] = {
            'virtualNodeId': '10000000-0000-4000-8000-000000000000', 'isVirtualFocusNode': False}
        self.assert_rejected(self.run_flow(tree=tree))
        tree = demo.load_tree()
        tree['children'] = []
        self.assert_rejected(self.run_flow(tree=tree))

    def test_duplicate_actions_contexts_and_talk_categories_rejected(self):
        responses = demo.load_responses()
        prefix, selected = responses['classification'].split('### SelectedUI ###')
        obj = {'action_point': 'element-open',
               'context_elements': [{'name': 'element-title', 'text': 'Sample item'}]}
        for selected in ([obj, obj], [dict(obj, context_elements=obj['context_elements'] * 2)]):
            changed = dict(responses, classification=prefix + '### SelectedUI ###' + json.dumps(selected))
            self.assert_rejected(self.run_flow(responses=changed))
        for talk in ('### Thought ### x ### Mode ### B ### Displayed UI ### 说明,说明',
                     '### Thought ### x ### Mode ### C ### Displayed UI ### 说明',
                     '### Thought ### x ### Mode ### B ### Displayed UI ###',
                     '### Thought ### x ### Mode ### A ### Displayed UI ### 说明'):
            result = self.run_flow(responses=dict(responses, talk=talk), include_talk=True)
            self.assertIn('error', json.loads(result['sent'][1]))
            self.assertEqual(result['agent'].target_element, ['element-open', 'element-title'])
            self.assertEqual(result['agent'].state, 'waiting')

    def test_overlapping_categories_and_context_union_remain_valid(self):
        responses = demo.load_responses()
        responses['classification'] = responses['classification'].replace(
            '"element-hint": {', '"element-title": {"text":"Sample item"}, "element-hint": {')
        responses['classification'] = responses['classification'].replace(
            '"name": "element-title",', '"name": "element-open",')
        result = self.run_flow(responses=responses, include_talk=True)
        self.assertNotIn('error', json.loads(result['sent'][0]))
        self.assertEqual(json.loads(result['sent'][0])['payload']['children']['element-card']['children']['element-open']['isVirtualFocusNode'], True)
        self.assertEqual(set(result['agent'].target_element), {'element-open', 'element-title', 'element-hint'})
        self.assertEqual(result['agent'].ui_layout_info_original, demo.load_tree())

    def test_empty_selection_on_root_only_snapshot_rejected_without_focus_guess(self):
        for initial_focus in (True, False):
            tree = demo.load_tree()
            tree.pop('children')
            tree['isVirtualFocusNode'] = initial_focus
            responses = demo.load_responses()
            responses['decision'] = '### Thought ### x ### Output ### []'
            result = self.run_flow(tree=tree, responses=responses)
            self.assert_rejected(result)
            self.assertEqual(result['agent'].ui_layout_info_original, tree)

    def test_live_acquisition_uses_argv_even_for_adb_path_with_spaces(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from MobileAgent import controller
        commands = []
        def run(command, **kwargs):
            commands.append((command, kwargs))
            return SimpleNamespace(returncode=1, stdout='', stderr='')
        with patch.object(controller.subprocess, 'run', run):
            with self.assertRaises(RuntimeError):
                controller.get_screenshot_and_ui_elements('/synthetic path/adb', 'user', 'task', 1, expected_context=demo.CONTEXT)
        self.assertIsInstance(commands[0][0], list)
        self.assertEqual(commands[0][0][0], '/synthetic path/adb')
        self.assertFalse(commands[0][1].get('shell', False))

    def test_role_path_or_shell_parameters_do_not_replace_identifiers(self):
        from run import MobileAgentStateMachine, UIListener
        with demo.offline_boundaries(), contextlib.redirect_stdout(io.StringIO()):
            listener = UIListener(MobileAgentStateMachine(), send=lambda frame: None)
            listener._process_message(json.dumps(demo.message('ROLE', ctx=dict(demo.CONTEXT, snapshotSeq=0), PID='user_1', TaskID='2_4')))
            for value in ('../outside', 'name;command', '$(command)', ['invalid']):
                listener._process_message(json.dumps(demo.message('ROLE', ctx=dict(demo.CONTEXT, taskEpoch=2, snapshotSeq=0), PID='new', TaskID=value)))
                self.assertEqual((listener.current_user_id, listener.current_task_id), ('user_1', '2_4'))

    def test_failed_next_capture_preserves_prior_derived_state_and_blocks_stale_talk(self):
        from pathlib import Path
        import tempfile
        result = self.run_flow()
        agent = result['agent']
        listener = agent.ui_listener
        previous = agent.request_checkpoint()
        tree = demo.load_tree()
        card = tree['children']['element-card']['children']
        card['new-snapshot-open'] = card.pop('element-open')
        with demo.offline_boundaries(), tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            image_path = Path(directory) / 'image.png'
            image_path.write_bytes((demo.FIXTURES / 'synthetic.png').read_bytes())
            tree_path = Path(directory) / 'tree.json'
            tree_path.write_text(demo.snapshot_text(json.dumps(tree)), encoding='utf-8')
            listener.acquire = lambda *args, **kwargs: (str(image_path), str(tree_path))
            responses = demo.load_responses()
            outputs = iter(responses[key] for key in ('planning', 'decision', 'classification'))
            agent.chat = lambda *args: next(outputs)
            listener._process_message(json.dumps(demo.message('REQUEST_UI_UPDATE', 'next-capture', interaction={'text': 'second action'})))
            self.assertIn('error', json.loads(result['sent'][-1]))
            self.assertNotIn('payload', json.loads(result['sent'][-1]))
            self.assertEqual(agent.request_checkpoint(), previous)
            self.assertEqual(agent.action_history, ['Open fictional shelf', 'second action'])
            self.assertEqual(agent.ui_layout_info_original, tree)
            self.assertIsNot(agent.classification_source, agent.ui_layout_info_original)
            listener._process_message(json.dumps(demo.message('REQUEST_TALK', 'late-talk', baseRequestId=demo.REQUEST_ID)))
            self.assertEqual(json.loads(result['sent'][-1])['error'], 'INVALID_BASE_OR_BUSY')
            self.assertEqual(agent.request_checkpoint(), previous)
            self.assertEqual(agent.state, 'waiting')

    def test_ten_thousand_nodes_are_within_the_initial_limit(self):
        tree = demo.load_tree()
        for n in range(9994):
            tree['children']['extra-%d' % n] = {
                'virtualNodeId': '10000000-0000-4000-8000-%012d' % n,
                'isVirtualFocusNode': False}
        result = self.run_flow(tree=tree)
        demo.verify_outcome(result)

    def test_talk_mode_a_keeps_focus_without_claiming_back_action(self):
        responses = demo.load_responses()
        responses['talk'] = '### Thought ### Go back ### Mode ### A ### Displayed UI ###'
        result = self.run_flow(responses=responses, include_talk=True)
        self.assertEqual(len(result['sent']), 2)
        self.assertEqual(json.loads(result['sent'][1])['status'], 'NO_OP')
        self.assertNotIn('payload', json.loads(result['sent'][1]))
        self.assertEqual(result['agent'].target_element, ['element-open', 'element-title'])
        self.assertEqual(result['agent'].state, 'waiting')


if __name__ == '__main__':
    unittest.main()
