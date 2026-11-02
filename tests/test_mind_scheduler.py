"""Deterministic scheduler tests; these do not exercise a game or a real model."""
import asyncio
import json
import time
import types
import unittest
from unittest.mock import patch

from agent.cognitive_scheduler import CognitiveScheduler
from agent.local_model import LocalModelError, LocalModelResponse


class Probe:
    def __init__(self, ram=4096, cpu=20):
        self.ram, self.cpu = ram, cpu

    def snapshot(self):
        return {'status': 'measured', 'free_ram_mb': self.ram, 'cpu_percent': self.cpu}


class Provider:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.requests = []
        self.errors = []
        self.active = self.maximum = 0

    async def generate(self, messages, schema, *, thinking=False):
        self.requests.append(thinking)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.started.set()
        try:
            await self.release.wait()
            if self.errors:
                raise self.errors.pop(0)
            return LocalModelResponse('{"thoughts":[{"text":"provisional"}]}', 'fixture', None, {})
        finally:
            self.active -= 1

    def snapshot(self):
        return {'status': 'fixture', 'capabilities': {'thinking': True}}


class Generator:
    """Boundary stub: semantic schema validation is tested by test_mind itself."""
    @staticmethod
    def messages(context, purpose):
        return [{'role': 'user', 'content': json.dumps(context)}]

    @staticmethod
    def schema():
        return {'type': 'object'}

    @staticmethod
    def parse(content, context, purpose):
        value = json.loads(content)
        if not value.get('thoughts'):
            raise ValueError('no_content')
        return value


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.parser = patch.dict('sys.modules', {'agent.mind': types.SimpleNamespace(ThoughtGenerator=Generator)})
        self.parser.start()
        self.provider = Provider()
        self.schedulers = []

    async def asyncTearDown(self):
        for scheduler in self.schedulers:
            await scheduler.close()
        self.parser.stop()

    def scheduler(self, **config):
        value = CognitiveScheduler({'provider': 'ollama', 'interval_seconds': 0,
                                    'failure_cooldown_seconds': 0, 'retry_backoff_seconds': 0,
                                    **config}, provider=self.provider, probe=Probe())
        self.schedulers.append(value)
        return value

    def context(self, event='one', **scope):
        return {'mind_version': 1, 'scope': {'world': 'world', 'dimension': 'overworld',
                'session': 'session', 'control_epoch': 1, **scope},
                'source_manifest': {event: 'hash'}, 'source_event_ids': [event],
                'expires_at': time.time() + 60}

    async def test_slow_inference_does_not_block_heartbeat_and_queue_is_bounded(self):
        scheduler = self.scheduler()
        self.provider.release.clear()
        self.assertTrue(scheduler.schedule(self.context()))
        await self.provider.started.wait()
        beats = []
        async def heartbeat():
            for index in range(5):
                beats.append(index)
                await asyncio.sleep(0)
        await heartbeat()
        self.assertEqual(len(beats), 5)
        self.assertFalse(scheduler.schedule({**self.context(), 'seq': 20}))
        self.assertTrue(scheduler.schedule(self.context('two')))
        self.assertTrue(scheduler.schedule(self.context('three')))
        self.assertFalse(scheduler.schedule(self.context('four')))
        self.assertEqual(len(scheduler.queue), 2)
        self.provider.release.set()
        await scheduler.task
        self.assertEqual(self.provider.maximum, 1)
        self.assertEqual(len(self.provider.requests), 3)
        self.assertIsNotNone(scheduler.take_result())
        self.assertIsNone(scheduler.take_result())

    async def test_world_session_epoch_changes_discard_without_opening_second_lane(self):
        for field, value in [('world', 'other'), ('dimension', 'nether'), ('session', 'new'), ('control_epoch', 2)]:
            scheduler = self.scheduler()
            self.provider.started.clear()
            self.provider.release.clear()
            scheduler.schedule(self.context())
            await self.provider.started.wait()
            scheduler.bind_scope(self.context(**{field: value})['scope'])
            self.assertIsNone(scheduler.take_result())
            self.assertTrue(scheduler.schedule(self.context('two', **{field: value})))
            await asyncio.sleep(0)
            self.assertEqual(self.provider.active, 1)
            self.provider.release.set()
            await scheduler.task
            self.assertEqual(scheduler.take_result()['context']['scope'][field], value)
            self.assertGreaterEqual(scheduler.discarded, 1)
        self.assertEqual(self.provider.maximum, 1)

    async def test_unavailable_retries_once_then_recovers_without_losing_event(self):
        scheduler = self.scheduler()
        self.provider.errors = [LocalModelError('unavailable'), LocalModelError('unavailable')]
        scheduler.schedule(self.context())
        await scheduler.task
        self.assertEqual(len(self.provider.requests), 2)
        self.assertEqual(scheduler.status, 'fallback')
        scheduler.schedule(self.context())
        await scheduler.task
        self.assertEqual(scheduler.status, 'ready')

    async def test_timeout_does_not_immediately_start_second_remote_inference(self):
        scheduler=self.scheduler(failure_cooldown_seconds=60)
        self.provider.errors=[LocalModelError('timeout')]
        scheduler.schedule(self.context())
        await scheduler.task
        self.assertEqual(len(self.provider.requests),1)
        self.assertEqual(scheduler.status,'fallback')
        self.assertFalse(scheduler.due())

    async def test_close_cancels_wait_and_discards_result(self):
        scheduler = self.scheduler()
        self.provider.release.clear()
        scheduler.schedule(self.context())
        await self.provider.started.wait()
        await scheduler.close()
        self.assertEqual(self.provider.active, 0)
        self.assertIsNone(scheduler.take_result())
        self.assertFalse(scheduler.due())

    async def test_resource_guard_defers_and_unknown_does_not_fabricate_readings(self):
        scheduler = self.scheduler()
        scheduler.probe = Probe(ram=100)
        scheduler.schedule(self.context())
        await asyncio.sleep(0)
        self.assertEqual(scheduler.status, 'deferred')
        self.assertEqual(self.provider.requests, [])
        scheduler.probe = Probe(ram=None, cpu=None)
        scheduler.wake.set()
        await scheduler.task
        self.assertEqual(scheduler.status, 'ready')

    async def test_deep_requires_explicit_trigger_and_obeys_cooldown(self):
        scheduler = self.scheduler(deep_thinking=True)
        scheduler.schedule({**self.context(), 'deep_trigger': True})
        await scheduler.task
        scheduler.schedule({**self.context('two'), 'deep_trigger': 'project_completed'})
        await scheduler.task
        self.assertEqual(self.provider.requests, [False, True])
        self.assertFalse(scheduler.schedule({**self.context('three'), 'deep_trigger': 'project_completed'}))

    async def test_deep_opt_in_and_capability_fallback(self):
        scheduler = self.scheduler()
        scheduler.schedule({**self.context(), 'deep_trigger': 'project_completed'})
        await scheduler.task
        self.assertEqual(self.provider.requests, [False])
        self.assertEqual(scheduler.snapshot()['deep_reason'], 'opt_in_disabled')
        scheduler = self.scheduler(deep_thinking=True)
        with patch.object(self.provider, 'snapshot', return_value={'capabilities': {'thinking': False}}):
            scheduler.schedule({**self.context(), 'deep_trigger': 'project_completed'})
            await scheduler.task
        self.assertEqual(self.provider.requests, [False, False])
        self.assertEqual(scheduler.snapshot()['deep_reason'], 'thinking_unsupported')

    async def test_resource_budget_can_disable_and_semantic_positions_change_key(self):
        scheduler = self.scheduler(disable_on_budget_overrun=True)
        scheduler.probe = Probe(cpu=99)
        scheduler.schedule(self.context())
        await scheduler.task
        self.assertTrue(scheduler.disabled_budget)
        self.assertEqual(self.provider.requests, [])
        scheduler = self.scheduler()
        scheduler.schedule({**self.context(), 'target': {'position': [1, 2, 3]}})
        await scheduler.task
        self.assertTrue(scheduler.schedule({**self.context(), 'target': {'position': [2, 2, 3]}}))
        await scheduler.task
        self.assertEqual(len(self.provider.requests), 2)

    async def test_interval_retains_bounded_pending_job_until_ready(self):
        scheduler = self.scheduler(interval_seconds=.02)
        self.provider.release.clear()
        scheduler.schedule(self.context())
        await self.provider.started.wait()
        await asyncio.sleep(.03)
        self.assertTrue(scheduler.schedule(self.context('two')))
        self.assertTrue(scheduler.schedule(self.context('three')))
        self.provider.release.set()
        await scheduler.task
        self.assertEqual(len(self.provider.requests), 3)
        self.assertFalse(scheduler.queue)

    async def test_expired_invalid_output_and_hourly_budget_are_finite(self):
        scheduler = self.scheduler(calls_per_hour=1)
        scheduler.schedule({**self.context(), 'expires_at': time.time() - 1})
        await scheduler.task
        self.assertEqual(self.provider.requests, [])
        with patch.object(Generator, 'parse', side_effect=ValueError('schema_mismatch')):
            scheduler.schedule(self.context('two'))
            await scheduler.task
        self.assertEqual(scheduler.status, 'fallback')
        self.assertEqual(len(self.provider.requests), 1)
        self.assertIsNone(scheduler.take_result())
        self.assertFalse(scheduler.schedule(self.context('three')))

    async def test_revoked_control_clears_pending_and_inflight_result(self):
        scheduler = self.scheduler()
        self.provider.release.clear()
        scheduler.schedule(self.context())
        await self.provider.started.wait()
        scheduler.schedule(self.context('two'))
        scheduler.bind_scope(self.context()['scope'], allowed=False)
        self.assertEqual(len(scheduler.queue), 0)
        self.provider.release.set()
        await scheduler.task
        self.assertIsNone(scheduler.take_result())
        self.assertFalse(scheduler.due())

    async def test_disabled_provider_is_deterministic(self):
        scheduler = self.scheduler(provider='none')
        self.assertFalse(scheduler.schedule(self.context()))
        self.assertEqual(self.provider.requests, [])

    async def test_budget_overrun_can_disable_and_expired_response_is_discarded(self):
        now = [0.0]
        scheduler = self.scheduler(inference_budget_seconds=1, disable_on_budget_overrun=True)
        scheduler.clock = lambda: now[0]
        self.provider.release.clear()
        scheduler.schedule(self.context())
        await self.provider.started.wait()
        now[0] = 2
        self.provider.release.set()
        await scheduler.task
        self.assertEqual(scheduler.status, 'budget_disabled')
        self.assertFalse(scheduler.due())

        scheduler = self.scheduler(job_ttl_seconds=1)
        scheduler.clock = lambda: now[0]
        self.provider.started.clear()
        self.provider.release.clear()
        original = self.context()
        scheduler.schedule(original)
        original['scope']['world'] = 'mutated-by-caller'
        await self.provider.started.wait()
        now[0] = 4
        self.provider.release.set()
        await scheduler.task
        self.assertIsNone(scheduler.take_result())
        self.assertEqual(scheduler.status, 'stale')
