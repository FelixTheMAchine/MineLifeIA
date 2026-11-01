"""Verified fixture experience -> recall -> interpretation -> allowed goal.

Language output is synthetic. No external model or consciousness is asserted.
"""
import unittest
import sqlite3
from contextlib import closing
import test_pipeline as base
from agent.memory import MemoryManager
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.protocol import Step


class CognitiveChainTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def test_verified_crafting_memory_and_interpretation_change_allowed_goal(self):
        recipe=dict(id='minecraft:oak_planks',input_id='minecraft:oak_log',input_count=1,output_id='minecraft:oak_planks',output_count=4)
        caps=['craft','explore','observe','approach']
        command=self.step(blocks=[],capabilities=caps,recipes=[recipe],
                          player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:oak_log':1}))['command']
        self.assertEqual(command['action'],'craft')
        proof=dict(target={k:command['target'][k] for k in ('x','y','z')},server_verified=True,
                   recipe=recipe['id'],crafted_delta=4,inventory_before={'minecraft:oak_log':1},inventory_after={'minecraft:oak_planks':4})
        self.step([self.success(command,proof)],blocks=[],capabilities=caps,
                  player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:oak_planks':4}))
        event=self.m.rows("SELECT * FROM Events WHERE type='crafted'")[0]
        recalled=self.engine.autobiography.recall(base.WORLD,'crafting creation ferramentas',5)
        self.assertIn(event['id'],[m['source_event'] for m in recalled])
        self.assertTrue(self.m.rows('SELECT * FROM PreferenceUpdates WHERE source=?',(event['id'],)))
        params=dict(blocks=[dict(x=2,y=64,z=0,id='minecraft:stone',log=False)],
                    frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)],capabilities=caps)
        # Branch the same fixture database to compare the decision without advice.
        probe_path=self.root/'probe.sqlite3'
        with closing(sqlite3.connect(probe_path)) as destination:self.m.db.backup(destination)
        probe=MemoryManager(probe_path)
        try:
            baseline=CognitiveEngine(probe,JournalWriter(probe,self.root/'probe-journals'))
            payload=self.engine.latest.model_dump(mode='json')|params|dict(seq=self.seq+1,results=[])
            self.assertEqual(baseline.step(Step(**payload))['command']['action'],'approach')
        finally:probe.close()
        self.assertEqual(self.engine.language.bonus(base.WORLD,'explore',{'target':{'id':'minecraft:air'}},'explore:fixture'),0)
        self.engine.record_advice(dict(world=base.WORLD,purpose='philosophy',preferred_subject=None,
            question='Que lugares podem ampliar as possibilidades desses materiais?',hypothesis='Explorar pode revelar novas aplicacoes.',
            interpretation='Uma interpretacao provisoria da experiencia registrada.',journal_draft='',social_interpretation='',
            proposal=dict(intent='explore_regions',evidence_ids=[event['id']]),source_event_ids=[event['id']],claims=[dict(event_id=event['id'])]))
        self.engine.last_plan[base.WORLD]=-1e30
        result=self.step(**params)
        self.assertEqual(result['command']['action'],'explore')
        self.assertTrue(self.engine.skills.available('explore_region',caps))
        self.assertGreater(self.engine.language.bonus(base.WORLD,'explore',result['command'],'explore:fixture'),0)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='region_reached'"))
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))
