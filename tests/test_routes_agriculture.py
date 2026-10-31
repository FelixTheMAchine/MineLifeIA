"""Progressive return and replanting contracts using synthetic observations only."""
import json
import unittest
import test_pipeline as base
from agent.engine import CognitiveEngine

SITE=dict(x=2,y=64,z=0)
CROP=dict(**SITE,id='minecraft:wheat',log=False,harvestable=True)
CAPS=['plant','harvest','approach','pickup','explore']

class RoutesAgricultureTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def frame(self,stock=2,results=None,sites=(),blocks=(),**kw):
        self.engine.last_plan[base.WORLD]=-1e30
        return self.step(results,capabilities=CAPS,blocks=list(blocks),farmland=list(sites),
                         player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:wheat_seeds':stock}),**kw)

    def planted(self,c,before=2,after=1):
        return dict(target=SITE,server_verified=True,dimension='minecraft:overworld',before_block='minecraft:air',after_block='minecraft:wheat',
                    soil='minecraft:farmland',crop_age=0,used_delta=1,inventory_before={'minecraft:wheat_seeds':before},inventory_after={'minecraft:wheat_seeds':after})

    def test_plant_observe_maturity_harvest_and_replant_cycle(self):
        plant=self.frame(sites=[SITE])['command'];self.assertEqual(plant['action'],'plant')
        self.frame(1,[self.success(plant,self.planted(plant))])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='crop_harvested'"))
        # Mature stage comes from another observation; the test does not simulate elapsed gameplay.
        approach=self.frame(1,blocks=[CROP])['command'];self.assertEqual(approach['action'],'approach')
        harvest=self.frame(1,[self.success(approach,dict(target=SITE,in_reach=True))],blocks=[CROP])['command']
        self.assertEqual(harvest['action'],'harvest')
        ev=dict(server_verified=True,target=SITE,dimension='minecraft:overworld',before_block='minecraft:wheat',after_block='minecraft:air',before_crop_mature=True,mined_delta=1)
        again=self.frame(1,[self.success(harvest,ev)],sites=[SITE])['command']
        self.assertEqual(again['action'],'plant');self.assertNotEqual(again['id'],plant['id'])
        self.frame(0,[self.success(again,self.planted(again,1,0))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='planted'")),2)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))
        self.assertEqual(len(self.m.rows("SELECT * FROM PhilosophicalQuestions WHERE theme='care-and-future'")),1)
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))

    def test_plant_requires_native_consumption_and_young_crop(self):
        c=self.frame(sites=[SITE])['command'];ev=self.planted(c);ev['inventory_after']={'minecraft:wheat_seeds':2}
        self.frame(2,[self.success(c,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='planted'"))

    def test_no_planting_without_seed_farmland_or_day(self):
        self.assertIsNone(self.frame(0,sites=[SITE])['command'])
        self.assertIsNone(self.frame(2)['command'])
        self.assertIsNone(self.frame(2,sites=[SITE],time=13000)['command'])
        self.assertIsNone(self.frame(2,sites=[SITE],active=False)['command'])

    def test_food_reserve_is_not_all_planted(self):
        self.step(blocks=[],capabilities=['plant'],farmland=[SITE],
                  player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:carrot':2}))
        self.assertFalse(self.m.rows("SELECT * FROM Commands WHERE status='sent'"))

    def test_route_uses_only_new_observed_segments_and_records_server_arrival(self):
        self.frame(frontiers=[dict(x=8,y=64,z=0,safe=True,path_length=8)],active=False)
        s=self.engine.latest
        p=self.engine.routes.request(s,dict(x=40,y=64,z=0),'fixture-point','Retornar ao lugar registrado')
        self.assertEqual(p['params']['target']['x'],8)
        c=self.engine._offer_project(s,p)
        ev=dict(target=dict(x=8,y=64,z=0),server_verified=True,position=dict(x=8.5,y=64,z=.5),dimension='minecraft:overworld')
        self.frame(results=[self.success(c,ev)],active=False)
        route=self.m.rows('SELECT * FROM ReturnRoutes')[0]
        self.assertEqual(json.loads(route['history'])[0]['x'],8)
        self.assertIn('trecho',self.m.rows("SELECT description FROM Events WHERE type='region_reached'")[0]['description'])

    def test_route_refuses_unsafe_away_or_repeated_frontiers(self):
        self.frame(active=False,frontiers=[dict(x=8,y=64,z=0,safe=False,path_length=8),dict(x=-8,y=64,z=0,safe=True,path_length=8)])
        self.assertIsNone(self.engine.routes.request(self.engine.latest,dict(x=40,y=64,z=0),'fixture-point','Retornar'))
        self.assertEqual(self.m.rows('SELECT status FROM ReturnRoutes')[0]['status'],'blocked')
        self.assertFalse(self.m.rows('SELECT * FROM Commands'))

    def test_return_history_persists_and_is_world_isolated(self):
        self.frame(active=False,frontiers=[dict(x=8,y=64,z=0,safe=True,path_length=8)])
        self.engine.routes.request(self.engine.latest,dict(x=40,y=64,z=0),'fixture-point','Retornar')
        old=self.m.rows('SELECT id FROM ReturnRoutes')[0]['id']
        self.engine=CognitiveEngine(self.m,self.writer)
        self.frame(active=False,frontiers=[dict(x=8,y=64,z=0,safe=True,path_length=8)])
        p=self.engine.routes.request(self.engine.latest,dict(x=40,y=64,z=0),'fixture-point','Retornar')
        self.assertEqual(p['params']['route'],old)
        self.assertFalse(self.m.rows('SELECT * FROM ReturnRoutes WHERE world=?',('b'*64,)))
