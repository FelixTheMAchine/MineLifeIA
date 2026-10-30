"""Construction planning/evidence fixtures. These tests do not start Minecraft or modify real saves."""
import json
import unittest
from uuid import uuid4
import test_pipeline as base
from agent.construction import BLUEPRINT, CAPABILITIES, PLANKS, position
from agent.engine import CognitiveEngine
from agent.protocol import Step

ANCHOR=dict(x=0,y=64,z=0)
STOCK={'minecraft:oak_planks':16,'minecraft:oak_door':1}


class ConstructionTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def frame(self,inv=None,results=None,site=True,coords=(.5,64,.5),caps=None,blocks=(),**kwargs):
        self.engine.last_plan[base.WORLD]=-1e30
        return self.step(results,capabilities=sorted(CAPABILITIES) if caps is None else caps,blocks=list(blocks),shelter_sites=[ANCHOR] if site else [],
                         player=dict(x=coords[0],y=coords[1],z=coords[2],health=20,food=20,danger=False,inventory=inv if inv is not None else STOCK),**kwargs)

    def survey(self,cmd,filled=0,open_door=False,where='inside'):
        data=cmd['shelter'];a=data['anchor']
        cells=[]
        for i,spec in enumerate(BLUEPRINT['steps']):
            item=('minecraft:oak_door' if spec['role']=='door' else 'minecraft:oak_planks') if i<filled else 'minecraft:air'
            cells.append(dict(step=i,pos=position(a,spec['offset']),id=item))
        return dict(server_verified=True,target={k:cmd['target'][k] for k in ('x','y','z')},project=data['project'],anchor=a,blueprint=BLUEPRINT['id'],
                    cells=cells,floor_solid=True,interior_clear=True,door_valid=filled==17,door_open=open_door,entrance_clear=filled<17,complete=filled==17,
                    inside=where=='inside',outside=where=='outside',position=dict(x=a['x']+.5,y=a['y'],z=a['z']+(.5 if where=='inside' else 2.5)))

    def placed(self,cmd,before):
        req=cmd['shelter'];spec=BLUEPRINT['steps'][req['step']];item=req['item_id'];after=dict(before);after[item]-=1
        ev=dict(server_verified=True,target=position(req['anchor'],spec['offset']),project=req['project'],anchor=req['anchor'],blueprint=BLUEPRINT['id'],
                step=req['step'],support=position(req['anchor'],spec['support']),face=spec['face'],
                before_block='minecraft:air',after_block=item,used_delta=1,inventory_before=before,inventory_after=after,
                door_valid=spec['role']=='door',door_open=False)
        return ev,after

    def full_build(self):
        cmd=self.frame()['command'];self.assertEqual(cmd['action'],'inspect_shelter')
        inv=dict(STOCK)
        cmd=self.frame(inv,[self.success(cmd,self.survey(cmd))])['command']
        for i in range(17):
            self.assertEqual((cmd['action'],cmd['shelter']['step']),('build_shelter',i))
            ev,inv=self.placed(cmd,inv)
            cmd=self.frame(inv,[self.success(cmd,ev)],site=False)['command']
        self.assertEqual(cmd['action'],'inspect_shelter')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'"))
        return cmd,inv

    def test_full_blueprint_requires_final_inspection_then_leaves_and_continues(self):
        cmd,inv=self.full_build()
        leave=self.frame(inv,[self.success(cmd,self.survey(cmd,17))],site=False)['command']
        self.assertEqual(leave['action'],'leave_shelter')
        done=self.frame(inv,[self.success(leave,self.survey(leave,17,where='outside'))],site=False,coords=(.5,64,2.5))
        self.assertIsNone(done['command'])
        self.assertEqual(self.engine.construction.current(self.engine.latest)['status'],'ready')
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'")),1)
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='construction_step'")),17)
        self.assertEqual(len(self.m.rows("SELECT * FROM PhilosophicalQuestions WHERE theme='shelter-and-belonging'")),1)
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))
        self.engine.last_plan[base.WORLD]=-1e30
        response=self.step(blocks=[dict(x=4,y=64,z=0,id='minecraft:birch_log',log=True)],capabilities=['approach','break','collect'],
                           player=dict(x=.5,y=64,z=2.5,health=20,food=20,danger=False,inventory={}))
        self.assertEqual(response['command']['action'],'approach')

    def test_missing_resources_create_demand_but_not_placed_blocks(self):
        cmd=self.frame({})['command']
        response=self.frame({},[self.success(cmd,self.survey(cmd))])
        self.assertIsNone(response['command'])
        self.assertEqual(self.engine.construction.requirements(self.engine.latest),(16,1))
        self.assertEqual(self.engine.construction.wood_demand(self.engine.latest),22)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('construction_step','shelter_completed')"))

    def test_no_site_no_capability_or_night_does_not_create_project(self):
        self.assertIsNone(self.frame(site=False)['command'])
        self.assertFalse(self.m.rows('SELECT * FROM ConstructionProjects'))
        self.assertIsNone(self.frame(time=13000)['command'])
        self.assertFalse(self.m.rows('SELECT * FROM ConstructionProjects'))
        self.engine.last_plan[base.WORLD]=-1e30
        self.step(blocks=[],capabilities=[],shelter_sites=[ANCHOR])
        self.assertFalse(self.m.rows('SELECT * FROM ConstructionProjects'))

    def test_placement_without_used_stat_or_wrong_target_cannot_advance(self):
        inspect=self.frame()['command']
        cmd=self.frame(results=[self.success(inspect,self.survey(inspect))])['command']
        ev,inv=self.placed(cmd,STOCK);ev['used_delta']=0
        self.frame(inv,[self.success(cmd,ev)])
        self.assertEqual(self.m.rows('SELECT status FROM ConstructionSteps WHERE step=0')[0]['status'],'pending')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='construction_step'"))

    def test_forged_complete_missing_roof_does_not_confirm_shelter(self):
        cmd=self.frame()['command'];ev=self.survey(cmd,17);ev['cells'][15]['id']='minecraft:air'
        self.frame(results=[self.success(cmd,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'"))
        self.assertNotEqual(self.engine.construction.current(self.engine.latest)['status'],'ready')

    def test_conflicting_existing_block_is_preserved_and_project_blocked(self):
        cmd=self.frame()['command'];ev=self.survey(cmd);ev['cells'][0]['id']='minecraft:chest'
        response=self.frame(results=[self.success(cmd,ev)])
        self.assertIsNone(response['command'])
        self.assertEqual(self.engine.construction.current(self.engine.latest)['status'],'blocked')

    def test_restart_inspects_partial_build_without_replaying_or_inventing_placement(self):
        inspect=self.frame()['command']
        interrupted=self.frame(results=[self.success(inspect,self.survey(inspect))])['command']
        self.engine=CognitiveEngine(self.m,self.writer);self.session=str(uuid4())
        recovery=self.frame()['command']
        self.assertEqual(recovery['action'],'inspect_shelter')
        self.assertNotEqual(recovery['id'],interrupted['id'])
        response=self.frame(results=[self.success(recovery,self.survey(recovery,1))])
        self.assertEqual(response['command']['shelter']['step'],1)
        self.assertEqual(self.m.rows('SELECT status FROM ConstructionSteps WHERE step=0')[0]['status'],'present')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='construction_step'"))

    def test_night_enters_waits_and_daytime_leaves_with_distinct_evidence(self):
        inspect=self.frame()['command']
        enter=self.frame(results=[self.success(inspect,self.survey(inspect,17,where='outside'))],
                         time=13000,coords=(.5,64,2.5))['command']
        self.assertEqual(enter['action'],'enter_shelter')
        response=self.frame(results=[self.success(enter,self.survey(enter,17))],time=13000)
        self.assertIsNone(response['command'])
        self.assertIn('porta fechada',response['reason'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='slept'"))
        leave=self.frame(time=1000)['command'];self.assertEqual(leave['action'],'leave_shelter')

    def test_open_door_cannot_confirm_entry(self):
        inspect=self.frame()['command']
        enter=self.frame(results=[self.success(inspect,self.survey(inspect,17,where='outside'))],time=13000,coords=(.5,64,2.5))['command']
        self.frame(results=[self.success(enter,self.survey(enter,17,open_door=True))],time=13000)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_entered'"))

    def test_cancelled_build_releases_goal_without_claiming_progress(self):
        inspect=self.frame()['command']
        cmd=self.frame(results=[self.success(inspect,self.survey(inspect))])['command']
        response=self.frame(results=[dict(id=cmd['id'],status='cancelled',reason='control_interrupted',evidence={})],active=False)
        self.assertIsNone(response['command'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='construction_step'"))

    def test_correlated_inspection_is_world_isolated(self):
        cmd=self.frame()['command'];old=self.survey(cmd,17)
        self.engine.last_seen=-1e30;self.session=str(uuid4())
        self.frame(world='d'*64,site=False,results=[self.success(cmd,old)])
        self.assertIsNone(self.engine.construction.current(self.engine.latest))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='shelter_completed'"))

    def test_door_recipe_demand_and_bench_placement_do_not_block_blueprint(self):
        self.frame()
        s=self.engine.latest
        self.assertEqual(self.engine.crafting.demand(s,'minecraft:oak_door'),0) # already has a door
        s=s.model_copy(deep=True);s.player.inventory={'minecraft:oak_planks':4,'minecraft:crafting_table':1}
        self.assertEqual(self.engine.crafting.demand(s,'minecraft:oak_door'),1)
        self.assertGreater(self.engine.crafting.demand(s,'minecraft:oak_planks'),4)

    def test_repeated_observations_do_not_generate_continuous_inspections(self):
        inspect=self.frame()['command']
        self.frame(results=[self.success(inspect,self.survey(inspect,17))],time=13000)
        for _ in range(20):self.assertIsNone(self.frame(time=13000)['command'])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='shelter_inspected'")),1)

    def test_missing_component_reopens_only_that_step_with_a_new_revision(self):
        cmd,inv=self.full_build()
        leave=self.frame(inv,[self.success(cmd,self.survey(cmd,17))])['command']
        self.frame(inv,[self.success(leave,self.survey(leave,17,where='outside'))],coords=(.5,64,2.5))
        p=self.engine.construction.current(self.engine.latest)
        self.engine.construction.checked[(p['id'],self.session)]=-1e30
        check=self.frame({'minecraft:oak_planks':1},coords=(.5,64,2.5))['command']
        self.assertEqual(check['action'],'inspect_shelter')
        ev=self.survey(check,17,where='outside');ev['cells'][0]['id']='minecraft:air';ev['complete']=False
        repair=self.frame({'minecraft:oak_planks':1},[self.success(check,ev)],coords=(.5,64,2.5))['command']
        self.assertEqual((repair['action'],repair['shelter']['step']),('build_shelter',0))
        rows=self.m.rows('SELECT step,status,revision FROM ConstructionSteps ORDER BY step')
        self.assertEqual(rows[0],dict(step=0,status='pending',revision=1))
        self.assertTrue(all(r['status']=='placed' for r in rows[1:]))

    def test_wrong_project_or_geometry_cannot_be_accepted(self):
        cmd=self.frame()['command']
        for what in ('project','geometry','material'):
            ev=self.survey(cmd,17)
            if what=='project':ev['project']=str(uuid4())
            elif what=='geometry':ev['cells'][0]['pos']['x']+=1
            else:ev['cells'][0]['id']='minecraft:sand'
            self.assertFalse(self.engine.construction.validate(self.engine.latest,cmd,ev))

    def test_pause_emergency_and_danger_never_start_construction(self):
        for overrides in (dict(active=False),dict(armed=False),dict(control_state='EMERGENCY_STOP')):
            response=self.frame(**overrides)
            self.assertIsNone(response['command'])
        self.engine.last_plan[base.WORLD]=-1e30
        response=self.step(blocks=[],capabilities=sorted(CAPABILITIES),shelter_sites=[ANCHOR],
                           player=dict(x=.5,y=64,z=.5,health=20,food=20,danger=True,inventory=STOCK))
        self.assertIsNone(response['command'])
        self.assertFalse(self.m.rows('SELECT * FROM ConstructionProjects'))

    def test_partial_project_without_materials_can_be_left_without_claiming_shelter(self):
        cmd=self.frame({})['command']
        leave=self.frame({},[self.success(cmd,self.survey(cmd,5))])['command']
        self.assertEqual(leave['action'],'leave_shelter')
        self.frame({},[self.success(leave,self.survey(leave,5,where='outside'))],coords=(.5,64,2.5))
        self.assertTrue(self.m.rows("SELECT * FROM Events WHERE type='construction_departed'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('shelter_completed','shelter_left')"))

    def test_observed_door_recipe_supplies_the_project_before_building(self):
        from test_workstations import recipe,CAPS,TABLE
        caps=CAPS+sorted(CAPABILITIES)
        door=recipe('oak_door',{'minecraft:oak_planks':6},'oak_door',count=3,grid=3)
        inv={'minecraft:oak_planks':22}
        check=self.frame(inv,caps=caps,blocks=[TABLE],recipes=[door])['command']
        craft=self.frame(inv,[self.success(check,self.survey(check))],caps=caps,blocks=[TABLE],recipes=[door])['command']
        self.assertEqual(craft['action'],'craft_table')
        after={'minecraft:oak_planks':16,'minecraft:oak_door':3}
        ev=dict(server_verified=True,target={k:craft['target'][k] for k in ('x','y','z')},recipe=door['id'],
                inventory_before=inv,inventory_after=after,crafted_delta=3,grid=3,station=door['station'],station_opened=True)
        build=self.frame(after,[self.success(craft,ev)],caps=caps,blocks=[TABLE])['command']
        self.assertEqual((build['action'],build['shelter']['step']),('build_shelter',0))
