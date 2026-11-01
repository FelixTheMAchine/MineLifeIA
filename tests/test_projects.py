"""Project dependencies over real planners with synthetic observations, never gameplay."""
import json
import unittest
from pathlib import Path
from uuid import uuid4
import test_pipeline as base
from agent.protocol import Step
from agent.projects import ProjectManager
from agent.engine import CognitiveEngine
from agent.memory import MemoryManager
from agent.construction import CAPABILITIES, BLUEPRINT


class ProjectsTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def state(self,**kw):
        data=dict(protocol=1,session=self.session,world=base.WORLD,dimension='minecraft:overworld',seq=1,
                  day=1,time=1000,active=True,armed=True,results=[],blocks=[],capabilities=list(CAPABILITIES),
                  shelter_sites=[dict(x=0,y=64,z=0)],player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,inventory={}))
        return Step(**(data|kw))

    def adopt(self):
        s=self.state();self.engine.construction.prepare(s);self.engine.projects.sync(s)
        return s,self.engine.projects.focus(s)

    def test_adopts_only_real_native_projects_and_builds_dependency_graph(self):
        self.assertIsNone(self.engine.projects.focus(self.state()))
        s,p=self.adopt()
        self.assertEqual(json.loads(p['deficits']),{'planks':22})
        nodes=self.m.rows('SELECT * FROM ProjectDependencies WHERE project=?',(p['id'],))
        self.assertEqual({n['node'] for n in nodes},{'resources','execute','verify'})
        self.assertEqual(json.loads(next(n for n in nodes if n['node']=='verify')['requires']),['execute'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'"))

    def test_suspend_restart_resume_and_replan_preserve_same_project(self):
        s,p=self.adopt();self.engine.projects.suspend(s,'Fome observada')
        self.m.db.commit();self.m.close();self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        manager=ProjectManager(self.m)
        self.assertIsNone(manager.focus(s))
        rich=self.state(player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,inventory={'minecraft:oak_planks':22}))
        manager.sync(rich);resumed=manager.focus(rich)
        self.assertEqual(resumed['id'],p['id']);self.assertEqual(json.loads(resumed['deficits']),{})
        self.assertTrue(self.m.rows("SELECT * FROM ProjectDecisions WHERE project=? AND kind='replanned'",(p['id'],)))

    def test_stagnation_cooldown_does_not_reset_native_progress(self):
        s,p=self.adopt();clock=[100.];manager=ProjectManager(self.m,clock=lambda:clock[0])
        for _ in range(24):manager.sync(s)
        self.assertIsNone(manager.focus(s))
        row=self.m.rows('SELECT * FROM LongProjects')[0]
        self.assertEqual(row['status'],'stalled');self.assertEqual(row['retry_after'],160.)
        self.assertFalse(manager.allows(s,'shelter',p['source_id']))
        manager=ProjectManager(self.m,clock=lambda:clock[0]);manager.sync(s)
        self.assertIsNone(manager.focus(s))
        clock[0]=161.;manager.sync(s);self.assertEqual(manager.focus(s)['id'],p['id'])
        self.assertTrue(manager.allows(s,'shelter',p['source_id']))
        self.assertEqual(len(self.m.rows('SELECT * FROM ConstructionSteps')),len(BLUEPRINT['steps']))

    def test_abandon_requires_reason_and_explicit_resume(self):
        s,p=self.adopt()
        with self.assertRaises(ValueError):self.engine.projects.abandon(s,p['id'],'')
        self.engine.projects.abandon(s,p['id'],'Local inacessivel observado')
        self.assertEqual(self.m.rows('SELECT status FROM ConstructionProjects')[0]['status'],'abandoned')
        self.engine.projects.sync(s);self.assertIsNone(self.engine.projects.focus(s))
        self.assertIsNone(self.engine.construction.prepare(s))
        self.assertEqual(len(self.m.rows('SELECT * FROM ConstructionProjects')),1)
        self.engine.projects.resume(s,p['id'],'Nova oportunidade observada')
        self.engine.projects.sync(s);self.assertEqual(self.engine.projects.focus(s)['id'],p['id'])
        self.assertEqual(self.m.rows('SELECT status FROM ConstructionProjects')[0]['status'],'planned')

    def test_ready_status_without_verified_inspection_never_completes(self):
        s,p=self.adopt()
        self.m.db.execute("UPDATE ConstructionProjects SET status='ready'")
        self.engine.projects.sync(s)
        self.assertNotEqual(self.m.rows('SELECT status FROM LongProjects')[0]['status'],'completed')
        pid=p['source_id']
        eid=self.m.event(s.world,str(s.session),1,'shelter_inspected','Fixture inspecionada.',True,
                         dict(server_verified=True,dimension=s.dimension,project=pid,complete=True),'verified-fixture')
        self.m.db.execute('UPDATE ConstructionProjects SET last_inspection=?',(eid,))
        self.engine.projects.sync(s)
        self.assertEqual(self.m.rows('SELECT status FROM LongProjects')[0]['status'],'completed')
        self.assertIsNone(self.engine.projects.focus(s))

    def test_world_dimension_and_danger_do_not_share_focus(self):
        s,p=self.adopt()
        self.assertIsNone(self.engine.projects.focus(self.state(world='b'*64)))
        self.assertIsNone(self.engine.projects.focus(self.state(dimension='minecraft:the_nether')))
        unsafe=self.state(player=dict(x=0,y=64,z=2,health=20,food=20,danger=True,inventory={}))
        self.assertEqual(self.engine.projects.bonus(unsafe,'craft',dict(recipe={'output_id':'minecraft:oak_planks'})),0)

    def test_abandon_refuses_an_unresolved_native_command(self):
        result=self.step(blocks=[],capabilities=list(CAPABILITIES),shelter_sites=[dict(x=0,y=64,z=0)])
        self.assertEqual(result['command']['action'],'inspect_shelter')
        p=self.engine.projects.focus(self.engine.latest)
        with self.assertRaises(ValueError):self.engine.projects.abandon(self.engine.latest,p['id'],'Interromper projeto')
        self.assertEqual(self.m.rows('SELECT status FROM ConstructionProjects')[0]['status'],'planned')

    def test_engine_respects_project_cooldown_before_native_inspection(self):
        s,p=self.adopt();clock=[100.];self.engine.projects.clock=lambda:clock[0]
        self.m.db.execute("UPDATE LongProjects SET status='stalled',stagnation=24,retry_after=160")
        self.assertIsNone(self.step(blocks=[],capabilities=list(CAPABILITIES))['command'])
        self.assertFalse(self.m.rows('SELECT * FROM Commands'))
        clock[0]=161.;self.engine.last_plan[base.WORLD]=-1e30
        response=self.step(blocks=[],capabilities=list(CAPABILITIES))
        self.assertEqual(response['command']['action'],'inspect_shelter')
        self.assertEqual(response['command']['shelter']['project'],p['source_id'])

    def test_focus_changes_allowed_goal_selection_and_links_dependency(self):
        s,p=self.adopt()
        # Two valid recipes compete. A real shelter deficit changes their
        # selection order without emitting a new action type.
        self.engine.construction.checked[(p['source_id'],self.session)]=self.engine.construction.clock()
        self.m.db.execute("UPDATE ConstructionProjects SET status='building',last_session=?",(self.session,))
        self.engine.last_plan[base.WORLD]=-1e30
        plank=dict(id='minecraft:oak_planks',input_id='minecraft:oak_log',input_count=1,output_id='minecraft:oak_planks',output_count=4)
        stick=dict(id='minecraft:stick',input_id='minecraft:oak_planks',input_count=2,output_id='minecraft:stick',output_count=4)
        inv={'minecraft:oak_log':1,'minecraft:oak_planks':2}
        before=self.state(capabilities=['craft'],recipes=[stick,plank],
                          player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,inventory=inv))
        self.assertEqual(self.engine.crafting.proposals(before,self.engine.motivation.values(base.WORLD))[0]['params']['recipe']['output_id'],'minecraft:stick')
        cmd=self.step(blocks=[],capabilities=['craft'],recipes=[stick,plank],
                      player=dict(x=0,y=64,z=2,health=20,food=20,danger=False,inventory=inv))['command']
        self.assertEqual(cmd['action'],'craft');self.assertEqual(cmd['recipe']['output_id'],'minecraft:oak_planks')
        self.assertTrue(self.m.rows('SELECT * FROM ProjectGoalLinks WHERE project=?',(p['id'],)))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))
