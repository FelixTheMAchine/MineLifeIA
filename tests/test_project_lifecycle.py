"""Project lifecycle regressions over temporary SQLite, without gameplay."""
import json
import unittest
from uuid import uuid4

import test_pipeline as base
import test_projects as projects_base
import test_mining_cooking as cooking_fixtures
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.memory import MemoryManager, now
from agent.projects import ProjectManager


class ProjectLifecycleTest(unittest.TestCase):
    setUp = base.PipelineTest.setUp
    tearDown = base.PipelineTest.tearDown
    state = projects_base.ProjectsTest.state
    adopt = projects_base.ProjectsTest.adopt
    step = base.PipelineTest.step
    success = base.PipelineTest.success
    frame = cooking_fixtures.MiningCookingTest.frame
    furnace_frame = cooking_fixtures.MiningCookingTest.furnace_frame
    snapshot = cooking_fixtures.MiningCookingTest.snapshot
    proof = cooking_fixtures.MiningCookingTest.proof

    def conflicted_furnace_after_restart(self,resume=True):
        self.t=100.
        self.engine.clock=lambda:self.t
        self.engine.cooking.clock=lambda:self.t
        inventory=cooking_fixtures.MiningCookingTest.load(self)
        job=self.engine.cooking.current(self.engine.latest)
        proposal=dict(target={**job['station'],'id':'minecraft:furnace'},
                      furnace=dict(job_id=job['id'],recipe=job['recipe'],recover=False))
        gid=self.engine.goals.ensure(self.engine.latest,'fixture-exhausted-inspection','Inspect','Observed',235,
                                     'furnace_inspect',proposal,'furnace_inspect')
        self.m.db.execute('UPDATE GoalPlans SET attempts=2 WHERE goal_id=?',(gid,))
        self.m.db.execute("UPDATE Goals SET status='abandoned' WHERE id=?",(gid,))
        self.m.db.execute("UPDATE FurnaceJobs SET status='conflict',revision=64 WHERE id=?",(job['id'],))
        self.engine.projects.sync(self.engine.latest)
        project=self.m.rows('SELECT * FROM LongProjects WHERE source_id=?',(job['id'],))[0]
        self.m.db.commit();self.m.close()
        self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        self.writer=JournalWriter(self.m,self.root/'journals')
        self.engine=CognitiveEngine(self.m,self.writer,clock=lambda:self.t)
        self.engine.cooking.clock=lambda:self.t
        self.session=str(uuid4())
        state=self.state(capabilities=cooking_fixtures.CAPS,
                         player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory=inventory))
        if resume:self.engine.projects.resume(state,project['id'],'Reobservar explicitamente o preparo bloqueado')
        return inventory,job,project,gid

    def row(self):
        return self.m.rows('SELECT * FROM LongProjects ORDER BY rowid LIMIT 1')[0]

    def test_irrelevant_cycles_do_not_exhaust_stagnation_budget(self):
        s,p = self.adopt()
        unavailable = self.state(capabilities=[])
        for _ in range(40):self.engine.projects.sync(unavailable)
        self.assertEqual(self.row()['stagnation'],0)
        self.assertEqual(self.row()['status'],'active')
        self.assertEqual(self.row()['id'],p['id'])
        self.assertFalse(self.m.rows('SELECT * FROM Commands'))

    def test_resource_loss_and_restoration_replan_without_clearing_stagnation(self):
        s,p = self.adopt()
        rich = self.state(player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,
                                     inventory={'minecraft:oak_planks':22}))
        self.engine.projects.sync(rich)
        for _ in range(3):self.engine.projects.sync(rich)
        self.assertEqual(self.row()['stagnation'],3)
        poor = self.state(player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,
                                     inventory={'minecraft:oak_planks':10}))
        self.engine.projects.sync(poor)
        self.assertEqual(self.row()['stagnation'],4)
        self.assertEqual(json.loads(self.row()['deficits']),{'planks':12})
        self.engine.projects.sync(rich)
        self.assertEqual(self.row()['stagnation'],5)
        self.assertEqual(self.row()['id'],p['id'])
        self.assertEqual(json.loads(self.row()['deficits']),{})

    def test_pending_native_source_survives_more_than_eight_completed_jobs(self):
        s = self.state(capabilities=[])
        recipe = json.dumps(dict(input_id='minecraft:raw_iron',fuel_id='minecraft:coal',output_id='minecraft:iron_ingot'))
        pending = str(uuid4())
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          (pending,s.world,s.dimension,json.dumps(dict(x=1,y=64,z=0)),recipe,'planned','2000-01-01',now()))
        for index in range(12):
            self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                              (str(uuid4()),s.world,s.dimension,json.dumps(dict(x=2,y=64,z=index)),recipe,'completed',now(),now()))
        self.engine.projects.sync(s)
        rows = self.m.rows("SELECT * FROM LongProjects WHERE source_kind='furnace'")
        self.assertEqual(len(rows),9)
        self.assertIn(pending,{r['source_id'] for r in rows})

    def test_adoption_has_interpretable_rationale_and_only_evidenced_preferences(self):
        eid = self.m.event(base.WORLD,self.session,1,'observed','Synthetic preference source',True,{},'preference-source')
        self.m.db.execute('INSERT INTO Preferences VALUES(?,?,?,?,?,?)',
                          (base.WORLD,'activity','creation',.4,json.dumps([eid,'unverified-id']),now()))
        s,p = self.adopt()
        context = json.loads(self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? AND kind='adopted'",(p['id'],))[0]['context'])
        rationale = context['rationale']
        self.assertTrue(rationale['need'])
        self.assertTrue(rationale['expected_benefit'])
        self.assertEqual(set(rationale['available_capabilities']),set(s.capabilities))
        self.assertEqual(rationale['deficits'],{'planks':22})
        self.assertEqual(rationale['evidenced_preferences'][0]['sources'],[eid])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'"))

    def test_same_session_resume_preserves_native_id_and_requires_reinspection(self):
        s,p = self.adopt()
        self.m.db.execute("UPDATE ConstructionProjects SET status='building',last_session=?",(str(s.session),))
        self.engine.construction.checked[(p['source_id'],str(s.session))] = self.engine.construction.clock()
        self.engine.projects.suspend(s,'Urgencia alimentar')
        self.engine.projects.resume(s,p['id'],'Reservas recuperadas; revalidar local')
        self.engine.projects.sync(s)
        proposal = self.engine.construction.propose(s)
        self.assertEqual(proposal['kind'],'inspect_shelter')
        self.assertEqual(proposal['params']['shelter']['project'],p['source_id'])
        self.assertEqual(self.row()['id'],p['id'])
        self.assertEqual(len(self.m.rows('SELECT * FROM ConstructionProjects')),1)

    def test_urgent_condition_keeps_focus_suspended_and_budget_intact(self):
        s,p = self.adopt()
        unsafe = self.state(player=dict(x=0,y=64,z=2,health=20,food=4,danger=False,inventory={}))
        self.engine.projects.sync(unsafe)
        self.assertIsNone(self.engine.projects.focus(unsafe))
        self.assertEqual(self.row()['status'],'suspended')
        self.assertEqual(self.row()['stagnation'],0)

    def test_current_build_step_remains_viable_with_only_its_capability(self):
        s, project = self.adopt()
        step = self.state(capabilities=['build_shelter'],
                          player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,
                                      inventory={'minecraft:oak_planks':22}))
        self.engine.projects.sync(step)
        self.assertEqual(self.engine.projects.focus(step)['id'],project['id'])
        self.assertEqual(self.row()['status'],'active')
        self.assertEqual(self.row()['stagnation'],0)

    def test_only_focused_project_spends_opportunity_budget(self):
        s,p = self.adopt()
        jid = str(uuid4())
        recipe = json.dumps(dict(input_id='minecraft:raw_iron',fuel_id='minecraft:coal',output_id='minecraft:iron_ingot'))
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          (jid,s.world,s.dimension,json.dumps(dict(x=1,y=64,z=0)),recipe,'planned',now(),now()))
        both = self.state(capabilities=list(s.capabilities)+['furnace_inspect','furnace_load','furnace_take'])
        for _ in range(10):self.engine.projects.sync(both)
        furnace = self.m.rows('SELECT * FROM LongProjects WHERE source_id=?',(jid,))[0]
        self.assertEqual(furnace['stagnation'],0)
        self.assertEqual(self.row()['stagnation'],10)

    def test_unavailable_active_project_yields_focus_to_observed_furnace(self):
        s,shelter = self.adopt()
        jid = str(uuid4())
        recipe = json.dumps(dict(input_id='minecraft:raw_iron',fuel_id='minecraft:coal',output_id='minecraft:iron_ingot'))
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          (jid,s.world,s.dimension,json.dumps(dict(x=1,y=64,z=0)),recipe,'planned',now(),now()))
        available = self.state(capabilities=['furnace_inspect','furnace_load','furnace_take'],
                               player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,
                                           inventory={'minecraft:raw_iron':1,'minecraft:coal':1}))
        self.engine.projects.sync(available)
        focused = self.engine.projects.focus(available)
        self.assertEqual(focused['source_id'],jid)
        preserved = self.m.rows('SELECT status,stagnation FROM LongProjects WHERE id=?',(shelter['id'],))[0]
        self.assertEqual(preserved['status'],'active')
        self.assertEqual(preserved['stagnation'],0)
        self.assertEqual(self.engine.projects.bonus(available,'furnace_inspect',dict(furnace=dict(job_id=jid))),35)
        self.m.db.commit();self.m.close()
        self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        manager=ProjectManager(self.m)
        self.assertEqual(manager.focus(available)['source_id'],jid)
        self.assertEqual(self.m.rows('SELECT status FROM LongProjects WHERE id=?',(shelter['id'],))[0]['status'],'active')

    def test_cancelled_work_does_not_spend_budget_on_resume(self):
        s,p = self.adopt()
        gid = self.engine.goals.ensure(s,'fixture-build','Build','Observed',100,'build_shelter',
                                       dict(target=dict(x=0,y=64,z=0),shelter=dict(project=p['source_id'])),'build_shelter')
        self.m.db.execute('INSERT INTO ProjectGoalLinks VALUES(?,?,?,?)',(p['id'],gid,'Fixture',now()))
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)',('fixture-experiment',gid))
        self.m.db.execute('INSERT INTO Commands VALUES(?,?,?,?,?,?,?,?)',
                          (str(uuid4()),s.world,str(s.session),'fixture-experiment','{}','cancelled','{}',now()))
        self.engine.projects.suspend(s,'Urgencia alimentar')
        self.engine.projects.resume(s,p['id'],'Controle retomado')
        self.engine.projects.sync(self.state(capabilities=[]))
        self.assertEqual(self.row()['stagnation'],0)

    def test_conflicted_furnace_resume_after_restart_reinspects_and_only_recovers_output(self):
        inventory,old,project,gid=self.conflicted_furnace_after_restart()
        reopened=self.m.rows('SELECT * FROM FurnaceJobs WHERE id=?',(old['id'],))[0]
        self.assertEqual(reopened['status'],'planned')
        self.assertIsNone(reopened['last_session'])
        self.assertIsNone(reopened['load_event'])
        self.assertEqual(json.loads(reopened['inspection']),old['inspection'])
        marker=json.loads(self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? AND kind='resumed' ORDER BY rowid DESC LIMIT 1",(project['id'],))[0]['context'])['furnace_resume']
        self.assertEqual(marker['previous_load_event'],old['load_event'])
        self.assertTrue(self.m.rows('SELECT 1 FROM Events WHERE id=?',(old['load_event'],)))
        # The explicit budget and conservative provenance survive another restart
        # before the first physical inspection has even been requested.
        self.m.db.commit();self.m.close()
        self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        self.writer=JournalWriter(self.m,self.root/'journals')
        self.engine=CognitiveEngine(self.m,self.writer,clock=lambda:self.t)
        self.engine.cooking.clock=lambda:self.t
        self.session=str(uuid4())
        fresh=self.furnace_frame(inventory)['command']
        self.assertEqual(fresh['action'],'furnace_inspect')
        self.assertEqual(fresh['furnace']['job_id'],old['id'])
        self.assertNotIn('project_resume',fresh)
        self.assertEqual(self.m.rows('SELECT attempts FROM GoalPlans WHERE goal_id=?',(gid,))[0]['attempts'],2)
        take=self.furnace_frame(inventory,[self.success(fresh,self.proof(fresh,self.snapshot(inventory,output=1)))])['command']
        self.assertEqual(take['action'],'furnace_take')
        after={**inventory,cooking_fixtures.COOK['output_id']:1}
        self.furnace_frame(after,[self.success(take,self.proof(take,self.snapshot(inventory,output=1),self.snapshot(after),2))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='furnace_recovered'")),1)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))
        self.assertEqual(len(self.m.rows('SELECT * FROM FurnaceJobs')),1)

    def test_conflicted_furnace_resume_blocks_again_when_fresh_inspection_is_incompatible(self):
        inventory,old,project,gid=self.conflicted_furnace_after_restart()
        inspect=self.furnace_frame(inventory)['command']
        conflicting=self.snapshot(inventory,inputs=1)
        conflicting['slots'][0]['id']='minecraft:diamond'
        self.furnace_frame(inventory,[self.success(inspect,self.proof(inspect,conflicting))])
        self.assertEqual(self.m.rows('SELECT status FROM FurnaceJobs WHERE id=?',(old['id'],))[0]['status'],'conflict')
        self.assertIsNone(self.engine.cooking.current(self.engine.latest))
        resumed=json.loads(self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? AND kind='resumed' ORDER BY rowid DESC LIMIT 1",(project['id'],))[0]['context'])['furnace_resume']
        self.assertFalse(self.m.rows("SELECT * FROM GoalPlans WHERE kind IN ('furnace_load','furnace_take') AND json_extract(params,'$.project_resume')=?",(resumed['token'],)))

    def test_furnace_resume_refuses_an_unresolved_command(self):
        inventory,old,project,gid=self.conflicted_furnace_after_restart()
        self.furnace_frame(inventory)
        with self.assertRaises(ValueError):
            self.engine.projects.resume(self.engine.latest,project['id'],'Outra tentativa')
        self.assertEqual(len(self.m.rows("SELECT * FROM ProjectDecisions WHERE project=? AND kind='resumed'",(project['id'],))),1)

    def test_explicit_furnace_resume_budget_remains_bounded(self):
        inventory,old,project,gid=self.conflicted_furnace_after_restart()
        state=self.state(capabilities=cooking_fixtures.CAPS,
                         player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory=inventory))
        proposal=self.engine.cooking.propose(state)
        renewed=self.engine.goals.ensure(state,**proposal)
        self.assertNotEqual(renewed,gid)
        self.m.db.execute('UPDATE GoalPlans SET attempts=2 WHERE goal_id=?',(renewed,))
        self.assertIsNone(self.engine.cooking.propose(state))
        self.assertEqual(self.m.rows('SELECT status FROM FurnaceJobs WHERE id=?',(old['id'],))[0]['status'],'conflict')
        self.assertEqual(self.m.rows('SELECT sum(attempts) n FROM GoalPlans WHERE goal_id IN (?,?)',(gid,renewed))[0]['n'],4)

    def test_conflicted_furnace_resume_refuses_another_active_job_at_same_station(self):
        inventory,old,project,gid=self.conflicted_furnace_after_restart(resume=False)
        station={axis:old['station'][axis] for axis in ('z','y','x')}
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          (str(uuid4()),old['world'],old['dimension'],json.dumps(station),json.dumps(old['recipe']),'planned',now(),now()))
        state=self.state(capabilities=cooking_fixtures.CAPS)
        with self.assertRaises(ValueError):
            self.engine.projects.resume(state,project['id'],'Retomar a estacao compartilhada')
        native=self.m.rows('SELECT status,load_event FROM FurnaceJobs WHERE id=?',(old['id'],))[0]
        self.assertEqual(native,dict(status='conflict',load_event=old['load_event']))
        self.assertFalse(self.m.rows("SELECT * FROM ProjectDecisions WHERE project=? AND kind='resumed'",(project['id'],)))

    def test_ordinary_furnace_resume_preserves_load_and_does_not_renew_budget(self):
        self.t=100.;self.engine.clock=lambda:self.t;self.engine.cooking.clock=lambda:self.t
        cooking_fixtures.MiningCookingTest.load(self)
        state=self.engine.latest;job=self.engine.cooking.current(state)
        self.engine.projects.sync(state)
        project=self.m.rows('SELECT * FROM LongProjects WHERE source_id=?',(job['id'],))[0]
        self.engine.projects.suspend(state,'Pausa comum')
        self.engine.projects.resume(state,project['id'],'Continuar apos pausa')
        resumed=self.m.rows('SELECT load_event,revision FROM FurnaceJobs WHERE id=?',(job['id'],))[0]
        self.assertEqual(resumed,dict(load_event=job['load_event'],revision=job['revision']))
        self.assertEqual(json.loads(self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? AND kind='resumed' ORDER BY rowid DESC LIMIT 1",(project['id'],))[0]['context']),{})


if __name__ == '__main__':
    unittest.main()
