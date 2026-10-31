"""Material dependencies use synthetic observations; they are not gameplay proofs."""
import unittest
import test_pipeline as base
import test_workstations as work
from agent.protocol import Step
from agent.crafting import has_tool

STONE=work.recipe('stone_pickaxe',{'minecraft:cobblestone':3,'minecraft:stick':2},'stone_pickaxe',grid=3)
IRON=work.recipe('iron_pickaxe',{'minecraft:iron_ingot':3,'minecraft:stick':2},'iron_pickaxe',grid=3)


class MaterialsTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success
    observe=work.WorkstationsTest.observe
    proof=work.WorkstationsTest.proof

    def test_sticks_unlock_upgrade_even_with_wooden_tools_already_present(self):
        inv={'minecraft:wooden_pickaxe':1,'minecraft:wooden_axe':1,'minecraft:cobblestone':3,'minecraft:birch_planks':4}
        c=self.observe(inv,[work.STICKS],blocks=[work.TABLE])['command']
        self.assertEqual(c['recipe']['output_id'],'minecraft:stick')
        after={**inv,'minecraft:birch_planks':2,'minecraft:stick':4}
        upgrade=self.observe(after,[STONE],blocks=[work.TABLE],results=[self.success(c,self.proof(c,inv,after))])['command']
        self.assertEqual(upgrade['recipe']['output_id'],'minecraft:stone_pickaxe')

    def test_iron_tools_use_real_advertised_ingredients_and_stock(self):
        inv={'minecraft:stone_pickaxe':1,'minecraft:wooden_axe':1,'minecraft:iron_ingot':3,'minecraft:birch_planks':2}
        c=self.observe(inv,[work.STICKS],blocks=[work.TABLE])['command']
        after={**inv,'minecraft:birch_planks':0,'minecraft:stick':4}
        iron=self.observe(after,[IRON],blocks=[work.TABLE],results=[self.success(c,self.proof(c,inv,after))])['command']
        self.assertEqual(iron['action'],'craft_table');self.assertEqual(iron['recipe']['output_id'],'minecraft:iron_pickaxe')
        final={**after,'minecraft:iron_ingot':0,'minecraft:stick':2,'minecraft:iron_pickaxe':1}
        self.observe(final,[IRON,STONE,work.PICK],blocks=[work.TABLE],results=[self.success(iron,self.proof(iron,after,final))])
        self.assertTrue(self.m.rows("SELECT * FROM Knowledge WHERE subject='recipe:minecraft:iron_pickaxe' AND status='confirmed'"))
        self.assertEqual(self.engine.crafting.demand(self.engine.latest,'minecraft:iron_pickaxe'),0)
        self.assertEqual(self.engine.crafting.demand(self.engine.latest,'minecraft:stone_pickaxe'),0)

    def test_worn_or_enchanted_tools_do_not_mask_replacement_need(self):
        self.observe({},[])
        data=self.engine.latest.model_dump(mode='json');data['player']['inventory']={'minecraft:stone_pickaxe':1,'minecraft:iron_pickaxe':1}
        data['player']['tools']=[dict(id='minecraft:stone_pickaxe',slot=0,damage=130,max_damage=131,kind='pickaxe',usable=False),
                                 dict(id='minecraft:iron_pickaxe',slot=1,damage=0,max_damage=250,kind='pickaxe',usable=False)]
        s=Step(**data)
        self.assertFalse(has_tool(s,'pickaxe'))
        self.assertEqual(self.engine.crafting.demand(s,'minecraft:stone_pickaxe'),2)
        self.assertGreater(self.engine.mining.demand(s,'minecraft:cobblestone'),0)
        data['player']['tools'][1]['usable']=True;s=Step(**data)
        self.assertTrue(has_tool(s,'pickaxe'))
        self.assertEqual(self.engine.crafting.demand(s,'minecraft:stone_pickaxe'),0)

    def test_insufficient_material_or_missing_station_cannot_craft_upgrade(self):
        inv={'minecraft:wooden_pickaxe':1,'minecraft:wooden_axe':1,'minecraft:iron_ingot':2,'minecraft:stick':2}
        command=self.observe(inv,[IRON],blocks=[work.TABLE])['command']
        # Observe an unfamiliar workstation independently of an impossible recipe.
        self.assertEqual(command['action'],'approach')
        self.assertEqual(command['target']['id'],'minecraft:crafting_table')
        self.assertNotIn('recipe',command)
        plans=self.m.rows('SELECT kind,skill FROM GoalPlans')
        self.assertEqual(plans,[dict(kind='observe',skill='observe_block')])
        self.assertFalse(self.engine.crafting.proposals(self.engine.latest,self.engine.motivation.values(base.WORLD)))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='crafted'"))

    def test_missing_station_refuses_upgrade_even_with_all_ingredients(self):
        # Separate fixture: a pending approach from another case must not mask this check.
        inv={'minecraft:wooden_pickaxe':1,'minecraft:wooden_axe':1,'minecraft:iron_ingot':3,'minecraft:stick':2}
        self.assertIsNone(self.observe(inv,[IRON],blocks=[])['command'])
        self.assertFalse(self.m.rows('SELECT * FROM Commands'))
        self.assertFalse(self.m.rows("SELECT * FROM Knowledge WHERE subject='recipe:minecraft:iron_pickaxe'"))
