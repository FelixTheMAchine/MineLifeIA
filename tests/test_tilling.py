"""Synthetic planning/evidence contracts. These tests do not assert gameplay execution."""
import unittest
from types import SimpleNamespace
from agent.agriculture import AgriculturePlanner
from agent.protocol import TillingOffer, FarmlandObservation
from pydantic import ValidationError


class TillingTest(unittest.TestCase):
    def state(self):
        site=TillingOffer(x=2,y=63,z=0,id='minecraft:dirt',tool_id='minecraft:wooden_hoe',
                         tool_slot=10,tool_damage=0,tool_max_damage=59,water=dict(x=3,y=63,z=0))
        return SimpleNamespace(dimension='minecraft:overworld',time=1000,capabilities=['plant','till'],
                               farmland=[],tilling=[site],player=SimpleNamespace(food=20,danger=False,
                               inventory={'minecraft:wheat_seeds':2},foods=[SimpleNamespace(count=2,nutrition=3)]))

    def test_till_keeps_food_seed_and_durability_reserves(self):
        s=self.state();planner=AgriculturePlanner(None)
        p=planner.proposals(s,{})[0]
        self.assertEqual(p['kind'],'till');self.assertEqual(p['params']['tilling']['tool_slot'],10)
        for change in ('seed','food','hunger','danger','night','capability','durability'):
            with self.subTest(change=change):
                s=self.state()
                if change=='seed':s.player.inventory['minecraft:wheat_seeds']=1
                elif change=='food':s.player.foods=[]
                elif change=='hunger':s.player.food=12
                elif change=='danger':s.player.danger=True
                elif change=='night':s.time=13000
                elif change=='capability':s.capabilities=['till']
                elif change=='durability':s.tilling[0].tool_damage=58
                self.assertFalse(planner.proposals(s,{}))

    def test_protocol_rejects_far_water_and_worn_hoe(self):
        payload=self.state().tilling[0].model_dump()
        for updates in (dict(water=dict(x=7,y=63,z=0)),dict(water=dict(x=3,y=62,z=0)),dict(tool_damage=58)):
            with self.assertRaises(ValidationError):TillingOffer(**(payload|updates))
        self.assertEqual(FarmlandObservation(x=1,y=64,z=0).moisture,-1)

    def test_tilling_requires_real_use_wear_water_and_inventory_preservation(self):
        s=self.state();cmd=AgriculturePlanner(None).proposals(s,{})[0]['params']
        ev=dict(server_verified=True,dimension=s.dimension,before_block='minecraft:dirt',after_block='minecraft:farmland',
                water=cmd['tilling']['water'],water_observed=True,moisture=0,tool_id='minecraft:wooden_hoe',
                tool_plain=True,tool_damage_before=0,tool_damage_after=1,used_delta=1,inventory_before={'minecraft:wooden_hoe':1},inventory_after={'minecraft:wooden_hoe':1})
        self.assertTrue(AgriculturePlanner.validate_till(s,cmd,ev))
        for key,value in dict(server_verified=False,water_observed=False,used_delta=0,tool_damage_after=0,tool_plain=False,
                              moisture=8,after_block='minecraft:dirt',inventory_after={}).items():
            with self.subTest(key=key):self.assertFalse(AgriculturePlanner.validate_till(s,cmd,ev|{key:value}))


if __name__=='__main__':unittest.main()
