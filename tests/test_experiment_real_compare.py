"""Real-inference harness orchestration with a mock provider, never Ollama/gameplay."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.contract_diagnostics import MindContractError
from agent.local_model import LocalModelError
from scripts.experiment_compare import _suggestion
from scripts.experiment_real_compare import run_real_experiment


class IdleProbe:
    def snapshot(self):
        return dict(free_ram_mb=8000, cpu_percent=10)


class MockProvider:
    def __init__(self, *, proposal=False, failure=None, available=True):
        self.contexts=[]
        self.proposal=proposal
        self.failure=failure
        self.available=available
        self.health_calls=0

    async def health_check(self):
        self.health_calls+=1
        return dict(available=self.available,error=None if self.available else 'model_missing')

    async def generate(self,messages,schema,*,thinking=False):
        context=json.loads(messages[1]['content'])['untrusted_data']
        self.contexts.append(context)
        if self.failure:
            raise LocalModelError(self.failure)
        output=_suggestion(context)
        if not self.proposal:
            output['proposal']=None
        return SimpleNamespace(content=json.dumps(output),model='fixture',
                               metrics=dict(eval_count=12,tokens_per_second=7,
                                            arbitrary_private_field='NEVER_EXPORT_THIS'))


class RealExperimentCompareTest(unittest.IsolatedAsyncioTestCase):
    async def run_fixture(self,provider,**kwargs):
        return await run_real_experiment((19,),model='fixture',provider=provider,
                                         process_check=lambda:'clear',probe=IdleProbe(),**kwargs)

    async def test_isolated_recall_ablation_and_valid_thought_does_not_imply_influence(self):
        provider=MockProvider()
        report=await self.run_fixture(provider)
        self.assertEqual(report['status'],'completed')
        self.assertTrue(report['synthetic'])
        self.assertFalse(report['gameplay_verified'])
        self.assertFalse(report['private_memory_read'])
        self.assertEqual(len(provider.contexts),2)
        arms={arm['arm']:arm for arm in report['runs'][0]['arms']}
        self.assertEqual(len({json.dumps(arm['conditions'],sort_keys=True) for arm in arms.values()}),1)
        self.assertEqual(len({arm['initial_event_count'] for arm in arms.values()}),1)
        self.assertEqual(arms['B']['recalled_memories'],0)
        self.assertGreater(arms['C']['recalled_memories'],0)
        self.assertEqual(arms['B']['source_events'],arms['C']['source_events'])
        self.assertGreater(arms['B']['prompt_json_bytes'],0)
        self.assertGreater(arms['C']['prompt_json_bytes'],arms['B']['prompt_json_bytes'])
        self.assertGreater(arms['B']['schema_json_bytes'],0)
        for arm in arms.values():
            self.assertFalse(arm['factual_mutations_from_suggestion'])
            self.assertEqual(arm['confirmed_action_outcomes'],0)
            self.assertFalse(arm['influenced'])
            self.assertEqual(arm['selected_action'],arms['A']['selected_action'])
        self.assertTrue(arms['B']['suggestion_accepted'])
        self.assertTrue(arms['B']['output_structurally_valid'])
        self.assertFalse(arms['B']['proposal_present'])
        self.assertFalse(arms['B']['proposal_bound'])
        self.assertFalse(arms['B']['intention_accepted'])
        self.assertNotIn('NEVER_EXPORT_THIS',json.dumps(report))
        self.assertNotIn('talvez explorar',json.dumps(report))

    async def test_bounded_proposal_can_influence_without_claiming_outcome(self):
        provider=MockProvider(proposal=True)
        report=await self.run_fixture(provider)
        arms={arm['arm']:arm for arm in report['runs'][0]['arms']}
        self.assertEqual([arms[arm]['selected_action'] for arm in ('A','B','C')],
                         ['approach','explore','explore'])
        self.assertTrue(arms['B']['proposal_bound'])
        self.assertTrue(arms['B']['intention_accepted'])
        self.assertTrue(arms['C']['influenced'])
        self.assertEqual(arms['C']['confirmed_action_outcomes'],0)

    async def test_timeout_records_fallback_and_preserves_deterministic_choice(self):
        provider=MockProvider(failure='timeout')
        report=await self.run_fixture(provider)
        self.assertEqual(report['status'],'partial')
        arms={arm['arm']:arm for arm in report['runs'][0]['arms']}
        self.assertEqual((arms['B']['status'],arms['B']['reason']),('fallback','timeout'))
        self.assertEqual((arms['C']['status'],arms['C']['reason']),('skipped','paired_arm_unavailable'))
        self.assertTrue(all(arms[name]['fallback'] for name in ('B','C')))
        self.assertTrue(all(arms[name]['selected_action']==arms['A']['selected_action'] for name in ('B','C')))
        self.assertEqual(len(provider.contexts),1)
        with patch('scripts.experiment_real_compare.ensure_fresh_context',
                   side_effect=[None,MindContractError('stale_context')]):
            stale=await self.run_fixture(MockProvider(proposal=True))
        first,second=stale['runs'][0]['arms'][1:]
        self.assertEqual(first['reason'],'stale_context')
        self.assertEqual(second['reason'],'paired_arm_unavailable')
        self.assertFalse(first['intention_accepted'])
        self.assertFalse(second['influenced'])
        self.assertIsNone(first['output_structurally_valid'])

    async def test_unknown_process_and_missing_model_skip_before_inference(self):
        provider=MockProvider()
        report=await run_real_experiment(provider=provider,process_check=lambda:'unknown')
        self.assertEqual(report['reason'],'minecraft_process_unknown')
        self.assertEqual(provider.health_calls,0)
        missing=MockProvider(available=False)
        report=await self.run_fixture(missing)
        self.assertEqual(report['reason'],'model_missing')
        self.assertFalse(report['model_inference'])
        self.assertEqual(missing.contexts,[])

    async def test_resource_guard_and_seed_budget_prevent_calls(self):
        class LowRam:
            def snapshot(self):return dict(free_ram_mb=100,cpu_percent=10)
        provider=MockProvider()
        report=await run_real_experiment((19,),model='fixture',provider=provider,
                                         process_check=lambda:'clear',probe=LowRam())
        self.assertEqual(report['status'],'partial')
        self.assertFalse(report['model_inference'])
        self.assertEqual(provider.contexts,[])
        self.assertEqual(report['resource_limits']['min_free_ram_mb'],4096)
        arms={arm['arm']:arm for arm in report['runs'][0]['arms']}
        self.assertEqual((arms['B']['reason'],arms['C']['reason']),
                         ('resource_budget','paired_arm_unavailable'))
        for seeds in ((),(True,),(-1,),range(4)):
            with self.subTest(seeds=seeds),self.assertRaises(ValueError):
                await run_real_experiment(seeds,provider=provider,process_check=lambda:'clear')


if __name__=='__main__':
    unittest.main()
