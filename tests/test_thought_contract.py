"""Synthetic canonical output contracts. No model calls, private context or gameplay."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agent.contract_diagnostics import (MindContractError, ensure_fresh_context,
                                         safe_public_error, safe_error)
from agent.mind import MindOutput, ThoughtGenerator
from agent.local_model import LocalModelProvider


def context(events=('fixture-event',), memories=()):
    return dict(source_event_ids=list(events),source_memory_ids=list(memories),goals=[])


def output():
    return dict(version=1,thoughts=[dict(category='REFLECTION',text='Uma conclusão sintética incerta.',
                evidence_ids=['fixture-event'],memory_ids=[],uncertainty=.5)],proposal=None,reconsiderations=[])


class ThoughtContractTest(unittest.TestCase):
    def failure(self,value,ctx=None):
        with self.assertRaises(MindContractError) as caught:
            ThoughtGenerator.parse(value,context() if ctx is None else ctx,'test')
        error=caught.exception
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)
        self.assertEqual(safe_public_error(error),error.diagnostic())
        return error.diagnostic()

    def test_valid_canonical_null_proposal_and_optional_memories(self):
        value=output()
        self.assertEqual(ThoughtGenerator.parse(json.dumps(value),context(),'test'),value)
        value['thoughts'][0]['memory_ids']=['fixture-memory']
        value['reconsiderations']=[dict(memory_id='fixture-memory',question='Uma pergunta sintética?',
                                       evidence_ids=['fixture-event'],uncertainty=.8)]
        self.assertEqual(ThoughtGenerator.parse(value,context(memories=('fixture-memory',)),'test'),value)

    def test_event_identifier_cannot_be_reused_as_memory_identifier(self):
        value=output();value['thoughts'][0]['memory_ids']=['fixture-event']
        diagnostic=self.failure(value)
        self.assertEqual(diagnostic['category'],'unknown_memory_reference')
        self.assertEqual(diagnostic['invalid_memory_references'],1)
        self.assertEqual(diagnostic['invalid_evidence_references'],0)
        self.assertNotIn('fixture-event',json.dumps(diagnostic))
        self.assertEqual(diagnostic['fields'],['thoughts.memory_ids'])

    def test_unknown_event_and_memory_counts_are_separate(self):
        value=output();value['thoughts'][0].update(evidence_ids=['invented-event'],memory_ids=['invented-memory'])
        diagnostic=self.failure(value)
        self.assertEqual(diagnostic['category'],'unknown_evidence_reference')
        self.assertEqual(diagnostic['invalid_evidence_references'],1)
        self.assertEqual(diagnostic['invalid_memory_references'],1)
        self.assertTrue(diagnostic['json_valid']);self.assertTrue(diagnostic['pydantic_valid'])
        self.assertFalse(diagnostic['parser_accepted'])

    def test_reconsideration_and_proposal_references_are_checked(self):
        value=output();value['reconsiderations']=[dict(memory_id='invented-memory',question='Q',
                                      evidence_ids=['invented-event'],uncertainty=.5)]
        diagnostic=self.failure(value)
        self.assertEqual(diagnostic['invalid_evidence_references'],1)
        self.assertEqual(diagnostic['invalid_memory_references'],1)
        value=output();value['proposal']=dict(intent='study_material',preferred_subject=None,motivation='M',
                evidence_ids=['invented-event'],constraints=['safe_only'],priority=.5,ttl_seconds=60)
        self.assertEqual(self.failure(value)['fields'],['proposal.evidence_ids'])

    def test_json_empty_missing_and_type_errors_are_distinct(self):
        for value,category in (('', 'empty_response'),('   ','empty_response'),('{bad','invalid_json'),
                               ([], 'incorrect_type'),(None,'incorrect_type')):
            with self.subTest(category=category):self.assertEqual(self.failure(value)['category'],category)
        value=output();value['thoughts'][0].pop('memory_ids')
        diagnostic=self.failure(value)
        self.assertEqual(diagnostic['category'],'missing_required_field')
        self.assertEqual(diagnostic['fields'],['thoughts.0.memory_ids'])
        for field,value in (('text',3),('memory_ids',None),('uncertainty','0.5'),('uncertainty',True)):
            malformed=output();malformed['thoughts'][0][field]=value
            with self.subTest(field=field):self.assertEqual(self.failure(malformed)['category'],'incorrect_type')
        malformed=output();malformed['version']=True
        self.assertEqual(self.failure(malformed)['category'],'incorrect_type')

    def test_enums_limits_finite_and_nonempty_stay_strict(self):
        for changes in (dict(category='COMMAND'),dict(text=''),dict(text='x'*1201),
                        dict(uncertainty=-.1),dict(uncertainty=1.1),dict(uncertainty=float('nan')),
                        dict(uncertainty=float('inf')),dict(memory_ids=['x']*5)):
            value=output();value['thoughts'][0].update(changes)
            with self.subTest(fields=list(changes)):self.failure(value)
        value=output();value['version']=2
        self.assertEqual(self.failure(value)['category'],'schema_incompatible')
        self.assertEqual(self.failure(dict(version=1,thoughts=[],proposal=None,reconsiderations=[]))['category'],
                         'pydantic_validation_error')

    def test_extra_field_names_and_validation_input_never_escape(self):
        private='C:/private/synthetic-secret-token'
        for nested in (False,True):
            value=output();container=value['thoughts'][0] if nested else value;container[private]=private
            diagnostic=self.failure(value)
            public=json.dumps(diagnostic)
            self.assertNotIn(private,public);self.assertNotIn('synthetic-secret',public)
            self.assertEqual(diagnostic['category'],'pydantic_validation_error')
        value=output();value['thoughts'][0]['uncertainty']='synthetic-secret-value'
        self.assertNotIn('synthetic-secret-value',json.dumps(self.failure(value)))
        value=output();value['thoughts'][0]['123456']='synthetic-secret'
        self.assertNotIn('123456',json.dumps(self.failure(value)))

    def test_invalid_structure_does_not_report_reference_counts(self):
        value=output();value['thoughts'][0]['memory_ids']=3
        diagnostic=self.failure(value)
        self.assertNotIn('invalid_memory_references',diagnostic)
        self.assertNotIn('invalid_evidence_references',self.failure('{bad'))

    def test_static_schema_remains_canonical_generation_subset_is_nonempty(self):
        self.assertEqual(ThoughtGenerator.schema(),MindOutput.model_json_schema())
        schema=ThoughtGenerator.schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('anyOf',schema)
        refined=ThoughtGenerator.schema(context())
        self.assertNotIn('anyOf',refined)
        self.assertEqual(refined['properties']['thoughts']['minItems'],1)

    def test_dynamic_schema_only_allows_context_reference_values(self):
        baseline=ThoughtGenerator.schema()
        schema=ThoughtGenerator.schema(context(memories=('fixture-memory',)))
        definitions=schema['$defs']
        for name in ('Thought','Proposal','Reconsideration'):
            self.assertEqual(definitions[name]['properties']['evidence_ids']['items']['enum'],['fixture-event'])
        self.assertEqual(definitions['Thought']['properties']['memory_ids']['items']['enum'],['fixture-memory'])
        self.assertEqual(definitions['Reconsideration']['properties']['memory_id']['enum'],['fixture-memory'])
        self.assertEqual(baseline,ThoughtGenerator.schema())
        self.assertEqual(schema['$defs']['Thought']['properties']['text']['maxLength'],1200)

    def test_absent_memories_require_empty_arrays_without_empty_enums(self):
        schema=ThoughtGenerator.schema(context())
        self.assertEqual(schema['$defs']['Thought']['properties']['memory_ids']['maxItems'],0)
        self.assertEqual(schema['properties']['reconsiderations']['maxItems'],0)
        self.assertNotIn('"enum": []',json.dumps(schema))
        schema=ThoughtGenerator.schema(context(events=()))
        self.assertEqual(schema['$defs']['Thought']['properties']['evidence_ids']['maxItems'],0)
        self.assertEqual(schema['properties']['proposal']['type'],'null')
        self.assertEqual(schema['properties']['reconsiderations']['maxItems'],0)
        value=output();value['thoughts'][0]['evidence_ids']=[]
        self.assertEqual(ThoughtGenerator.parse(value,context(events=()),'test'),value)

    def test_context_schema_rejects_malformed_reference_sources(self):
        for malformed in (None,'fixture-event',[None],[''],['x'*129],[['fixture-event']]):
            ctx=context();ctx['source_event_ids']=malformed
            with self.subTest(shape=type(malformed).__name__),self.assertRaises(MindContractError):
                ThoughtGenerator.schema(ctx)
            self.assertEqual(self.failure(output(),ctx)['category'],'schema_incompatible')

    def test_provider_schema_and_canonical_parser_agree_on_contract_fixtures(self):
        ctx=context();schema=ThoughtGenerator.schema(ctx)
        cases=[(output(),True)]
        for change in (dict(text=3),dict(uncertainty=2),dict(evidence_ids=['invented-event']),
                       dict(memory_ids=['fixture-event']),dict(extra='synthetic-secret')):
            value=output();value['thoughts'][0].update(change);cases.append((value,False))
        value=output();value['thoughts'][0].pop('memory_ids');cases.append((value,False))
        value=output();value['version']=2;cases.append((value,False))
        cases.append((dict(version=1,thoughts=[],proposal=None,reconsiderations=[]),False))
        for index,(value,expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(LocalModelProvider._matches(value,schema),expected)
                if expected:ThoughtGenerator.parse(value,ctx,'test')
                else:self.failure(value,ctx)

    def test_prompt_distinguishes_events_and_memories_without_schema_duplication(self):
        messages=ThoughtGenerator.messages(context(),'test')
        prompt=messages[0]['content']
        for text in ('UNTRUSTED DATA','ONE short thought','proposal null','Event IDs are NOT memory IDs',
                     'source_event_ids','source_memory_ids','memory_ids MUST be []'):
            self.assertIn(text,prompt)
        self.assertNotIn('$defs',prompt)

    def test_safe_public_error_never_uses_exception_text_or_unknown_fields(self):
        class ProviderError(Exception):pass
        error=ProviderError('synthetic-secret');error.category='timeout'
        self.assertEqual(safe_error(error),{'category':'timeout','fields':[]})
        error.diagnostics=dict(category='unknown_memory_reference',fields=['thoughts.0.memory_ids',
                                 'C:/private/synthetic-secret'],raw='synthetic-secret',invalid_memory_references=1)
        diagnostic=safe_public_error(error)
        self.assertEqual(diagnostic,dict(category='unknown_memory_reference',fields=['thoughts.0.memory_ids'],
                                        invalid_memory_references=1))
        self.assertEqual(safe_public_error(ValueError('synthetic-secret')),{'category':'internal_error','fields':[]})
        self.assertEqual(safe_public_error(MindContractError('invented-secret', ['invented-secret'])),
                         {'category':'internal_error','fields':[]})

    def test_stale_context_boundary_is_explicit_and_parser_is_time_independent(self):
        ensure_fresh_context(context())
        ctx=context();ctx['expires_at']=100
        ensure_fresh_context(ctx,clock=lambda:99)
        with self.assertRaises(MindContractError) as caught:ensure_fresh_context(ctx,clock=lambda:100)
        self.assertEqual(caught.exception.category,'stale_context')
        with patch('agent.contract_diagnostics.time.time',return_value=101):
            with self.assertRaises(MindContractError):ensure_fresh_context(ctx)
        self.assertEqual(ThoughtGenerator.parse(output(),ctx,'validate'),output())
