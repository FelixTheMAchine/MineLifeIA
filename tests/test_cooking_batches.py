"""Synthetic residual-heat and persistent unit-chain contracts, never gameplay evidence."""
import unittest
import test_mining_cooking as fixtures
from agent.engine import CognitiveEngine


class CookingBatchesTest(unittest.TestCase):
    setUp=fixtures.MiningCookingTest.setUp
    tearDown=fixtures.MiningCookingTest.tearDown
    set_clock=fixtures.MiningCookingTest.set_clock
    step=fixtures.MiningCookingTest.step
    success=fixtures.MiningCookingTest.success
    frame=fixtures.MiningCookingTest.frame
    furnace_frame=fixtures.MiningCookingTest.furnace_frame
    snapshot=fixtures.MiningCookingTest.snapshot
    proof=fixtures.MiningCookingTest.proof
    load=fixtures.MiningCookingTest.load

    def next_unit(self,burn=1200):
        inv=self.load();self.t+=6
        inspect=self.furnace_frame(inv)['command']
        ready=self.snapshot(inv,output=1,lit=True)|dict(burn_remaining=burn,cook_progress=0)
        take=self.furnace_frame(inv,[self.success(inspect,self.proof(inspect,ready))])['command']
        stock=inv|{'minecraft:cooked_chicken':1}
        empty=self.snapshot(stock,lit=True)|dict(burn_remaining=burn-10,cook_progress=0)
        response=self.furnace_frame(stock,[self.success(take,self.proof(take,ready,empty,2))])
        return stock,empty,response

    def test_next_unit_persists_and_consumes_only_input_with_residual_heat(self):
        stock,empty,response=self.next_unit();inspect=response['command']
        self.assertEqual(inspect['action'],'furnace_inspect')
        self.assertIsNone(inspect['furnace']['recipe']['fuel_id'])
        load=self.furnace_frame(stock,[self.success(inspect,self.proof(inspect,empty))])['command']
        self.assertEqual(load['action'],'furnace_load')
        after_stock={'minecraft:cooked_chicken':1}
        loaded=self.snapshot(after_stock,inputs=1,lit=True)|dict(burn_remaining=1100,cook_progress=8)
        self.furnace_frame(after_stock,[self.success(load,self.proof(load,empty,loaded))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='furnace_loaded'")),2)
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='cooked'")),1)

    def test_restart_requires_inspection_and_expired_heat_never_loads(self):
        stock,empty,_=self.next_unit()
        self.engine=CognitiveEngine(self.m,self.writer);self.set_clock()
        # An interrupted inspection must be acknowledged before the engine schedules again.
        self.m.db.execute("UPDATE Commands SET status='cancelled' WHERE status='sent'")
        inspect=self.furnace_frame(stock)['command']
        self.assertEqual(inspect['action'],'furnace_inspect')
        expired=empty|dict(lit=False,burn_remaining=0)
        response=self.furnace_frame(stock,[self.success(inspect,self.proof(inspect,expired))])
        self.assertIsNone(response['command'])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='furnace_loaded'")),1)

    def test_no_continuation_without_authoritative_sufficient_heat(self):
        self.next_unit(burn=210)
        self.assertEqual(len(self.m.rows('SELECT * FROM FurnaceJobs')),1)


if __name__=='__main__':unittest.main()
