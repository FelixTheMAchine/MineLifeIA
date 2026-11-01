"""Food/seed reserves and emergency retrieval using synthetic native snapshots."""
import unittest
import test_storage as storage_fixtures
from test_storage import snapshot, expected_transfer
import test_storage_engine as engine_fixtures
from agent.storage import ACTIONS


class FoodReservesTest(unittest.TestCase):
    setUp=storage_fixtures.StorageTest.setUp
    tearDown=storage_fixtures.StorageTest.tearDown
    command=storage_fixtures.StorageTest.command
    proof=storage_fixtures.StorageTest.proof
    inspected=storage_fixtures.StorageTest.inspected

    def test_excess_food_and_seeds_deposit_only_above_reserves(self):
        a=self.inspected(snapshot({0:('minecraft:bread',5),1:('minecraft:wheat_seeds',10),2:('minecraft:potato',8)}))
        for _ in range(6):
            cmd=self.command(self.manager.propose(self.s));self.assertEqual(cmd['action'],'storage_deposit')
            self.manager.prepare_command(self.s,cmd)
            b=expected_transfer(a,cmd['action'],cmd['storage'])
            self.manager.accept(self.s,cmd,self.proof(cmd,a,b),'transfer')
            self.s.player.inventory=b['inventory'].copy();a=b
        self.assertEqual(self.s.player.inventory,{'minecraft:bread':3,'minecraft:wheat_seeds':8,'minecraft:potato':6})
        self.assertIsNone(self.manager.propose(self.s))

    def test_food_demand_is_absolute_across_mixed_food_types(self):
        a=self.inspected(snapshot({0:('minecraft:bread',1)},{0:('minecraft:cooked_cod',3)}))
        for _ in range(2):
            cmd=self.command(self.manager.propose(self.s,food_only=True));self.assertEqual(cmd['action'],'storage_withdraw')
            self.manager.prepare_command(self.s,cmd);b=expected_transfer(a,cmd['action'],cmd['storage'])
            self.manager.accept(self.s,cmd,self.proof(cmd,a,b),'food');self.s.player.inventory=b['inventory'].copy();a=b
        self.assertIsNone(self.manager.propose(self.s,food_only=True))
        self.assertEqual(self.s.player.inventory,{'minecraft:bread':1,'minecraft:cooked_cod':2})

    def test_hunger_mode_never_deposits_or_withdraws_construction_material(self):
        self.inspected(snapshot({0:('minecraft:dirt',3)},{0:('minecraft:stick',4)}))
        self.assertIsNone(self.manager.propose(self.s,food_only=True))


class EmergencyFoodStorageTest(unittest.TestCase):
    setUp=engine_fixtures.StorageEngineTest.setUp
    tearDown=engine_fixtures.StorageEngineTest.tearDown
    step=engine_fixtures.StorageEngineTest.step
    frame=engine_fixtures.StorageEngineTest.frame
    success=engine_fixtures.StorageEngineTest.success
    proof=engine_fixtures.StorageEngineTest.proof
    set_clock=engine_fixtures.StorageEngineTest.set_clock

    def test_hungry_agent_revalidates_withdraws_then_eats_observed_food(self):
        a=snapshot({}, {0:('minecraft:bread',2)})
        caps=list(ACTIONS)+['eat']
        inspect=self.frame({},food=4,capabilities=caps)['command']
        self.assertEqual(inspect['action'],'storage_inspect')
        take=self.frame({},[self.success(inspect,self.proof(inspect,a))],food=4,capabilities=caps)['command']
        self.assertEqual(take['action'],'storage_withdraw');self.assertEqual(take['storage']['item_id'],'minecraft:bread')
        b=expected_transfer(a,take['action'],take['storage'])
        player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory=b['inventory'],
                    foods=[dict(id='minecraft:bread',slot=9,count=1,nutrition=5)])
        meal=self.frame(b['inventory'],[self.success(take,self.proof(take,a,b))],player=player,capabilities=caps)['command']
        self.assertEqual(meal['action'],'eat')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('ate','collected')"))
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='storage_withdrawn'")),1)
