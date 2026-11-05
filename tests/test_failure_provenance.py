"""Operational errors remain auditable without fabricating strategy learning."""
import json
import unittest
from uuid import uuid4

import test_pipeline as base
from agent.engine import CognitiveEngine
from agent.failure_assessment import assess_failure
from agent.journal.writer import JournalWriter
from agent.memory import MemoryManager


class FailureProvenanceTest(unittest.TestCase):
    setUp = base.PipelineTest.setUp
    tearDown = base.PipelineTest.tearDown
    step = base.PipelineTest.step
    success = base.PipelineTest.success

    def assert_no_negative_learning(self, event_id):
        self.assertFalse(self.m.rows('SELECT 1 FROM PreferenceUpdates WHERE source=?',(event_id,)))
        self.assertFalse(self.m.rows('SELECT 1 FROM InterestUpdates WHERE source=?',(event_id,)))
        self.assertFalse(self.m.rows('SELECT 1 FROM PersonalityChanges WHERE source_event=?',(event_id,)))
        self.assertFalse(self.m.rows('SELECT 1 FROM SkillProgress WHERE failures>0'))

    def test_unverified_result_survives_restart_without_learning_or_replay(self):
        command = self.step()['command']
        wrong = dict(target=dict(x=999,y=64,z=0),in_reach=True)
        self.step([self.success(command,wrong)])
        event = self.m.rows("SELECT * FROM Events WHERE type='attempt_failed'")[0]
        evidence = json.loads(event['evidence'])
        self.assertEqual((evidence['failure_category'],evidence['physical_outcome'],evidence['origin']),
                         ('inconclusive','inconclusive','backend_validation'))
        self.assertEqual(self.m.rows('SELECT attempts FROM GoalPlans')[0]['attempts'],0)
        self.assert_no_negative_learning(event['id'])
        self.assertEqual(self.m.rows('SELECT status FROM Commands WHERE id=?',(command['id'],))[0]['status'],'unverified')

        self.m.db.commit();self.m.close()
        self.m = MemoryManager(self.root / 'data' / 'memory.sqlite3')
        self.writer = JournalWriter(self.m,self.root / 'journals')
        self.engine = CognitiveEngine(self.m,self.writer)
        self.session = str(uuid4())
        self.m.db.execute('UPDATE GoalPlans SET cooldown=0')
        alternative = dict(x=3,y=64,z=0,id='minecraft:birch_log',log=True)
        resumed = self.step(blocks=[alternative])['command']
        self.assertIsNotNone(resumed)
        self.assertNotEqual(resumed['id'],command['id'])
        self.assertEqual(resumed['target']['id'],alternative['id'])
        self.assertFalse(self.m.rows("SELECT 1 FROM Experiments WHERE status='completed'"))
        self.assert_no_negative_learning(event['id'])

    def test_route_failure_chooses_alternative_without_material_penalty(self):
        command = self.step()['command']
        self.step([dict(id=command['id'],status='failed',reason='path_obstructed',evidence={})])
        event = self.m.rows("SELECT * FROM Events WHERE type='attempt_failed' ORDER BY rowid DESC LIMIT 1")[0]
        evidence = json.loads(event['evidence'])
        self.assertEqual((evidence['failure_category'],evidence['physical_outcome']),('navigation','inconclusive'))
        self.assert_no_negative_learning(event['id'])
        self.assertEqual(self.m.rows('SELECT attempts FROM GoalPlans')[0]['attempts'],1)
        alternative = dict(x=3,y=64,z=0,id='minecraft:birch_log',log=True)
        self.engine.last_plan[base.WORLD]=-1e30
        next_command = self.step(blocks=[alternative])['command']
        self.assertIsNotNone(next_command)
        self.assertEqual(next_command['target']['id'],alternative['id'])

    def test_two_uncertain_reports_keep_goal_suspended_without_spending_budget(self):
        self.step()
        goal = self.m.rows('SELECT id FROM Goals')[0]['id']
        for _ in range(2):self.engine.goals.failure(goal,'backend_command_timeout',uncertain=True)
        row = self.m.rows('SELECT g.status,p.attempts FROM Goals g JOIN GoalPlans p ON p.goal_id=g.id WHERE g.id=?',(goal,))[0]
        self.assertEqual(row,dict(status='suspended',attempts=0))

    def test_backend_watchdog_pauses_without_negative_learning(self):
        command = self.step()['command']
        self.engine.command_sent[command['id']]=self.engine.clock()-30
        self.engine.last_plan[base.WORLD]=-1e30
        response = self.step()
        self.assertEqual(response['control'],'pause')
        self.assertIsNone(response['command'])
        event = self.m.rows("SELECT * FROM Events WHERE type='attempt_failed'")[0]
        evidence = json.loads(event['evidence'])
        self.assertEqual((evidence['failure_category'],evidence['origin']),('timeout','backend_watchdog'))
        self.assertEqual(self.m.rows('SELECT attempts FROM GoalPlans')[0]['attempts'],0)
        self.assert_no_negative_learning(event['id'])

    def test_timeout_and_resource_errors_do_not_spend_goal_budget(self):
        for reason,category in [('backend_command_timeout','timeout'),('inventory_full','resource'),
                                ('unknown_error','inconclusive')]:
            with self.subTest(reason=reason):
                assessment = assess_failure('failed',reason)
                self.assertEqual(assessment.category,category)
                self.assertFalse(assessment.count_attempt)
        for reason,category in [('item_entity_changed','stale_state'),('inventory_busy','interaction'),
                                ('pickup_timeout','timeout')]:
            with self.subTest(reason=reason):
                assessment = assess_failure('failed',reason)
                self.assertEqual(assessment.category,category)
                self.assertTrue(assessment.count_attempt)


if __name__ == '__main__':unittest.main()
