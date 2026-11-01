"""Synthetic storage proofs and SQLite recovery; these tests do not execute Minecraft."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
from agent.memory import MemoryManager
from agent.storage import StorageManager, SCHEMA, ACTIONS, MATERIALS, cell, content, expected_transfer, valid_snapshot

POS=dict(x=2,y=64,z=0)
DIM='minecraft:overworld'
ITEM='minecraft:dirt'


def stack(item='minecraft:air',count=0,standard=True):
    return dict(id=item,count=count,components='' if not count else '{id:"'+item+'",count:1}',standard=standard)


def snapshot(player=None,chest=None,sync=1):
    cells=[stack() for _ in range(36)];slots=[stack() for _ in range(27)]
    for index,value in (player or {}).items():cells[index]=stack(*value)
    for index,value in (chest or {}).items():slots[index]=stack(*value)
    inv={}
    for c in cells:
        if c['count']:inv[c['id']]=inv.get(c['id'],0)+c['count']
    return dict(station=POS.copy(),dimension=DIM,station_opened=True,cursor_empty=True,sync_id=sync,
                slots=slots,player_slots=cells,inventory=inv)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.m=MemoryManager(Path(self.tmp.name)/'memory.sqlite')
        self.m.db.executescript(SCHEMA);self.t=100
        self.manager=StorageManager(self.m,clock=lambda:self.t)
        self.s=NS(world='f'*64,dimension=DIM,session=uuid4(),capabilities=list(ACTIONS),time=100,
                  player=NS(x=0,y=64,z=0,danger=False,inventory={ITEM:3}),storage=[NS(**POS)],recipes=[],placement_spots=[])

    def tearDown(self):
        self.m.close();self.tmp.cleanup()

    def command(self,proposal):
        return dict(id=str(uuid4()),action=proposal['kind'],**proposal['params'])

    def proof(self,cmd,before,after=None):
        return dict(server_verified=True,job_id=cmd['storage']['job_id'],before=copy.deepcopy(before),
                    after=copy.deepcopy(before if after is None else after))

    def inspected(self,snap=None):
        snap=snap or snapshot({0:(ITEM,3)})
        self.s.player.inventory=snap['inventory'].copy()
        cmd=self.command(self.manager.propose(self.s));self.assertEqual(cmd['action'],'storage_inspect')
        self.manager.accept(self.s,cmd,self.proof(cmd,snap),'inspection')
        return snap

    def intent(self):
        snap=self.inspected()
        cmd=self.command(self.manager.propose(self.s));self.assertEqual(cmd['action'],'storage_deposit')
        self.manager.prepare_command(self.s,cmd)
        return cmd,snap,expected_transfer(snap,cmd['action'],cmd['storage'])

    def test_exact_deposit_and_hotbar_slot_mapping(self):
        cmd,a,b=self.intent()
        self.assertEqual(cmd['storage']['source_slot'],54)
        a['sync_id']=b['sync_id']=2
        ev=self.proof(cmd,a,b)
        self.assertTrue(self.manager.validate(self.s,cmd,ev))
        self.manager.accept(self.s,cmd,ev,'transferred')
        self.assertEqual(self.manager.current(self.s)['inspection']['inventory'][ITEM],2)
        self.assertIsNone(self.manager.current(self.s)['intent'])

    def test_reject_unrelated_slot_change_even_same_aggregate(self):
        cmd,a,b=self.intent()
        b['player_slots'][1]=b['player_slots'][0];b['player_slots'][0]=stack()
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,b)))

    def test_reject_cursor_station_dimension_and_sync_changes(self):
        cmd,a,b=self.intent()
        for key,value in (('cursor_empty',False),('station_opened',False),('dimension','minecraft:the_nether'),('sync_id',2),('station',dict(x=3,y=64,z=0))):
            bad=copy.deepcopy(b);bad[key]=value
            self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,bad)),key)

    def test_reject_aggregate_component_or_extra_unit_changes(self):
        cmd,a,b=self.intent()
        bad=copy.deepcopy(b);bad['inventory'][ITEM]+=1
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,bad)))
        bad=copy.deepcopy(b);bad['slots'][0]['components']='different'
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,bad)))
        bad=copy.deepcopy(b);bad['slots'][0]['count']+=1;bad['inventory'][ITEM]-=1;bad['player_slots'][0]['count']-=1
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,bad)))

    def test_no_transfer_proof_without_persisted_intent(self):
        a=self.inspected();cmd=self.command(self.manager.propose(self.s))
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd,a,expected_transfer(a,cmd['action'],cmd['storage']))))

    def test_intent_and_command_can_rollback_atomically(self):
        a=self.inspected();self.m.db.commit();cmd=self.command(self.manager.propose(self.s))
        self.manager.prepare_command(self.s,cmd)
        self.assertEqual(self.manager.current(self.s)['status'],'intent')
        self.m.db.rollback()
        self.assertIsNone(self.manager.current(self.s)['intent'])

    def reconcile(self,which):
        cmd,a,b=self.intent();self.m.db.commit();self.manager.interrupt(self.s,cmd)
        self.s.session=uuid4()
        self.manager=StorageManager(self.m,clock=lambda:self.t)
        inspect=self.command(self.manager.propose(self.s));self.assertEqual(inspect['action'],'storage_inspect')
        observed=copy.deepcopy(b if which=='expected' else a)
        if which=='other':observed['player_slots'][0]['count']-=2;observed['inventory'][ITEM]-=2
        observed['sync_id']=19
        self.assertTrue(self.manager.validate(self.s,inspect,self.proof(inspect,observed)))
        status=self.manager.accept(self.s,inspect,self.proof(inspect,observed),'reinspection')
        return status

    def test_lost_success_reconciles_without_transfer_attribution(self):
        self.assertEqual(self.reconcile('expected'),'resolved')
        row=self.m.rows('SELECT * FROM StorageJobs')[0]
        self.assertIsNone(row['intent']);self.assertEqual(row['last_event'],'reinspection')
        self.assertFalse(self.m.rows('SELECT * FROM Events'))

    def test_unchanged_interruption_allows_new_intent(self):
        self.assertEqual(self.reconcile('before'),'retry')
        cmd=self.command(self.manager.propose(self.s));self.assertEqual(cmd['action'],'storage_deposit')
        self.manager.prepare_command(self.s,cmd)
        self.assertEqual(self.manager.current(self.s)['intent']['command_id'],cmd['id'])

    def test_third_state_is_conflict_and_never_retried(self):
        self.assertEqual(self.reconcile('other'),'conflict')
        self.assertIsNone(self.manager.propose(self.s))

    def test_essential_tools_and_nonstandard_items_never_transfer(self):
        for item in ('minecraft:iron_pickaxe','minecraft:diamond','minecraft:poisonous_potato'):
            self.assertNotIn(item,MATERIALS)
        a=snapshot({0:(ITEM,3,False)})
        self.inspected(a)
        self.assertIsNone(self.manager.propose(self.s))

    def test_protected_wood_and_furnace_reservations_add_up(self):
        self.s.player.inventory={'minecraft:oak_planks':20,'minecraft:coal':6}
        recipe=json.dumps(dict(input_id='minecraft:oak_planks',fuel_id='minecraft:coal'))
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          ('f',self.s.world,DIM,'{}',recipe,'planned','now','now'))
        reserved=self.manager.reservations(self.s)
        self.assertEqual(reserved['minecraft:oak_planks'],13)
        self.assertEqual(reserved['minecraft:coal'],5)

    def test_shelter_wood_reservation_is_additive_to_basic_reserve(self):
        self.manager.construction=NS(wood_demand=lambda s:5,requirements=lambda s:(5,0))
        self.s.player.inventory={'minecraft:oak_planks':20}
        self.assertEqual(self.manager.reservations(self.s)['minecraft:oak_planks'],17)

    def test_furnace_demand_withdraws_missing_unit_but_not_loaded_material(self):
        recipe=json.dumps(dict(input_id='minecraft:raw_iron',fuel_id='minecraft:coal'))
        loaded=dict(slots=[stack('minecraft:raw_iron',1),stack(),stack()])
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,inspection,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                          ('f',self.s.world,DIM,'{}',recipe,'recoverable',json.dumps(loaded),'now','now'))
        needs=self.manager.demands(self.s)
        self.assertNotIn('minecraft:raw_iron',needs)
        self.assertEqual(needs['minecraft:coal'],1)
        self.inspected(snapshot({}, {0:('minecraft:coal',2),1:('minecraft:raw_iron',2)}))
        cmd=self.command(self.manager.propose(self.s))
        self.assertEqual(cmd['action'],'storage_withdraw')
        self.assertEqual(cmd['storage']['item_id'],'minecraft:coal')

    def test_planned_furnace_demands_add_and_ignore_unsafe_food_and_terminal_jobs(self):
        for jid,status,item in (('a','planned','minecraft:raw_iron'),('b','empty','minecraft:raw_iron'),
                                ('c','completed','minecraft:raw_iron'),('d','planned','minecraft:potato'),
                                ('e','planned','minecraft:chicken')):
            recipe=json.dumps(dict(input_id=item,fuel_id=None))
            self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                              (jid,self.s.world,DIM,'{}',recipe,status,'now','now'))
        needs=self.manager.demands(self.s)
        self.assertEqual(needs['minecraft:raw_iron'],2)
        self.assertEqual(needs['minecraft:potato'],4)
        self.assertNotIn('minecraft:chicken',needs)

    def test_place_chest_for_excess_outside_shelter_anchor(self):
        self.s.storage=[];self.s.capabilities.append('place')
        self.s.player.inventory={ITEM:3,'minecraft:chest':1}
        support=NS(model_dump=lambda:dict(x=2,y=63,z=0))
        self.s.placement_spots=[NS(x=0,y=64,z=0,support=support),NS(x=2,y=64,z=0,support=support)]
        self.manager.construction=NS(current=lambda s:dict(anchor=dict(x=0,y=64,z=0)),
                                     wood_demand=lambda s:0,requirements=lambda s:(0,0))
        proposal=self.manager.propose(self.s)
        self.assertEqual(proposal['kind'],'place')
        self.assertEqual(proposal['params']['target'],dict(x=2,y=64,z=0,id='minecraft:chest'))
        self.s.player.inventory={'minecraft:chest':1,'minecraft:oak_planks':12}
        self.assertIsNone(self.manager.propose(self.s))

    def test_absolute_withdrawal_demand_stops_after_target(self):
        self.manager.construction=NS(wood_demand=lambda s:2,requirements=lambda s:(2,0))
        a=self.inspected(snapshot({}, {0:('minecraft:oak_planks',2)}))
        cmd=self.command(self.manager.propose(self.s));self.assertEqual(cmd['action'],'storage_withdraw')
        self.manager.prepare_command(self.s,cmd)
        b=expected_transfer(a,cmd['action'],cmd['storage'])
        self.manager.accept(self.s,cmd,self.proof(cmd,a,b),'withdrawn')
        self.s.player.inventory=b['inventory'].copy()
        cmd=self.command(self.manager.propose(self.s));self.manager.prepare_command(self.s,cmd)
        c=expected_transfer(b,cmd['action'],cmd['storage'])
        self.manager.accept(self.s,cmd,self.proof(cmd,b,c),'withdrawn2')
        self.s.player.inventory=c['inventory'].copy()
        proposal=self.manager.propose(self.s)
        self.assertTrue(proposal is None or proposal['kind']!='storage_withdraw')

    def test_main_inventory_mapping_and_stack_limit(self):
        a=snapshot({9:(ITEM,3)}, {0:(ITEM,64)})
        self.inspected(a);cmd=self.command(self.manager.propose(self.s))
        self.assertEqual(cmd['storage']['source_slot'],27)
        self.assertEqual(cmd['storage']['destination_slot'],1)

    def test_snapshot_requires_exact_inventory_and_empty_cursor(self):
        a=snapshot({0:(ITEM,3)})
        self.assertTrue(valid_snapshot(a,POS,DIM))
        for bad in (dict(a,inventory={ITEM:True}),dict(a,cursor_empty=False),dict(a,slots=[]),dict(a,player_slots=[])):
            self.assertFalse(valid_snapshot(bad,POS,DIM))

    def test_idle_chest_does_not_starve_other_work(self):
        self.inspected(snapshot({0:('minecraft:bread',3)}))
        self.assertIsNone(self.manager.propose(self.s))
        self.t+=11
        self.assertIsNone(self.manager.propose(self.s))
        self.t+=20
        self.assertEqual(self.manager.propose(self.s)['kind'],'storage_inspect')

    def test_source_contains_real_gui_and_server_evidence_guards(self):
        source=(Path(__file__).resolve().parents[1]/'mod/src/main/java/ai/minelife/StorageController.java').read_text()
        for text in ('SlotActionType.PICKUP','ChestType.SINGLE','server.execute','getInventory()==chest','canUse(player)',
                     'storage_baseline_changed','storage_client_not_synced','getCursorStack().isEmpty()'):
            self.assertIn(text,source)
        self.assertNotIn('QUICK_MOVE',source)
        self.assertNotIn('sendChatCommand',source)


if __name__=='__main__':unittest.main()
