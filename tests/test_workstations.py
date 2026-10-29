"""Synthetic protocol/state tests, not gameplay. All databases and journals are temporary."""
import json
import unittest
from uuid import uuid4
from pydantic import ValidationError
import test_pipeline as legacy
from agent.crafting import ingredients
from agent.engine import CognitiveEngine
from agent.protocol import RecipeOffer, Player, PlacementSpot
from agent.food import FoodAcquisitionManager

CAPS=['approach','break','collect','observe','explore','craft','craft_table','place','eat','pickup']
TABLE=dict(x=2,y=64,z=0,id='minecraft:crafting_table',log=False)
SPOT=dict(x=2,y=64,z=0,support=dict(x=2,y=63,z=0))


def recipe(name, inputs, output, count=1, grid=2):
    first=next(iter(inputs))
    return dict(id='minecraft:'+name,input_id=first,input_count=inputs[first],inputs=inputs,
                output_id='minecraft:'+output,output_count=count,grid=grid,
                station={k:TABLE[k] for k in ('x','y','z')} if grid==3 else None)


PLANKS=recipe('birch_planks',{'minecraft:birch_log':1},'birch_planks',4)
BENCH=recipe('crafting_table',{'minecraft:birch_planks':4},'crafting_table')
STICKS=recipe('stick',{'minecraft:birch_planks':2},'stick',4)
PICK=recipe('wooden_pickaxe',{'minecraft:birch_planks':3,'minecraft:stick':2},'wooden_pickaxe',grid=3)
BREAD=recipe('bread',{'minecraft:wheat':3},'bread',grid=3)


