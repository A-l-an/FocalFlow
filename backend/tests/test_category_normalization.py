"""Exact redundant category identity compatibility; synthetic data and no services."""
import contextlib
import copy
import io
import json
import unittest
from examples import offline_demo as demo
from MobileAgent.validation import (ValidationError,categories,json_section,scoped_index,
                                   sections,tree_index)

class CategoryNormalizationTests(unittest.TestCase):
    def source(self):
        tree=demo.load_tree()
        return tree,tree_index(tree)

    def test_matching_redundant_name_returns_new_canonical_values_without_mutation(self):
        source,index=self.source()
        grouped={'Title':{'element-title':{'name':'element-title','text':' \t中🙂 e\u0301 '}},
                 'Action':{'element-open':{'text':'Open'}}}
        before=copy.deepcopy((source,grouped))
        result=categories(grouped,index)
        self.assertEqual(result,{'Title':{'element-title':{'text':' \t中🙂 e\u0301 '}},
                                 'Action':{'element-open':{'text':'Open'}}})
        self.assertEqual((source,grouped),before)
        self.assertIsNot(result,grouped)
        for label,members in grouped.items():
            self.assertIsNot(result[label],members)
            for alias,info in members.items():self.assertIsNot(result[label][alias],info)
        result['Title']['element-title']['text']='synthetic changed result'
        self.assertEqual((source,grouped),before)

    def test_name_conflict_unknown_fields_missing_text_and_types_stay_rejected(self):
        source,index=self.source()
        variants=[{'name':'element-open','text':'x'}, {'name':' element-title','text':'x'},
                  {'name':'ELEMENT-TITLE','text':'x'}, {'name':False,'text':'x'},
                  {'name':0,'text':'x'}, {'name':None,'text':'x'}, {'name':[],'text':'x'},
                  {'name':{},'text':'x'}, {'name':'element-title'}, {},
                  {'name':'element-title','text':'x','extra':None}, {'text':'x','extra':True},
                  {'name':'element-title','text':False}, {'name':'element-title','text':0},
                  {'name':'element-title','text':1.5}, {'name':'element-title','text':[]},
                  {'name':'element-title','text':{}}, 'x', [], None]
        for info in variants:
            with self.subTest(info=info):
                value={'Title':{'element-title':info}};before=copy.deepcopy((source,value))
                with self.assertRaises(ValidationError):categories(value,index)
                self.assertEqual((source,value),before)

    def test_unknown_alias_and_out_of_scope_alias_are_rejected_despite_matching_name(self):
        source,index=self.source();scope=scoped_index(index,['element-card'])
        for alias,allowed in (('unknown-element',index),('element-other',scope)):
            with self.subTest(alias=alias):
                with self.assertRaises(ValidationError):categories({'Other':{alias:{'name':alias,'text':'x'}}},allowed)
        self.assertEqual(categories({'Title':{'element-title':{'name':'element-title','text':'x'}}},scope),
                         {'Title':{'element-title':{'text':'x'}}})

    def test_native_null_rule_is_preserved_with_matching_name(self):
        source,index=self.source();node=source['children']['element-card']['children']['element-title']
        node['text']=None
        for text in (None,'','synthetic model string'):
            value={'Title':{'element-title':{'name':'element-title','text':text}}}
            self.assertEqual(categories(value,index),{'Title':{'element-title':{'text':text}}})
        for source_text in ('nonnull','',0,False,[],{}):
            node['text']=source_text
            with self.subTest(source_text=source_text),self.assertRaises(ValidationError):
                categories({'Title':{'element-title':{'name':'element-title','text':None}}},index)
        del node['text']
        with self.assertRaises(ValidationError):categories({'Title':{'element-title':{'name':'element-title','text':None}}},index)

    def test_duplicate_keys_bad_json_and_invalid_later_member_do_not_partially_normalize(self):
        for text in ('{"C":{"element-title":{"name":"element-title","name":"element-title","text":"x"}}}',
                     '{"C":{"element-title":{"name":"element-title","text":"x","text":"x"}}}',
                     '{"C":{"element-title":{"name":"element-title","text":"x"}},}'):
            with self.subTest(text=text),self.assertRaises(ValidationError):json_section(text)
        source,index=self.source()
        value={'Title':{'element-title':{'name':'element-title','text':'x'},
                        'element-open':{'name':'element-title','text':'Open'}}}
        before=copy.deepcopy((source,value))
        with self.assertRaises(ValidationError):categories(value,index)
        self.assertEqual((source,value),before)

    def test_full_synthetic_classification_and_talk_use_canonical_categories(self):
        responses=demo.load_responses()
        thought,grouped,selected=sections(responses['classification'],('Thought','Categories','SelectedUI'))
        grouped=json_section(grouped)
        for members in grouped.values():
            for alias,info in members.items():info['name']=alias
        responses['classification']='### Thought ###\n'+thought+'\n### Categories ###\n'+json.dumps(grouped)+'\n### SelectedUI ###\n'+selected
        source=demo.load_tree();before=copy.deepcopy(source)
        with contextlib.redirect_stdout(io.StringIO()):result=demo.run_demo(tree=source,responses=responses,include_talk=True)
        demo.verify_outcome(result)
        self.assertEqual(source,before)
        self.assertEqual(result['external_calls'],[])
        for members in result['agent'].all_classified_info['categories'].values():
            for info in members.values():self.assertEqual(set(info),{'text'})

if __name__=='__main__':unittest.main()
