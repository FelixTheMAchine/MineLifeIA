"""Synthetic correlated farm-cycle contracts; no real Minecraft execution is claimed."""
import json
import unittest
from uuid import uuid4
from datetime import datetime,timedelta,timezone
import test_pipeline as base

SITE=dict(x=2,y=64,z=0)
SOIL=dict(x=2,y=63,z=0)
WATER=dict(x=3,y=63,z=0)
CAPS=['plant','till','harvest','approach','pickup']


class FarmCycleTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def frame(self,seeds=1,results=None,**kw):
        self.engine.last_plan[base.WORLD]=-1e30
        return self.step(results,capabilities=CAPS,blocks=kw.pop('blocks',[]),
                         player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,
                                     inventory={'minecraft:wheat_seeds':seeds,'minecraft:bread':3,'minecraft:wooden_hoe':1},
                                     foods=[dict(id='minecraft:bread',slot=1,count=3,nutrition=5)]),**kw)

    def drops(self):
        return [dict(entity_id=str(uuid4()),x=2.5,y=64,z=.5,item_id='minecraft:wheat_seeds',count=3,edible=False),
                dict(entity_id=str(uuid4()),x=1,y=64,z=0,item_id='minecraft:wheat',count=1,edible=False)]

    def harvest_event(self,**updates):
        ev=dict(target=SITE,dimension='minecraft:overworld',server_verified=True,before_block='minecraft:wheat',
                after_block='minecraft:air',before_crop_mature=True,mined_delta=1)|updates
        return self.m.event(base.WORLD,self.session,1,'crop_harvested','Synthetic verified fixture',True,ev,str(uuid4()))

    def test_recent_harvest_selects_seed_reserve_before_closer_wheat(self):
        self.harvest_event();self.frame(active=False,items=self.drops())
        item=self.engine.agriculture.pending_drop(self.engine.latest)
        self.assertEqual(item.item_id,'minecraft:wheat_seeds')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))

    def test_unrelated_old_foreign_or_unverified_events_do_not_select(self):
        for mutation in ('dimension','far','old','unverified','session'):
            with self.subTest(mutation=mutation):
                self.m.db.execute("DELETE FROM Events WHERE type='crop_harvested'")
                eid=self.harvest_event(**({'dimension':'minecraft:the_nether'} if mutation=='dimension' else
                                           {'target':dict(x=50,y=64,z=0)} if mutation=='far' else {}))
                if mutation=='old':self.m.db.execute('UPDATE Events SET timestamp=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),eid))
                if mutation=='unverified':self.m.db.execute('UPDATE Events SET verified=0 WHERE id=?',(eid,))
                if mutation=='session':self.m.db.execute('UPDATE Events SET session=? WHERE id=?',(str(uuid4()),eid))
                self.frame(active=False,items=self.drops())
                self.assertIsNone(self.engine.agriculture.pending_drop(self.engine.latest))

    def test_prepared_soil_two_harvests_seed_pickups_and_replant(self):
        offer=dict(**SOIL,id='minecraft:dirt',tool_id='minecraft:wooden_hoe',tool_slot=2,tool_damage=0,tool_max_damage=59,water=WATER)
        till=self.frame(2,tilling=[offer])['command'];self.assertEqual(till['action'],'till')
        stock={'minecraft:wheat_seeds':2,'minecraft:bread':3,'minecraft:wooden_hoe':1}
        ev=dict(target=SOIL,dimension='minecraft:overworld',server_verified=True,before_block='minecraft:dirt',after_block='minecraft:farmland',
                water=WATER,water_observed=True,moisture=7,tool_id='minecraft:wooden_hoe',tool_plain=True,
                tool_damage_before=0,tool_damage_after=1,used_delta=1,inventory_before=stock,inventory_after=stock)
        farmland=SITE|dict(moisture=7,water=WATER)
        plant=self.frame(2,[self.success(till,ev)],farmland=[farmland])['command']
        seeds=2
        for _ in range(2):
            self.assertEqual(plant['action'],'plant')
            proof=dict(target=SITE,server_verified=True,dimension='minecraft:overworld',before_block='minecraft:air',after_block='minecraft:wheat',
                       soil='minecraft:farmland',crop_age=0,used_delta=1,inventory_before={'minecraft:wheat_seeds':seeds},inventory_after={'minecraft:wheat_seeds':seeds-1})
            self.frame(seeds-1,[self.success(plant,proof)]);seeds-=1
            crop=SITE|dict(id='minecraft:wheat',log=False,harvestable=True)
            approach=self.frame(seeds,blocks=[crop])['command']
            harvest=self.frame(seeds,[self.success(approach,dict(target=SITE,in_reach=True))],blocks=[crop])['command']
            proof=dict(target=SITE,server_verified=True,dimension='minecraft:overworld',before_block='minecraft:wheat',after_block='minecraft:air',before_crop_mature=True,mined_delta=1)
            drops=self.drops()
            pickup=self.frame(seeds,[self.success(harvest,proof)],farmland=[farmland],items=drops)['command']
            self.assertEqual(pickup['action'],'pickup');self.assertEqual(pickup['item']['item_id'],'minecraft:wheat_seeds')
            proof=dict(target=SITE,server_verified=True,item_id='minecraft:wheat_seeds',entity_id=drops[0]['entity_id'],
                       entity_present_before=True,entity_present_after=False,entity_count_before=3,entity_count_after=0,
                       inventory_before={'minecraft:wheat_seeds':seeds},inventory_after={'minecraft:wheat_seeds':seeds+3})
            seeds+=3
            plant=self.frame(seeds,[self.success(pickup,proof)],farmland=[farmland])['command']
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='crop_harvested'")),2)
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='collected'")),2)
        self.assertTrue(all(json.loads(r['evidence'])['inventory_after']['minecraft:wheat_seeds']>
                            json.loads(r['evidence'])['inventory_before']['minecraft:wheat_seeds']
                            for r in self.m.rows("SELECT evidence FROM Events WHERE type='collected'")))


if __name__=='__main__':unittest.main()