class WorkstationsTest(unittest.TestCase):
    setUp=legacy.PipelineTest.setUp
    tearDown=legacy.PipelineTest.tearDown
    step=legacy.PipelineTest.step
    success=legacy.PipelineTest.success

    def observe(self, inv, recipes=(), blocks=(), food=20, results=None, foods=(), **kwargs):
        self.engine.last_plan[legacy.WORLD]=-1e30
        return self.step(results,capabilities=CAPS,blocks=list(blocks),recipes=list(recipes),
                         player=dict(x=0,y=64,z=0,health=20,food=food,danger=False,inventory=inv,foods=list(foods)),**kwargs)

    def proof(self,c,before,after):
        if c['action'] in ('craft','craft_table'):
            r=c['recipe']
            return dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,
                        inventory_before=before,inventory_after=after,recipe=r['id'],
                        crafted_delta=r['output_count'],grid=r.get('grid',2),station=r.get('station'),station_opened=True)
        return dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,
                    inventory_before=before,inventory_after=after,before_block='minecraft:air',
                    after_block='minecraft:crafting_table',used_delta=1,support=SPOT['support'])

    def test_chain_planks_table_placement_sticks_and_pickaxe(self):
        a={'minecraft:birch_log':4}
        c=self.observe(a,[PLANKS])['command']
        b={'minecraft:birch_log':3,'minecraft:birch_planks':4}
        table=self.observe(b,[BENCH,PLANKS],results=[self.success(c,self.proof(c,a,b))])['command']
        self.assertEqual(table['recipe']['output_id'],'minecraft:crafting_table')
        c_inv={'minecraft:birch_log':3,'minecraft:crafting_table':1}
        place=self.observe(c_inv,[PLANKS],placement_spots=[SPOT],
                           results=[self.success(table,self.proof(table,b,c_inv))])['command']
        self.assertEqual(place['action'],'place')
        d={'minecraft:birch_log':3}
        next_craft=self.observe(d,[PLANKS],blocks=[TABLE],
                               results=[self.success(place,self.proof(place,c_inv,d))])['command']
        self.assertEqual(next_craft['action'],'craft')
        inv=d
        for batch in range(3):
            after=dict(inv)
            after['minecraft:birch_log']-=1
            after['minecraft:birch_planks']=after.get('minecraft:birch_planks',0)+4
            offers=[STICKS] if batch==2 else [PLANKS]
            next_craft=self.observe(after,offers,blocks=[TABLE],
                                    results=[self.success(next_craft,self.proof(next_craft,inv,after))])['command']
            inv=after
        self.assertEqual(next_craft['recipe']['output_id'],'minecraft:stick')
        after={**inv,'minecraft:birch_planks':10,'minecraft:stick':4}
        pick=self.observe(after,[PICK],blocks=[TABLE],results=[self.success(next_craft,self.proof(next_craft,inv,after))])['command']
        self.assertEqual(pick['action'],'craft_table')
        final={**after,'minecraft:birch_planks':7,'minecraft:stick':2,'minecraft:wooden_pickaxe':1}
        self.observe(final,[PICK],blocks=[TABLE],results=[self.success(pick,self.proof(pick,after,final))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='placed' AND verified=1")),1)
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='crafted' AND verified=1")),7)
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))
        self.assertFalse(self.m.rows("SELECT * FROM Commands WHERE status='sent' AND payload LIKE '%wooden_pickaxe%'"))

    def test_hunger_prepares_bread_from_observed_recipe(self):
        before={'minecraft:wheat':3}
        c=self.observe(before,[BREAD],blocks=[TABLE],food=4)['command']
        self.assertEqual(c['action'],'craft_table')
        after={'minecraft:bread':1}
        self.observe(after,blocks=[TABLE],food=4,results=[self.success(c,self.proof(c,before,after))])
        self.assertTrue(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='ate'"))

    def test_hungry_agent_collects_wheat_before_it_has_three(self):
        item=dict(entity_id=str(uuid4()),x=1,y=64,z=0,item_id='minecraft:wheat',count=2,edible=False)
        c=self.observe({},food=4,items=[item])['command']
        self.assertEqual(c['action'],'pickup')

    def test_crafting_then_consumption_are_separate_verified_experiences(self):
        before={'minecraft:wheat':3}
        craft=self.observe(before,[BREAD],blocks=[TABLE],food=4)['command']
        bread={'minecraft:bread':1}
        meal=self.observe(bread,blocks=[TABLE],food=4,foods=[dict(id='minecraft:bread',slot=12,count=1,nutrition=5)],
                          results=[self.success(craft,self.proof(craft,before,bread))])['command']
        self.assertEqual(meal['action'],'eat')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='ate'"))
        ev=dict(target={k:meal['target'][k] for k in ('x','y','z')},server_verified=True,
                inventory_before=bread,inventory_after={},food_before=4,food_after=9)
        self.observe({},blocks=[TABLE],food=9,results=[self.success(meal,ev)])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='ate'")),1)
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))

    def test_eating_preempts_workstation_goals_even_with_one_goal_slot(self):
        self.engine.goals.max_active=1
        c=self.observe({'minecraft:bread':1,'minecraft:crafting_table':1},placement_spots=[SPOT],food=3,
                       foods=[dict(id='minecraft:bread',slot=12,count=1,nutrition=5)])['command']
        self.assertEqual(c['action'],'eat')

    def test_failed_eating_keeps_retry_budget_instead_of_creating_infinite_meals(self):
        inv={'minecraft:bread':1};foods=[dict(id='minecraft:bread',slot=12,count=1,nutrition=5)]
        first=self.observe(inv,food=3,foods=foods)['command']
        failure=dict(id=first['id'],status='failed',reason='inventory_busy',evidence={})
        self.assertIsNone(self.observe(inv,food=3,foods=foods,results=[failure])['command'])
        for _ in range(10):self.assertIsNone(self.observe(inv,food=3,foods=foods)['command'])
        self.assertEqual(len(self.m.rows("SELECT * FROM GoalPlans WHERE subject LIKE 'meal:%'")),1)
        self.m.db.execute("UPDATE GoalPlans SET cooldown=0 WHERE subject LIKE 'meal:%'")
        retry=self.observe(inv,food=3,foods=foods)['command']
        self.assertEqual(retry['action'],'eat')
        self.assertIsNone(self.observe(inv,food=3,foods=foods,
                                      results=[dict(failure,id=retry['id'])])['command'])
        self.assertIsNone(self.observe(inv,food=3,foods=foods)['command'])
        self.assertTrue(self.m.rows("SELECT * FROM Goals WHERE status='abandoned'"))

    def test_harvest_and_sleep_require_their_approach_dependency(self):
        crop=dict(x=2,y=64,z=0,id='minecraft:wheat',log=False,harvestable=True)
        bed=dict(x=2,y=64,z=0,id='minecraft:red_bed',log=False,bed=True)
        player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory={})
        self.assertIsNone(self.step(blocks=[crop],capabilities=['harvest'],player=player)['command'])
        self.engine.last_plan[legacy.WORLD]=-1e30
        self.assertIsNone(self.step(blocks=[bed],capabilities=['sleep'],time=13000)['command'])

    def test_workstation_proof_requires_each_ingredient_and_server_gui(self):
        for corrupt in ('ingredient','station','stat'):
            with self.subTest(corrupt=corrupt):
                # Each alternative has a fresh synthetic world/session.
                if self.seq:
                    self.tearDown();self.setUp()
                before={'minecraft:birch_planks':3,'minecraft:stick':2}
                c=self.observe(before,[PICK],blocks=[TABLE])['command']
                after={'minecraft:wooden_pickaxe':1}
                ev=self.proof(c,before,after)
                if corrupt=='ingredient':ev['inventory_after']['minecraft:stick']=2
                elif corrupt=='station':ev['station_opened']=False
                else:ev['crafted_delta']=0
                self.observe(after,blocks=[],results=[self.success(c,ev)])
                self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))

    def test_placement_requires_both_native_usage_and_consumption(self):
        inv={'minecraft:crafting_table':1}
        c=self.observe(inv,placement_spots=[SPOT])['command']
        ev=self.proof(c,inv,{})
        ev['used_delta']=0
        self.observe({},blocks=[TABLE],results=[self.success(c,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='placed'"))
        self.assertFalse(self.m.rows("SELECT * FROM Knowledge WHERE subject LIKE 'placement:%'"))

    def test_interrupted_placement_is_not_success_and_not_replayed_on_restart(self):
        inv={'minecraft:crafting_table':1}
        c=self.observe(inv,placement_spots=[SPOT])['command']
        self.engine=CognitiveEngine(self.m,self.writer)
        self.session=str(uuid4())
        new=self.observe(inv,placement_spots=[SPOT])['command']
        self.assertNotEqual(c['id'],new['id'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='placed'"))

    def test_no_station_no_capability_and_no_safe_spot_do_not_invent_actions(self):
        inv={'minecraft:birch_planks':3,'minecraft:stick':2}
        self.assertIsNone(self.observe(inv,[PICK])['command'])
        self.assertIsNone(self.observe({'minecraft:crafting_table':1},placement_spots=[])['command'])
        self.engine.last_plan[legacy.WORLD]=-1e30
        self.assertIsNone(self.step(blocks=[TABLE],recipes=[PICK],capabilities=[],
                                   player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory=inv))['command'])

    def test_food_slots_and_recipe_protocol_boundaries(self):
        food=dict(id='minecraft:bread',count=1,nutrition=5)
        player=Player(x=0,y=64,z=0,health=20,food=4,danger=False,inventory={},
                      foods=[dict(food,slot=i) for i in range(36)])
        self.assertEqual(player.foods[-1].slot,35)
        for change in ({'inputs':{'minecraft:stick':-2}}, {'station':None}, {'inputs':{'minecraft:stick':True}}):
            with self.assertRaises(ValidationError):RecipeOffer(**dict(PICK,**change))
        with self.assertRaises(ValidationError):PlacementSpot(x=1,y=64,z=0,support=dict(x=9,y=63,z=0))
        for bad in ('minecraft:chicken','minecraft:suspicious_stew','minecraft:chorus_fruit'):
            self.assertFalse(FoodAcquisitionManager().safe_id(bad))

    def test_failure_uses_cooldown_and_does_not_loop_impossible_recipe(self):
        inv={'minecraft:birch_planks':3,'minecraft:stick':2}
        c=self.observe(inv,[PICK],blocks=[TABLE])['command']
        response=self.observe(inv,[PICK],blocks=[TABLE],
                              results=[dict(id=c['id'],status='failed',reason='inventory_full',evidence={})])
        if response['command']:
            self.assertNotEqual(response['command']['action'],'craft_table')
        self.assertTrue(self.m.rows("SELECT * FROM Goals WHERE status='suspended'"))

    def test_remembered_placement_and_recipe_knowledge_are_world_isolated(self):
        inv={'minecraft:crafting_table':1}
        c=self.observe(inv,placement_spots=[SPOT])['command']
        self.observe({},results=[self.success(c,self.proof(c,inv,{}))])
        self.assertTrue(self.engine.crafting.remembered_table(self.engine.latest))
        distant=self.engine.latest.model_copy(deep=True)
        distant.player.x=1000
        self.assertFalse(self.engine.crafting.remembered_table(distant))
        self.engine.last_seen=-1e30;self.session=str(uuid4())
        self.step(world='d'*64,blocks=[])
        self.assertFalse(self.engine.crafting.remembered_table(self.engine.latest))
