"""Synthetic experience/recall/decision lifecycle in isolated SQLite; never gameplay."""
import json
import unittest
from uuid import uuid4

import test_mind_integration as fixtures
import test_cognitive_influence as influence_fixtures
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.memory import MemoryManager


class CognitiveLifecycleTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.MindIntegrationTest.asyncSetUp
    asyncTearDown = fixtures.MindIntegrationTest.asyncTearDown
    payload = fixtures.MindIntegrationTest.payload
    experience = fixtures.MindIntegrationTest.experience
    infer = fixtures.MindIntegrationTest.infer
    opportunities = fixtures.MindIntegrationTest.opportunities
    baseline = influence_fixtures.CognitiveInfluenceTest.baseline

    async def decide_from_memory(self, eid, mid):
        recalled = self.engine.autobiography.recall(self.world, 'fabricação materiais madeira', 4)
        self.assertIn(mid, [memory['id'] for memory in recalled])
        envelope = await self.infer(eid, lambda output: output['thoughts'][0].update(memory_ids=[mid]))
        self.assertIsNotNone(envelope)
        self.assertIn(mid, envelope['context']['source_memory_ids'])
        self.assertIn(eid, envelope['context']['source_manifest'])
        self.assertIn(mid, envelope['context']['source_memory_manifest'])
        step = self.opportunities()
        self.assertEqual(self.baseline(step)['action'], 'approach')
        factual_before = self.m.rows('SELECT * FROM Events')
        self.engine.record_advice(envelope)
        self.assertEqual(factual_before, self.m.rows('SELECT * FROM Events'))
        self.assertEqual(self.m.rows("SELECT outcome FROM MindEvaluations WHERE kind='validation' ORDER BY created DESC LIMIT 1")[0]['outcome'], 'accepted')
        self.engine.last_plan[self.world] = -1e30
        command = self.engine.step(step)['command']
        self.assertEqual(command['action'], 'explore')
        selection = self.m.rows("SELECT * FROM MindEvaluations WHERE kind='selection' AND session=?", (self.session,))[0]
        proof = dict(target={k: command['target'][k] for k in ('x', 'y', 'z')}, server_verified=True,
                     position=dict(x=9.5, y=64, z=.5), dimension='minecraft:overworld')
        self.engine.step(self.payload(results=[dict(id=command['id'], status='success', reason='synthetic_fixture', evidence=proof)]))
        outcome = self.m.rows("SELECT * FROM MindEvaluations WHERE kind='outcome' AND session=?", (self.session,))[0]
        self.assertEqual(outcome['outcome'], 'confirmed')
        self.assertEqual(outcome['plan_id'], selection['plan_id'])
        self.assertEqual(outcome['goal_id'], selection['goal_id'])
        event = self.m.rows('SELECT * FROM Events WHERE id=?', (outcome['event_id'],))[0]
        self.assertEqual((event['verified'], event['world'], event['session']), (1, self.world, self.session))
        self.assertIn(command['id'], json.dumps(event))
        memories = self.m.rows('SELECT * FROM LifeMemories WHERE source_event=?', (event['id'],))
        self.assertTrue(memories)
        self.assertTrue(all(memory['summary']==event['description'] for memory in memories))
        learning = self.engine.snapshot()['mind']['learning']
        self.assertEqual(learning['memory'][0]['source_event'], event['id'])
        self.assertEqual(learning['preference'][0]['source'], event['id'])
        refreshed = self.engine.mind_context.build(self.engine.latest, self.engine.goals.rows(self.world), {}, [], generation=self.engine.mind.validator.generation)
        self.assertTrue(set(memory['id'] for memory in memories) & set(refreshed['source_memory_ids']))

    async def test_observation_to_recalled_intention_action_and_new_memory(self):
        eid = self.experience()
        event = self.m.rows('SELECT * FROM Events WHERE id=?', (eid,))[0]
        self.assertEqual(event['verified'], 1)
        memory = self.m.rows('SELECT * FROM LifeMemories WHERE source_event=?', (eid,))[0]
        await self.decide_from_memory(eid, memory['id'])

    async def test_restart_preserves_experience_for_fresh_validated_decision(self):
        eid = self.experience()
        event = self.m.rows('SELECT * FROM Events WHERE id=?', (eid,))[0]
        memory = self.m.rows('SELECT * FROM LifeMemories WHERE source_event=?', (eid,))[0]
        # Controlled close commits only the temporary fixture database.
        self.m.db.commit()
        self.m.close()
        self.m = MemoryManager(self.root / 'memory.sqlite3')
        self.writer = JournalWriter(self.m, self.root / 'journals')
        self.engine = CognitiveEngine(self.m, self.writer)
        self.session = str(uuid4())
        self.assertEqual(self.m.rows('SELECT * FROM Events WHERE id=?', (eid,)), [event])
        self.assertEqual(self.m.rows('SELECT * FROM LifeMemories WHERE id=?', (memory['id'],)), [memory])
        self.engine.step(self.payload())
        self.engine.goals.ensure(self.engine.latest, 'explore:minecraft:overworld:(1, 4, 0)',
            'Explorar uma região ainda não visitada', 'Fronteira sintética observada', 78, 'explore',
            dict(target=dict(x=9,y=64,z=0,id='minecraft:air')), 'explore_region')
        self.assertFalse(self.m.rows('SELECT * FROM MindBindings'))
        await self.decide_from_memory(eid, memory['id'])
