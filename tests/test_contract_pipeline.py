"""HTTP fixtures through the real provider, canonical parser and benchmark; no inference/gameplay."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
from unittest.mock import patch

import httpx

from agent.contract_diagnostics import MindContractError, safe_public_error
from agent.cognitive_scheduler import CognitiveScheduler
from agent.local_model import LocalModelProvider
from agent.mind import ThoughtGenerator
from scripts import benchmark_mind as bench


MODEL='qwen3.5:0.8b'
PRIVATE='synthetic-private-token-C:/private/response'
CONFIG=dict(provider='ollama',model=MODEL,num_ctx=4096,max_output_tokens=384,
            num_thread=4,timeout_seconds=60,temperature=.2,num_gpu=0,keep_alive='2m')


def output():
    return dict(version=1,thoughts=[dict(category='REFLECTION',text='Uma conclusão sintética incerta.',
                evidence_ids=['fixture-event'],memory_ids=[],uncertainty=.5)],proposal=None,reconsiderations=[])


class Probe:
    def snapshot(self):return dict(status='fixture',free_ram_mb=8192,cpu_percent=1)


class CanonicalGenerator:
    """Intentionally use the static schema to exercise semantic parser rejection separately."""
    @staticmethod
    def schema(context=None):return ThoughtGenerator.schema()
    messages=staticmethod(ThoughtGenerator.messages)
    parse=staticmethod(ThoughtGenerator.parse)


class FixtureHTTP:
    def __init__(self,content=None,*,status=200,wire_invalid=False):
        self.content=json.dumps(output()) if content is None else content
        self.status=status;self.wire_invalid=wire_invalid;self.calls=[]

    def __call__(self,request):
        self.calls.append(request)
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL}]})
        if request.url.path=='/api/version':return httpx.Response(200,json={'version':'fixture'})
        if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
        if request.url.path=='/api/show':return httpx.Response(200,json={'capabilities':['completion','thinking']})
        if request.url.path=='/api/chat':
            if self.status!=200:return httpx.Response(self.status,json={'error':PRIVATE})
            if self.wire_invalid:return httpx.Response(200,text=PRIVATE)
            return httpx.Response(200,json=dict(model=MODEL,message={'content':self.content},
                    done_reason='stop',eval_count=32,eval_duration=1000000000,
                    load_duration=2000000,prompt_eval_count=128))
        raise AssertionError('unexpected_fixture_endpoint')

    @property
    def inference(self):return [request for request in self.calls if request.url.path=='/api/chat']


class ContractPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def run_benchmark(self,fixture=None,*,generator=None,context=None):
        fixture=fixture or FixtureHTTP()
        with TemporaryDirectory() as directory, \
             patch.object(bench,'read_config',return_value=({'llm':CONFIG},'fixture')):
            options=dict(model=MODEL,timeout=60,root=Path(directory),process_check=lambda:'clear',
                         probe=Probe(),transport=httpx.MockTransport(fixture))
            if generator is not None:options['generator']=generator
            if context is None:
                report=await bench.benchmark(**options)
            else:
                with patch.object(bench,'synthetic_context',return_value=context):report=await bench.benchmark(**options)
            self.assertEqual(list(Path(directory).iterdir()),[])
        self.assertNotIn(PRIVATE,json.dumps(report))
        return report,fixture

    def assert_metrics(self,sample):
        self.assertEqual(sample['metrics']['eval_count'],32)
        self.assertEqual(sample['metrics']['tokens_per_second'],32)
        self.assertEqual(sample['metrics']['done_reason'],'stop')
        self.assertGreaterEqual(sample['metrics']['wall_seconds'],0)

    async def test_real_wire_schema_and_qwen_parameters_are_preserved(self):
        report,fixture=await self.run_benchmark()
        self.assertEqual(report['status'],'completed')
        self.assertEqual(len(fixture.inference),1)
        request=fixture.inference[0];body=json.loads(request.content)
        self.assertEqual(body['format'],ThoughtGenerator.schema(bench.synthetic_context()))
        self.assertEqual(body['options'],dict(num_ctx=4096,num_predict=384,num_thread=4,
                                            temperature=.2,num_gpu=0))
        self.assertEqual(body['keep_alive'],'2m');self.assertFalse(body['think']);self.assertFalse(body['stream'])
        self.assertTrue(all(value==60 for value in request.extensions['timeout'].values()))
        sample=report['samples'][0];self.assert_metrics(sample)
        self.assertTrue(sample['quality']['parser_accepted'])
        self.assertGreaterEqual(sample['quality']['accepted_thoughts'],1)
        for key in ('invalid_evidence_references','invalid_memory_references','invented_references'):
            self.assertEqual(sample['quality'][key],0)

    async def test_nested_contract_errors_are_specific_before_parser_with_metrics(self):
        cases=[]
        value=output();value['thoughts'][0].pop('memory_ids');cases.append((value,'missing_required_field'))
        for changes,category in ((dict(text=3),'incorrect_type'),(dict(category='COMMAND'),'schema_incompatible'),
                                 (dict(uncertainty=2),'schema_incompatible')):
            value=output();value['thoughts'][0].update(changes);cases.append((value,category))
        for value,category in cases:
            with self.subTest(category=category),patch.object(ThoughtGenerator,'parse',wraps=ThoughtGenerator.parse) as parse:
                report,_=await self.run_benchmark(FixtureHTTP(json.dumps(value)))
                sample=report['samples'][0]
                self.assertEqual(report['status'],'failed');self.assertEqual(sample['reason'],category)
                self.assertEqual(sample['stage'],'inference');self.assert_metrics(sample)
                parse.assert_not_called()
                self.assertIsNone(sample['quality']['invalid_memory_references'])
                self.assertIsNone(report['quality_totals']['invented_references'])

    async def test_unknown_references_are_rejected_by_dynamic_schema(self):
        for field,category in (('evidence_ids','unknown_evidence_reference'),('memory_ids','unknown_memory_reference')):
            value=output();value['thoughts'][0][field]=['invented-fixture']
            with self.subTest(field=field),patch.object(ThoughtGenerator,'parse',wraps=ThoughtGenerator.parse) as parse:
                report,_=await self.run_benchmark(FixtureHTTP(json.dumps(value)))
                sample=report['samples'][0]
                self.assertEqual(report['status'],'failed');self.assertEqual(sample['reason'],category)
                parse.assert_not_called();self.assert_metrics(sample)
                self.assertEqual(sample['quality']['reference_measurement'],'unavailable')
                self.assertIsNone(sample['quality']['invented_references'])

    async def test_parser_rejection_still_measures_unknown_event_and_memory_counts(self):
        for field,category in (('evidence_ids','unknown_evidence_reference'),('memory_ids','unknown_memory_reference')):
            value=output();value['thoughts'][0][field]=['invented-fixture']
            with self.subTest(field=field):
                report,_=await self.run_benchmark(FixtureHTTP(json.dumps(value)),generator=CanonicalGenerator())
                sample=report['samples'][0]
                self.assertEqual(report['status'],'failed');self.assertEqual(sample['stage'],'parse')
                self.assertEqual(sample['reason'],category);self.assert_metrics(sample)
                self.assertEqual(sample['quality']['reference_measurement'],'measured')
                self.assertEqual(sample['quality']['invented_references'],1)
                expected='invalid_evidence_references' if field=='evidence_ids' else 'invalid_memory_references'
                other='invalid_memory_references' if field=='evidence_ids' else 'invalid_evidence_references'
                self.assertEqual(sample['quality'][expected],1);self.assertEqual(sample['quality'][other],0)
                self.assertFalse(sample['quality']['parser_accepted'])

    async def test_bad_json_empty_wire_error_and_secret_extra_are_safe_failed(self):
        extra=output();extra['thoughts'][0][PRIVATE]=PRIVATE
        cases=[(FixtureHTTP('{'+PRIVATE),'invalid_json',True),(FixtureHTTP(''),'empty_response',True),
               (FixtureHTTP(json.dumps(extra)),'schema_incompatible',True),
               (FixtureHTTP(status=500),'server_error',False),
               (FixtureHTTP(wire_invalid=True),'malformed_response',False)]
        for fixture,category,has_metrics in cases:
            with self.subTest(category=category):
                report,_=await self.run_benchmark(fixture);sample=report['samples'][0]
                self.assertEqual(report['status'],'failed');self.assertEqual(sample['reason'],category)
                self.assertEqual(sample['quality']['reference_measurement'],'unavailable')
                self.assertIsNone(sample['quality']['invalid_evidence_references'])
                self.assertIsNone(sample['quality']['invalid_memory_references'])
                if has_metrics:self.assert_metrics(sample)
                else:self.assertNotIn('metrics',sample)

    async def test_expired_context_is_rejected_before_inference(self):
        ctx=bench.synthetic_context();ctx['expires_at']=0
        report,fixture=await self.run_benchmark(context=ctx)
        self.assertFalse(fixture.inference)
        sample=report['samples'][0]
        self.assertEqual(report['status'],'failed');self.assertEqual(sample['reason'],'stale_context')
        self.assertEqual(sample['stage'],'context')
        self.assertIsNone(report['quality_totals']['invalid_memory_references'])

    async def test_generator_runtime_and_type_errors_are_internal_without_exception_text(self):
        for failing_stage in ('schema','messages','parse'):
            for error_type in (RuntimeError,TypeError):
                class FaultGenerator:
                    def schema(self,context=None):
                        if failing_stage=='schema':raise error_type(PRIVATE)
                        return ThoughtGenerator.schema(context)
                    def messages(self,context,purpose):
                        if failing_stage=='messages':raise error_type(PRIVATE)
                        return ThoughtGenerator.messages(context,purpose)
                    def parse(self,content,context,purpose):
                        if failing_stage=='parse':raise error_type(PRIVATE)
                        return ThoughtGenerator.parse(content,context,purpose)
                with self.subTest(stage=failing_stage,error=error_type.__name__):
                    report,fixture=await self.run_benchmark(generator=FaultGenerator())
                    sample=report['samples'][0]
                    self.assertEqual(report['status'],'failed');self.assertEqual(sample['reason'],'internal_error')
                    self.assertEqual(len(fixture.inference),int(failing_stage=='parse'))

    async def test_scheduler_uses_context_schema_real_provider_and_safe_rejection(self):
        for case in ('valid','unknown_memory','stale'):
            value=output()
            if case=='unknown_memory':value['thoughts'][0]['memory_ids']=['invented-fixture']
            fixture=FixtureHTTP(json.dumps(value))
            config=CONFIG|dict(interval_seconds=0,max_retries=0,failure_cooldown_seconds=0)
            scheduler=CognitiveScheduler(config,transport=httpx.MockTransport(fixture),probe=Probe())
            ctx=bench.synthetic_context()
            ctx['scope']=dict(world=ctx['world'],dimension='minecraft:overworld',session='fixture-session',control_epoch=1)
            ctx['expires_at']=0 if case=='stale' else time.time()+60
            try:
                with self.subTest(case=case):
                    self.assertTrue(scheduler.schedule(ctx))
                    await asyncio.wait_for(scheduler.task,1)
                    if case=='stale':
                        self.assertFalse(fixture.inference);self.assertEqual(scheduler.error,'stale_context')
                    else:
                        self.assertEqual(len(fixture.inference),1)
                        self.assertEqual(json.loads(fixture.inference[0].content)['format'],ThoughtGenerator.schema(ctx))
                        if case=='valid':
                            result=scheduler.take_result()
                            self.assertGreaterEqual(len(result['output']['thoughts']),1)
                            self.assertEqual(scheduler.status,'ready')
                        else:
                            self.assertIsNone(scheduler.take_result())
                            self.assertEqual(scheduler.error,'unknown_memory_reference')
                    self.assertNotIn(PRIVATE,json.dumps(scheduler.snapshot()))
            finally:
                await scheduler.close()

    def test_schema_matcher_and_parser_agree_on_canonical_corpus(self):
        schema=ThoughtGenerator.schema();ctx=bench.synthetic_context()
        cases=[(output(),True)]
        for changes in (dict(category='COMMAND'),dict(text=4),dict(text=''),dict(memory_ids=None),
                        dict(uncertainty=True),dict(uncertainty=float('inf')),dict(uncertainty=float('nan')),
                        dict(uncertainty=1.1),dict(text='x'*1201)):
            value=output();value['thoughts'][0].update(changes);cases.append((value,False))
        value=output();value['thoughts'][0].pop('memory_ids');cases.append((value,False))
        value=output();value['version']=True;cases.append((value,False))
        value=output();value['version']=2;cases.append((value,False))
        # Legacy parser and static schema still allow a nonempty proposal without thoughts.
        value=output();value['thoughts']=[];value['proposal']=dict(intent='study_material',
            preferred_subject='observe:stone',motivation='M',evidence_ids=['fixture-event'],
            constraints=['safe_only'],priority=.5,ttl_seconds=60);cases.append((value,True))
        for index,(value,expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(LocalModelProvider._matches(value,schema),expected)
                if expected:ThoughtGenerator.parse(value,ctx,'test')
                else:
                    with self.assertRaises(MindContractError):ThoughtGenerator.parse(value,ctx,'test')

    def test_matcher_rejects_external_cyclic_refs_nonfinite_and_numeric_bools(self):
        for schema in ({'$ref':'https://invalid.example/private-schema'},
                       {'$ref':'#/$defs/Loop','$defs':{'Loop':{'$ref':'#/$defs/Loop'}}}):
            self.assertFalse(LocalModelProvider._matches({},schema))
            public=safe_public_error(LocalModelProvider._schema_issue({},schema))
            self.assertEqual(public['category'],'schema_incompatible')
            self.assertNotIn('invalid.example',json.dumps(public))
        for value,schema in ((True,{'type':'integer'}),(False,{'type':'number'}),
                            (float('nan'),{'type':'number'}),(float('inf'),{'type':'number'})):
            with self.subTest(kind=schema['type']):self.assertFalse(LocalModelProvider._matches(value,schema))
