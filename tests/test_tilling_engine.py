"""Engine integration with synthetic observations, not a Minecraft gameplay test."""
import unittest
import test_pipeline as base


SOIL=dict(x=2,y=63,z=0)
WATER=dict(x=4,y=63,z=0)
OFFER=dict(**SOIL,id='minecraft:dirt',tool_id='minecraft:wooden_hoe',tool_slot=0,
           tool_damage=0,tool_max_damage=59,water=WATER)


class TillingEngineTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def frame(self,results=None,**kw):
        self.engine.last_plan[base.WORLD]=-1e30
        payload=dict(blocks=[],capabilities=['till','plant'],tilling=[OFFER],
                     player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,
                                 inventory={'minecraft:wheat_seeds':2,'minecraft:wooden_hoe':1,'minecraft:bread':2},
                                 foods=[dict(id='minecraft:bread',slot=1,count=2,nutrition=5)]))
        return self.step(results,**(payload|kw))

    def test_till_then_plant_keeps_physical_facts_separate(self):
        till=self.frame()['command']
        self.assertEqual(till['action'],'till')
        inv={'minecraft:wheat_seeds':2,'minecraft:wooden_hoe':1,'minecraft:bread':2}
        evidence=dict(target=SOIL,server_verified=True,dimension='minecraft:overworld',
                      before_block='minecraft:dirt',after_block='minecraft:farmland',water=WATER,
                      water_observed=True,moisture=0,tool_id='minecraft:wooden_hoe',tool_damage_before=0,
                      tool_damage_after=1,tool_plain=True,used_delta=1,inventory_before=inv,inventory_after=inv)
        plant=self.frame([self.success(till,evidence)],tilling=[],
                         farmland=[dict(x=2,y=64,z=0,moisture=7,water=WATER)])['command']
        self.assertEqual(plant['action'],'plant')
        self.assertEqual(plant['target'],dict(x=2,y=64,z=0,id='minecraft:wheat'))
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='soil_tilled'")),1)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('planted','crop_harvested','collected')"))

    def test_pause_and_foreign_evidence_do_not_claim_tilling(self):
        self.assertIsNone(self.frame(active=False)['command'])
        till=self.frame()['command']
        self.frame([self.success(till,dict(target=SOIL,server_verified=True,dimension='minecraft:the_nether'))])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='soil_tilled'"))

    def test_measured_dry_soil_waits_for_observed_hydration(self):
        self.assertIsNone(self.frame(tilling=[],farmland=[dict(x=2,y=64,z=0,moisture=0,water=WATER)])['command'])
        self.assertEqual(self.frame(tilling=[],farmland=[dict(x=2,y=64,z=0,moisture=1,water=WATER)])['command']['action'],'plant')

    def test_seed_reserve_requests_real_hoe_recipe_before_soil_offer(self):
        station=dict(x=2,y=64,z=0)
        recipe=dict(id='minecraft:wooden_hoe',input_id='minecraft:oak_planks',input_count=2,
                    inputs={'minecraft:oak_planks':2,'minecraft:stick':2},output_id='minecraft:wooden_hoe',
                    output_count=1,grid=3,station=station)
        player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,
                    inventory={'minecraft:wooden_pickaxe':1,'minecraft:wooden_axe':1,
                               'minecraft:wheat_seeds':2,'minecraft:oak_planks':2,'minecraft:stick':2})
        cmd=self.frame(tilling=[],recipes=[recipe],capabilities=['craft_table','till','plant'],
                       blocks=[dict(**station,id='minecraft:crafting_table',log=False)],player=player)['command']
        self.assertEqual(cmd['action'],'craft_table')
        self.assertEqual(cmd['recipe']['output_id'],'minecraft:wooden_hoe')
