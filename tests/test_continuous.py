import json
import time
import unittest
from uuid import uuid4
import test_pipeline as legacy
from agent.engine import CognitiveEngine

WORLD=legacy.WORLD
CAPS=['approach','break','collect','explore','observe','craft']
FRONTIER=dict(x=9,y=64,z=0,safe=True,path_length=9)
RECIPE=dict(id='minecraft:birch_planks',input_id='minecraft:birch_log',input_count=1,output_id='minecraft:birch_planks',output_count=4)


class ContinuousTest(unittest.TestCase):
    setUp=legacy.PipelineTest.setUp
    tearDown=legacy.PipelineTest.tearDown
    step=legacy.PipelineTest.step
    success=legacy.PipelineTest.success
    complete=legacy.PipelineTest.complete
    break_result=legacy.PipelineTest.break_result

    def next_plan(self, **kwargs):
        self.engine.last_plan[WORLD]=-1e30
        return self.step(**kwargs)

    def test_discovery_leads_to_second_objective(self):
        self.complete()
        second=self.next_plan(blocks=[dict(x=3,y=64,z=0,id='minecraft:birch_log',log=True)])
        self.assertEqual(second['command']['target']['id'],'minecraft:birch_log')
        self.assertEqual(len(self.m.rows("SELECT * FROM Experiments WHERE status='completed'")),1)
        self.assertTrue(self.m.rows("SELECT * FROM Questions WHERE subject LIKE 'application:%'"))

    def test_known_subject_is_not_repeated_and_cognition_keeps_rechecking(self):
        self.complete()
        before=self.engine.planning_cycles
        for _ in range(5): self.assertIsNone(self.next_plan()['command'])
        self.assertEqual(self.engine.planning_cycles,before+5)
        self.assertEqual(len(self.m.rows('SELECT * FROM Experiments')),1)
        self.assertEqual(self.engine.state,'WAITING_FOR_SAFE_ACTION')
        self.assertTrue(self.m.rows("SELECT * FROM Goals WHERE status='blocked'"))

    def test_new_region_when_no_nearby_novelty(self):
        c=self.step(blocks=[],frontiers=[FRONTIER],capabilities=CAPS)['command']
        self.assertEqual(c['action'],'explore')
        ev=dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,
                position=dict(x=9.5,y=64,z=.5),dimension='minecraft:overworld')
        self.step([self.success(c,ev)],blocks=[],frontiers=[dict(x=1,y=64,z=0,safe=True,path_length=9)],capabilities=CAPS,
                  player=dict(x=9.5,y=64,z=.5,health=20,food=20,danger=False,inventory={}),biome='minecraft:forest')
        self.assertTrue(self.m.rows("SELECT * FROM Events WHERE type='region_reached'"))
        self.assertEqual(len(self.m.rows('SELECT * FROM SpatialRegions')),2)
        self.assertEqual(self.m.rows("SELECT count(*) n FROM Experiments WHERE status='running'")[0]['n'],0)

    def test_unsafe_frontier_is_not_used(self):
        r=self.step(blocks=[],frontiers=[dict(FRONTIER,safe=False)],capabilities=CAPS)
        self.assertIsNone(r['command'])

    def test_failed_goal_suspended_and_alternative_selected(self):
        c=self.step()['command']
        r=self.step([dict(id=c['id'],status='failed',reason='no_safe_path',evidence={})],
                    blocks=[dict(x=3,y=64,z=0,id='minecraft:birch_log',log=True)])
        self.assertEqual(r['command']['target']['id'],'minecraft:birch_log')
        self.assertTrue(self.m.rows("SELECT * FROM Goals WHERE status='suspended'"))

    def test_paused_emergency_and_unauthorized_never_send_action(self):
        for data in (dict(active=False),dict(armed=False),dict(active=False,armed=False,control_state='EMERGENCY_STOP')):
            self.assertIsNone(self.step(**data)['command'])
        self.assertEqual(self.engine.state,'EMERGENCY_STOP')

    def test_old_command_not_replayed_after_restart(self):
        old=self.step()['command']['id']
        self.engine=CognitiveEngine(self.m,self.writer)
        self.session=str(uuid4())
        new=self.step()['command']
        self.assertIsNotNone(new)
        self.assertNotEqual(new['id'],old)
        self.assertEqual(self.m.rows('SELECT status FROM Commands WHERE id=?',(old,))[0]['status'],'interrupted')

    def test_planning_rate_is_bounded_when_idle(self):
        moment=[100.0]
        self.engine.clock=lambda:moment[0]
        for _ in range(100): self.step(blocks=[])
        self.assertEqual(self.engine.planning_cycles,1)
        moment[0]+=2.1
        self.step(blocks=[])
        self.assertEqual(self.engine.planning_cycles,2)

    def test_new_memory_is_world_isolated(self):
        self.step()
        first=self.m.rows('SELECT * FROM Questions WHERE world=?',(WORLD,))
        self.engine.last_seen=-1e30
        self.session=str(uuid4())
        self.step(world='b'*64)
        second=self.m.rows('SELECT * FROM Questions WHERE world=?',('b'*64,))
        self.assertTrue(first and second)
        self.assertNotEqual(first[0]['id'],second[0]['id'])

    def test_crafting_requires_consumption_output_and_crafted_stat(self):
        c=self.step(blocks=[],recipes=[RECIPE],capabilities=CAPS,
                    player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:birch_log':1}))['command']
        self.assertEqual(c['action'],'craft')
        ev=dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,recipe=RECIPE['id'],crafted_delta=4,
                inventory_before={'minecraft:birch_log':1},inventory_after={'minecraft:birch_planks':4})
        self.step([self.success(c,ev)],blocks=[])
        self.assertEqual(self.m.rows('SELECT status FROM Knowledge')[0]['status'],'confirmed')
        self.assertTrue(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))

    def test_inventory_change_alone_is_not_crafting_evidence(self):
        c=self.step(blocks=[],recipes=[RECIPE],capabilities=CAPS,
                    player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:birch_log':1}))['command']
        ev=dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,recipe=RECIPE['id'],crafted_delta=0,
                inventory_before={'minecraft:birch_log':1},inventory_after={'minecraft:birch_planks':4})
        self.step([self.success(c,ev)],blocks=[])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))

    def test_personality_changes_are_small_and_evidence_linked(self):
        self.complete()
        changes=self.m.rows('SELECT * FROM PersonalityChanges')
        self.assertTrue(changes)
        self.assertTrue(all(abs(c['new_value']-c['old_value'])<=.25 for c in changes))
        for c in changes: self.assertTrue(self.m.rows('SELECT 1 FROM Events WHERE id=? AND verified=1',(c['source_event'],)))

    def test_prudence_changes_the_operational_safety_margin(self):
        self.step(active=False, blocks=[])
        personality=self.engine.motivation.values(WORLD)
        personality['prudence']=90
        self.m.db.execute('UPDATE Personality SET values_json=? WHERE world=?',(json.dumps(personality),WORLD))
        response=self.step(player=dict(x=0,y=64,z=0,health=10,food=20,danger=False,inventory={}))
        self.assertEqual(response['control'],'pause')
        self.assertIsNone(response['command'])
        self.assertFalse(self.m.rows('SELECT * FROM Experiments'))

    def test_goal_becomes_executable_after_missing_skill_is_available(self):
        self.step(blocks=[])
        s=self.engine.latest
        gid=self.engine.goals.ensure(s,'recipe:fixture','Testar receita','Sem habilidade',100,'craft',{},'craft_planks',blocked=True)
        self.assertEqual(self.m.rows('SELECT status FROM Goals WHERE id=?',(gid,))[0]['status'],'blocked')
        same=self.engine.goals.ensure(s,'recipe:fixture','Testar receita','Habilidade disponível',100,'craft',{},'craft_planks')
        self.assertEqual(same,gid)
        self.assertEqual(self.m.rows('SELECT status FROM Goals WHERE id=?',(gid,))[0]['status'],'pending')

    def test_goal_limit_deduplication_and_retry_budget(self):
        self.engine.goals.max_active=2
        self.step(blocks=[dict(x=2+i,y=64,z=0,id=f'minecraft:fixture_{i}_log',log=True) for i in range(5)])
        active=self.m.rows("SELECT * FROM Goals WHERE status IN ('pending','running')")
        self.assertEqual(len(active),2)
        subject=self.m.rows('SELECT subject FROM GoalPlans WHERE goal_id=?',(active[0]['id'],))[0]['subject']
        self.engine.goals.failure(active[0]['id'],'no_path')
        self.engine.goals.failure(active[0]['id'],'no_path')
        self.assertEqual(self.m.rows('SELECT status FROM Goals WHERE id=?',(active[0]['id'],))[0]['status'],'abandoned')
        s=self.engine.latest
        self.engine.goals.ensure(s,subject,'Não repetir','Mesmo assunto',99,'log',{},'investigate_log')
        self.assertEqual(self.m.rows('SELECT count(*) n FROM GoalPlans WHERE subject=?',(subject,))[0]['n'],1)
        self.assertEqual(self.m.rows('SELECT status FROM Goals WHERE id=?',(active[0]['id'],))[0]['status'],'abandoned')

    def test_philosophical_question_and_autobiographical_memory_are_evidence_linked(self):
        self.complete()
        thoughts=self.m.rows('SELECT * FROM PhilosophicalQuestions')
        self.assertEqual(len(thoughts),1)
        thought=thoughts[0]
        proof=self.m.rows('SELECT verified,type FROM Events WHERE id=?',(thought['origin_event'],))[0]
        self.assertEqual((proof['verified'],proof['type']),(1,'collected'))
        memories=self.engine.autobiography.recall(WORLD,'minecraft:oak_log',4)
        self.assertTrue(memories)
        reflected=next(e for e in self.m.rows("SELECT * FROM JournalEntries WHERE kind='reflection'")
                       if thought['origin_event'] in json.loads(e['evidence_ids']))
        self.assertTrue(self.writer.validate_entry(reflected))
        self.assertIn(thought['question'],reflected['text'])
        self.assertTrue(self.m.rows('SELECT * FROM PhilosophicalRevisions WHERE origin_event=?',(thought['origin_event'],)))

    def test_philosophical_interpretations_evolve_with_new_evidence(self):
        self.complete()
        first=self.m.rows("SELECT current FROM PhilosophicalRevisions WHERE theme='knowledge'")[0]['current']
        eid=self.m.event(WORLD,self.session,1,'collected','Fixture de nova coleta verificada.',True,
                         {'subject':'minecraft:birch_log'},'second-evidence')
        self.engine.philosophy.consider(WORLD,1,self.session,eid)
        revisions=self.m.rows("SELECT * FROM PhilosophicalRevisions WHERE theme='knowledge' ORDER BY created")
        self.assertEqual(len(revisions),2)
        self.assertEqual(revisions[1]['previous'],first)
        self.assertTrue(self.m.rows('SELECT 1 FROM Events WHERE id=? AND verified=1',(revisions[1]['origin_event'],)))

    def test_unverified_event_cannot_trigger_philosophical_memory(self):
        eid=self.m.event(WORLD,self.session,1,'collected','Coleta sem prova.',False,{},'unverified-evidence')
        self.assertIsNone(self.engine.philosophy.consider(WORLD,1,self.session,eid))
        self.assertFalse(self.m.rows('SELECT * FROM PhilosophicalQuestions'))
        self.assertFalse(self.m.rows('SELECT * FROM LifeMemories'))

    def test_language_model_drafts_are_persisted_as_unverified_only(self):
        self.step(blocks=[])
        proposal={'world':WORLD,'purpose':'philosophy','preferred_subject':'unknown-action',
                  'question':'Posso investigar isto?','hypothesis':'Talvez exista um mecanismo.',
                  'interpretation':'Proposta sem confirmação.','reflection':'Rascunho narrativo.',
                  'journal_draft':'A cidade aconteceu.','social_interpretation':'sugestão',
                  'source_event_ids':[]}
        self.engine.record_advice(proposal)
        saved=self.m.rows('SELECT * FROM CognitiveSuggestions')[0]
        self.assertEqual(saved['status'],'unverified')
        self.assertFalse(self.m.rows('SELECT * FROM Knowledge'))
        self.assertFalse(self.m.rows('SELECT * FROM JournalEntries'))
