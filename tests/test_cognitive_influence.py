"""Synthetic A/B cognition experiments; no Ollama or Minecraft execution."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest

import test_mind_integration as fixtures
from life_metrics import LifeMetrics
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.memory import MemoryManager


class CognitiveInfluenceTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.MindIntegrationTest.asyncSetUp
    asyncTearDown = fixtures.MindIntegrationTest.asyncTearDown
    payload = fixtures.MindIntegrationTest.payload
    experience = fixtures.MindIntegrationTest.experience
    infer = fixtures.MindIntegrationTest.infer
    opportunities = fixtures.MindIntegrationTest.opportunities

    def baseline(self, step):
        path = self.root / 'counterfactual.sqlite3'
        self.m.db.commit()
        with closing(sqlite3.connect(path)) as destination:
            self.m.db.backup(destination)
        memory = MemoryManager(path)
        try:
            engine = CognitiveEngine(memory, JournalWriter(memory, self.root / 'baseline-journals'))
            return engine.step(step)['command']
        finally:
            memory.close()

    async def test_valid_intention_changes_choice_and_requires_correlated_result(self):
        eid = self.experience()
        envelope = await self.infer(eid)
        step = self.opportunities()
        inventory = deepcopy(step.player.inventory)
        self.assertEqual(self.baseline(step)['action'], 'approach')
        facts = self.m.rows('SELECT * FROM Events')
        commands = self.m.rows('SELECT * FROM Commands')
        self.engine.record_advice(envelope)
        self.assertEqual(self.m.rows('SELECT * FROM Events'), facts)
        self.assertEqual(self.m.rows('SELECT * FROM Commands'), commands)
        self.engine.last_plan[self.world] = -1e30
        command = self.engine.step(step)['command']
        self.assertEqual(command['action'], 'explore')
        self.assertEqual(step.player.inventory, inventory)
        selected = self.m.rows("SELECT * FROM MindEvaluations WHERE kind='selection' AND outcome='influenced'")
        self.assertEqual(len(selected), 1)
        choice = json.loads(self.m.rows("SELECT evidence FROM Events WHERE type='goal_selected' ORDER BY rowid DESC LIMIT 1")[0]['evidence'])
        self.assertTrue(choice['mind_influenced'])
        self.assertNotEqual(choice['baseline'], choice['goal'])
        self.assertEqual(choice['command'], command['id'])
        self.assertEqual(LifeMetrics(self.m,self.world).report()['mind_changed_choices'],1)
        self.assertEqual(selected[0]['plan_id'], self.m.rows('SELECT plan_id FROM MindBindings')[0]['plan_id'])
        self.assertFalse(self.m.rows("SELECT * FROM MindEvaluations WHERE kind='outcome'"))
        visible = self.engine.snapshot()['mind']
        self.assertEqual(visible['actions'][0]['id'], command['id'])
        self.assertEqual(visible['actions'][0]['plan_id'], selected[0]['plan_id'])
        self.assertTrue(visible['actions'][0]['influenced'])
        self.assertEqual(visible['results'], [])
        proof = dict(target={k: command['target'][k] for k in ('x', 'y', 'z')},
                     server_verified=True, position=dict(x=9.5, y=64, z=.5), dimension='minecraft:overworld')
        self.engine.step(self.payload(results=[dict(id=command['id'], status='success', reason='synthetic_fixture', evidence=proof)]))
        outcome = self.m.rows("SELECT * FROM MindEvaluations WHERE kind='outcome' AND outcome='confirmed'")
        self.assertEqual(len(outcome), 1)
        self.assertEqual(outcome[0]['goal_id'], selected[0]['goal_id'])
        event = self.m.rows('SELECT * FROM Events WHERE id=?', (outcome[0]['event_id'],))[0]
        self.assertEqual((event['world'], event['session']), (self.world, self.session))
        self.assertIn(command['id'], json.dumps(event))
        visible = self.engine.snapshot()['mind']
        self.assertEqual(visible['results'][0]['id'], event['id'])
        self.assertEqual(visible['results'][0]['plan_id'], selected[0]['plan_id'])

    async def test_same_choice_is_not_recorded_as_applied_influence(self):
        eid = self.experience()
        envelope = await self.infer(eid)
        # With no competing observed block, exploration already wins unaided.
        step = self.opportunities()
        step.blocks = []
        self.assertEqual(self.baseline(step)['action'], 'explore')
        self.engine.record_advice(envelope)
        self.engine.last_plan[self.world] = -1e30
        self.assertEqual(self.engine.step(step)['command']['action'], 'explore')
        self.assertFalse(self.m.rows("SELECT * FROM MindEvaluations WHERE kind='selection' AND outcome='influenced'"))

    async def test_false_evidence_and_physical_command_are_rejected_before_binding(self):
        eid = self.experience()
        for mutate in (lambda output: output['proposal'].update(evidence_ids=['missing']),
                       lambda output: output.update(command={'action': 'give', 'item': 'minecraft:diamond'})):
            self.assertIsNone(await self.infer(eid, mutate))
        self.assertFalse(self.m.rows('SELECT * FROM MindBindings'))
        self.engine.last_plan[self.world] = -1e30
        self.assertEqual(self.engine.step(self.opportunities())['command']['action'], 'approach')

    async def test_expired_intention_keeps_deterministic_fallback(self):
        eid = self.experience()
        envelope = await self.infer(eid)
        now = envelope['created_at'] + envelope['output']['proposal']['ttl_seconds'] + 1
        self.engine.mind.validator.clock = lambda: now
        self.engine.mind.clock = lambda: now
        self.engine.record_advice(envelope)
        self.assertFalse(self.m.rows('SELECT * FROM MindBindings'))
        self.engine.last_plan[self.world] = -1e30
        self.assertEqual(self.engine.step(self.opportunities())['command']['action'], 'approach')

    async def test_critical_health_blocks_an_already_accepted_intention(self):
        eid = self.experience()
        envelope = await self.infer(eid)
        self.engine.record_advice(envelope)
        self.assertTrue(self.m.rows('SELECT * FROM MindBindings'))
        step = self.opportunities()
        step.player.health = 1
        baseline = self.baseline(step)
        command = self.engine.step(step)['command']
        self.assertEqual(command['action'] if command else None, baseline['action'] if baseline else None)
        self.assertFalse(self.m.rows("SELECT * FROM MindEvaluations WHERE kind='selection' AND outcome='influenced'"))
