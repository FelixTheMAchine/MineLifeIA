"""Mining acquisition regressions with temporary databases; no gameplay evidence."""
import json
import unittest
from uuid import uuid4

import test_mining_cooking as fixtures
from agent.engine import CognitiveEngine


class MiningPickupTest(unittest.TestCase):
    setUp=fixtures.MiningCookingTest.setUp
    tearDown=fixtures.MiningCookingTest.tearDown
    step=fixtures.MiningCookingTest.step
    success=fixtures.MiningCookingTest.success
    frame=fixtures.MiningCookingTest.frame
    set_clock=fixtures.MiningCookingTest.set_clock
    mine_proof=fixtures.MiningCookingTest.mine_proof
    caps=fixtures.CAPS+['explore']
    frontier=dict(x=9,y=64,z=0,safe=True,path_length=9)

    def mine(self):
        inv={fixtures.ORE['tool_id']:1}
        command=self.frame(inv,mining=[fixtures.ORE],caps=self.caps)['command']
        self.assertEqual(command['action'],'mine')
        return inv,command

    def item(self,**changes):
        return dict(dict(entity_id=str(uuid4()),x=2,y=64,z=0,
                         item_id='minecraft:cobblestone',count=1,edible=False),**changes)

    def intent(self):
        rows=self.m.rows("SELECT params FROM GoalPlans WHERE kind='mine' ORDER BY rowid DESC")
        return json.loads(rows[0]['params'])['acquisition']

    def pickup(self):
        inv,mine=self.mine();item=self.item()
        command=self.frame(inv,[self.success(mine,self.mine_proof(mine,inv))],items=[item],caps=self.caps)['command']
        self.assertEqual(command['action'],'pickup')
        return inv,item,command

    def proof(self,command):
        item=command['item'];item_id=item['item_id']
        return dict(server_verified=True,target={k:command['target'][k] for k in ('x','y','z')},
                    item_id=item_id,entity_id=item['entity_id'],inventory_before={},inventory_after={item_id:1},
                    entity_present_before=True,entity_present_after=False,entity_count_before=1,entity_count_after=0)

    def test_intention_precedes_removal_and_pickup_is_separate_fact(self):
        inv,command=self.mine()
        self.assertEqual(self.intent()['removal_command'],command['id'])
        self.assertFalse(self.intent()['removal_verified'])
        self.frame(inv,[self.success(command,self.mine_proof(command,inv))],caps=self.caps)
        self.assertTrue(self.intent()['removal_verified'])
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))

    def test_visible_resource_wins_over_exploration_and_other_mining(self):
        inv,item,command=self.pickup()
        self.assertEqual(command['item']['entity_id'],item['entity_id'])
        self.assertEqual(self.intent()['status'],'pending')

    def test_delayed_drop_holds_exploration_then_releases_without_fact(self):
        inv,command=self.mine()
        reply=self.frame(inv,[self.success(command,self.mine_proof(command,inv))],caps=self.caps,frontiers=[self.frontier])
        self.assertIsNone(reply['command'])
        for _ in range(3):reply=self.frame(inv,caps=self.caps,frontiers=[self.frontier])
        self.assertEqual(reply['command']['action'],'explore')
        self.assertEqual(self.intent()['status'],'unobserved')
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))

    def test_delayed_drop_holds_other_mining_until_bounded_wait_expires(self):
        inv,command=self.mine()
        other=dict(fixtures.ORE,x=3,tool_damage=1)
        reply=self.frame(inv,[self.success(command,self.mine_proof(command,inv))],mining=[other],caps=self.caps)
        for _ in range(3):
            self.assertIsNone(reply['command'])
            reply=self.frame(inv,mining=[other],caps=self.caps)
        self.assertEqual(reply['command']['action'],'mine')
        intents=self.m.rows("SELECT params FROM GoalPlans WHERE kind='mine' ORDER BY rowid")
        self.assertEqual(json.loads(intents[0]['params'])['acquisition']['status'],'unobserved')
        self.assertEqual(len(intents),2)

    def test_drop_observed_during_wait_wins_over_next_mining(self):
        inv,command=self.mine()
        other=dict(fixtures.ORE,x=3,tool_damage=1)
        reply=self.frame(inv,[self.success(command,self.mine_proof(command,inv))],mining=[other],caps=self.caps)
        self.assertIsNone(reply['command'])
        item=self.item()
        reply=self.frame(inv,mining=[other],items=[item],caps=self.caps)
        self.assertEqual(reply['command']['action'],'pickup')
        self.assertEqual(reply['command']['item']['entity_id'],item['entity_id'])
        self.assertEqual(len(self.m.rows("SELECT 1 FROM GoalPlans WHERE kind='mine'")),1)

    def test_failed_removal_does_not_start_a_drop_wait(self):
        inv,command=self.mine()
        reply=self.frame(inv,[dict(id=command['id'],status='failed',reason='path_obstructed',evidence={})],
                         mining=[dict(fixtures.ORE,x=3)],caps=self.caps)
        self.assertEqual(reply['command']['action'],'mine')

    def test_pickup_cooldown_holds_exploration_and_two_failures_are_bounded(self):
        inv,item,command=self.pickup()
        for attempt in range(2):
            reply=self.frame(inv,[dict(id=command['id'],status='failed',reason='path_obstructed',evidence={})],
                             items=[item],caps=self.caps,frontiers=[self.frontier])
            if attempt==0:
                self.assertIsNone(reply['command'])
                self.m.db.execute("UPDATE GoalPlans SET cooldown=0 WHERE kind='pickup'")
                command=self.frame(inv,items=[item],caps=self.caps)['command']
                self.assertEqual(command['action'],'pickup')
            else:
                self.assertEqual(reply['command']['action'],'explore')
        self.assertEqual(self.intent()['status'],'exhausted')
        self.assertEqual(self.intent()['attempts'],2)

    def test_cancel_restart_keeps_intention_and_reobserves_uuid(self):
        inv,item,command=self.pickup()
        self.frame(inv,[dict(id=command['id'],status='cancelled',reason='user_pause',evidence={})],active=False,caps=self.caps)
        self.assertEqual(self.intent()['attempts'],0)
        self.engine=CognitiveEngine(self.m,self.writer);self.set_clock();self.session=str(uuid4())
        self.m.db.execute("UPDATE GoalPlans SET cooldown=0 WHERE kind='pickup'")
        resumed=self.frame(inv,items=[item],caps=self.caps)['command']
        self.assertEqual(resumed['action'],'pickup')
        self.assertNotEqual(resumed['id'],command['id'])
        self.assertEqual(resumed['item']['entity_id'],item['entity_id'])

    def test_full_inventory_does_not_invent_collection(self):
        inv,item,command=self.pickup()
        self.frame(inv,[dict(id=command['id'],status='failed',reason='inventory_full',evidence={})],items=[item],caps=self.caps)
        self.assertEqual(self.intent()['status'],'exhausted')
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))

    def test_success_correlates_intention_uuid_and_pickup_command_without_origin_claim(self):
        inv,item,command=self.pickup();proof=self.proof(command)
        self.frame({**inv,item['item_id']:1},[self.success(command,proof)],caps=self.caps)
        self.assertEqual(self.intent()['status'],'acquired')
        self.assertEqual(self.intent()['entity_id'],item['entity_id'])
        self.assertEqual(self.intent()['pickup_command'],command['id'])
        self.assertEqual(self.intent()['pickup_session'],self.session)
        self.assertEqual(len(self.m.rows("SELECT 1 FROM Events WHERE type='collected'")),1)

    def test_partial_stack_pickup_records_only_verified_inventory_gain(self):
        inv,mine=self.mine();item=self.item(count=3)
        command=self.frame(inv,[self.success(mine,self.mine_proof(mine,inv))],items=[item],caps=self.caps)['command']
        self.assertEqual(command['action'],'pickup')
        proof=self.proof(command)
        proof.update(entity_present_after=True,entity_count_before=3,entity_count_after=2)
        self.frame({**inv,item['item_id']:1},[self.success(command,proof)],items=[{**item,'count':2}],caps=self.caps)
        self.assertEqual(self.intent()['status'],'acquired')
        events=self.m.rows("SELECT description,evidence FROM Events WHERE type='collected'")
        self.assertEqual(len(events),1)
        self.assertIn('1 unidade(s)',events[0]['description'])
        self.assertEqual(json.loads(events[0]['evidence'])['entity_count_after'],2)

    def test_wrong_uuid_or_impossible_delta_never_acquires(self):
        inv,item,command=self.pickup();proof=self.proof(command)
        proof['entity_id']=str(uuid4())
        self.frame(inv,[self.success(command,proof)],caps=self.caps)
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))
        self.assertEqual(self.intent()['status'],'pending')

    def test_inventory_gain_cannot_exceed_entity_reduction(self):
        inv,item,command=self.pickup();proof=self.proof(command)
        proof['inventory_after'][item['item_id']]=2
        self.frame(inv,[self.success(command,proof)],caps=self.caps)
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))

    def test_safety_pause_preserves_pending_acquisition(self):
        inv,command=self.mine()
        self.frame(inv,[self.success(command,self.mine_proof(command,inv))],caps=self.caps,active=False)
        self.assertEqual(self.intent()['status'],'pending')
        self.assertIsNone(self.frame(inv,items=[self.item()],caps=self.caps,control_state='EMERGENCY_STOP')['command'])
        self.assertEqual(self.intent()['status'],'pending')

    def test_out_of_range_drop_does_not_hold_exploration_forever(self):
        inv,command=self.mine();item=self.item(x=11)
        reply=self.frame(inv,[self.success(command,self.mine_proof(command,inv))],caps=self.caps,items=[item],frontiers=[self.frontier])
        for _ in range(3):reply=self.frame(inv,caps=self.caps,items=[item],frontiers=[self.frontier])
        self.assertEqual(reply['command']['action'],'explore')
        self.assertEqual(self.intent()['status'],'unobserved')

    def test_missing_pickup_capability_expires_acquisition_without_busy_wait(self):
        inv,command=self.mine();caps=[c for c in self.caps if c!='pickup']
        reply=self.frame(inv,[self.success(command,self.mine_proof(command,inv))],caps=caps,items=[self.item()],frontiers=[self.frontier])
        for _ in range(3):reply=self.frame(inv,caps=caps,items=[self.item()],frontiers=[self.frontier])
        self.assertEqual(reply['command']['action'],'explore')
        self.assertEqual(self.intent()['status'],'unobserved')

    def test_empty_hand_wood_mining_is_followed_by_observed_log_pickup(self):
        caps=self.caps+['craft','place','craft_table']
        offer=dict(x=2,y=64,z=0,id='minecraft:oak_log',tool_id='minecraft:air',tool_slot=0,
                   tool_damage=0,tool_max_damage=0,tool_wear=0,tool_required=False,tool_suitable=True)
        mine=self.frame(mining=[offer],caps=caps)['command']
        self.assertEqual(mine['action'],'mine')
        proof=dict(server_verified=True,target={k:mine['target'][k] for k in ('x','y','z')},
                   before_block=offer['id'],after_block='minecraft:air',mined_delta=1,tool_id='minecraft:air',
                   tool_suitable=True,tool_before_damage=0,tool_after_damage=0,inventory_before={},inventory_after={})
        item=self.item(item_id='minecraft:oak_log')
        pickup=self.frame(results=[self.success(mine,proof)],items=[item],caps=caps,frontiers=[self.frontier])['command']
        self.assertEqual(pickup['action'],'pickup')
        self.assertEqual(pickup['item']['entity_id'],item['entity_id'])
        self.assertTrue(self.intent()['removal_verified'])
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))

    def test_disappearance_without_inventory_gain_keeps_acquisition_unverified(self):
        inv,item,command=self.pickup();proof=self.proof(command)
        proof['inventory_after']={}
        self.frame(inv,[self.success(command,proof)],caps=self.caps)
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))
        self.assertNotEqual(self.intent()['status'],'acquired')

    def test_timeout_can_retry_a_new_observed_uuid_without_attributing_origin(self):
        inv,item,command=self.pickup()
        replacement=self.item()
        retry=self.frame(inv,[dict(id=command['id'],status='failed',reason='pickup_timeout',evidence={})],
                         items=[replacement],caps=self.caps)['command']
        self.assertEqual(retry['action'],'pickup')
        self.assertEqual(retry['item']['entity_id'],replacement['entity_id'])
        self.assertEqual(self.intent()['attempts'],1)
        self.assertFalse(self.m.rows("SELECT 1 FROM Events WHERE type='collected'"))
        self.frame(inv,[dict(id=retry['id'],status='failed',reason='no_safe_path',evidence={})],caps=self.caps)
        self.assertEqual(self.intent()['attempts'],2)
        self.assertEqual(self.intent()['status'],'exhausted')

    def test_stack_count_changes_cannot_reset_failed_uuid_budget(self):
        inv,item,command=self.pickup()
        for _ in range(2):
            self.frame(inv,[dict(id=command['id'],status='failed',reason='item_entity_changed',evidence={})],caps=self.caps)
            self.m.db.execute("UPDATE GoalPlans SET cooldown=0 WHERE kind='pickup'")
            if self.intent()['attempts']<2:
                command=self.frame(inv,items=[item],caps=self.caps)['command']
        changed={**item,'count':2}
        reply=self.frame(inv,items=[changed],caps=self.caps,frontiers=[self.frontier])
        self.assertEqual(reply['command']['action'],'explore')

    def test_urgent_food_interrupts_pickup_and_preserves_intention(self):
        inv,item,command=self.pickup()
        food=dict(id='minecraft:bread',slot=0,count=1,nutrition=5)
        reply=self.frame({**inv,'minecraft:bread':1},food=6,foods=[food],caps=self.caps,items=[item])
        self.assertEqual(reply['interrupt'],command['id'])
        self.assertIsNone(reply['command'])
        reply=self.frame({**inv,'minecraft:bread':1},
                         [dict(id=command['id'],status='cancelled',reason='urgent_food',evidence={})],
                         food=6,foods=[food],caps=self.caps,items=[item])
        self.assertEqual(reply['command']['action'],'eat')
        self.assertEqual(self.intent()['status'],'pending')
        self.assertEqual(self.intent()['attempts'],0)


if __name__=='__main__':unittest.main()
