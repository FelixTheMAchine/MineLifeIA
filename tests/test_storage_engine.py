"""Engine integration with synthetic native storage snapshots; no gameplay claims."""
import copy
import json
import unittest
from uuid import uuid4
import test_pipeline as base
from test_storage import snapshot, ITEM, POS
from agent.engine import CognitiveEngine
from agent.storage import ACTIONS, expected_transfer


class StorageEngineTest(unittest.TestCase):
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def setUp(self):
        base.PipelineTest.setUp(self)
        self.t=100.
        self.set_clock()

    def set_clock(self):
        self.engine.clock=lambda:self.t
        self.engine.storage.clock=lambda:self.t

    def frame(self,inv=None,results=None,**kw):
        self.engine.last_plan[base.WORLD]=-1e30
        food=kw.pop('food',20)
        player=kw.pop('player',dict(x=0,y=64,z=0,health=20,food=food,danger=False,inventory={ITEM:3} if inv is None else inv))
        return self.step(results,capabilities=kw.pop('capabilities',list(ACTIONS)),blocks=kw.pop('blocks',[]),
                         storage=kw.pop('storage',[POS]),player=player,**kw)

    def proof(self,c,a,b=None):
        return dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,
                    job_id=c['storage']['job_id'],before=copy.deepcopy(a),after=copy.deepcopy(a if b is None else b))

    def intent(self):
        inspect=self.frame()['command'];self.assertEqual(inspect['action'],'storage_inspect')
        a=snapshot({0:(ITEM,3)})
        cmd=self.frame(results=[self.success(inspect,self.proof(inspect,a))])['command']
        self.assertEqual(cmd['action'],'storage_deposit')
        intent=json.loads(self.m.rows('SELECT intent FROM StorageJobs')[0]['intent'])
        self.assertEqual(intent['command_id'],cmd['id'])
        return cmd,a,expected_transfer(a,cmd['action'],cmd['storage'])

    def test_deposit_correlates_command_and_ignores_duplicate_result(self):
        cmd,a,b=self.intent();result=self.success(cmd,self.proof(cmd,a,b))
        self.frame(b['inventory'],[result])
        self.frame(b['inventory'],[result])
        rows=self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['world'],base.WORLD)
        self.assertEqual(rows[0]['session'],self.session)
        self.assertEqual(rows[0]['dedup'],cmd['id'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('collected','inventory_gained')"))

    def test_wrong_target_never_creates_transfer_fact(self):
        cmd,a,b=self.intent();ev=self.proof(cmd,a,b);ev['target']['x']+=1
        self.frame(b['inventory'],[self.success(cmd,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))
        row=self.m.rows('SELECT * FROM StorageJobs')[0]
        self.assertEqual(row['status'],'uncertain');self.assertIsNotNone(row['intent'])

    def test_other_session_result_is_ignored_and_reinspection_required(self):
        cmd,a,b=self.intent();self.t+=4;self.session=str(uuid4())
        response=self.frame(b['inventory'],[self.success(cmd,self.proof(cmd,a,b))])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))
        self.assertEqual(response['command']['action'],'storage_inspect')

    def test_other_world_never_accepts_prior_world_result(self):
        cmd,a,b=self.intent();self.t+=4;self.session=str(uuid4())
        response=self.frame(b['inventory'],[self.success(cmd,self.proof(cmd,a,b))],world='b'*64)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))
        self.assertEqual(response['command']['action'],'storage_inspect')
        self.assertEqual(len(self.m.rows('SELECT * FROM StorageJobs')),2)

    def test_f10_cancel_preserves_intent_and_resumes_with_inspection(self):
        cmd,a,b=self.intent()
        cancelled=dict(id=cmd['id'],status='cancelled',reason='local_control_paused',evidence={})
        response=self.frame(results=[cancelled],active=False,armed=False)
        self.assertIsNone(response['command'])
        job=self.m.rows('SELECT * FROM StorageJobs')[0]
        self.assertEqual(job['status'],'uncertain');self.assertIsNotNone(job['intent'])
        resumed=self.frame()['command']
        self.assertEqual(resumed['action'],'storage_inspect')

    def test_hunger_cancel_does_not_deposit_or_retry_transfer(self):
        cmd,a,b=self.intent()
        cancelled=dict(id=cmd['id'],status='cancelled',reason='hunger_guard',evidence={})
        response=self.frame(results=[cancelled],food=4)
        self.assertIsNone(response['command'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))
        job=self.m.rows('SELECT * FROM StorageJobs')[0]
        self.assertEqual(job['status'],'uncertain');self.assertIsNotNone(job['intent'])
        resumed=self.frame()['command'];self.assertEqual(resumed['action'],'storage_inspect')

    def test_hunger_interrupt_waits_for_cancel_ack_then_eats(self):
        cmd,a,b=self.intent()
        stock={ITEM:3,'minecraft:bread':1}
        player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory=stock,
                    foods=[dict(id='minecraft:bread',slot=1,count=1,nutrition=5)])
        kw=dict(player=player,capabilities=list(ACTIONS)+['eat'])
        response=self.frame(**kw)
        self.assertEqual(response['interrupt'],cmd['id'])
        self.assertIsNone(response['command'])
        self.assertEqual(self.m.rows('SELECT status FROM StorageJobs')[0]['status'],'intent')
        cancelled=dict(id=cmd['id'],status='cancelled',reason='physiological_preemption',evidence={})
        response=self.frame(results=[cancelled],**kw)
        self.assertEqual(response['command']['action'],'eat')
        self.assertEqual(self.m.rows('SELECT status FROM StorageJobs')[0]['status'],'uncertain')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))

    def test_backend_restart_lost_success_only_reconciles_inspection(self):
        cmd,a,b=self.intent()
        self.engine=CognitiveEngine(self.m,self.writer);self.set_clock()
        self.t+=4;self.session=str(uuid4())
        inspect=self.frame(b['inventory'])['command'];self.assertEqual(inspect['action'],'storage_inspect')
        b['sync_id']=7
        response=self.frame(b['inventory'],[self.success(inspect,self.proof(inspect,b))])
        job=self.m.rows('SELECT * FROM StorageJobs')[0]
        self.assertEqual(job['last_event'],self.m.rows("SELECT id FROM Events WHERE type='storage_inspected' ORDER BY rowid DESC")[0]['id'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='storage_deposited'"))
        self.assertEqual(job['revision'],2)
        # If more surplus remains a fresh intention may be generated, with a new command id.
        if response['command'] and response['command']['action']=='storage_deposit':
            self.assertNotEqual(response['command']['id'],cmd['id'])

    def test_withdraw_missing_recipe_ingredient_then_craft(self):
        recipe=dict(id='minecraft:torch',input_id='minecraft:coal',input_count=1,
                    inputs={'minecraft:coal':1,'minecraft:stick':1},output_id='minecraft:torch',output_count=4,grid=2)
        a=snapshot({0:('minecraft:coal',1)},{0:('minecraft:stick',1)})
        kw=dict(capabilities=list(ACTIONS)+['craft'],recipes=[recipe])
        inspect=self.frame(a['inventory'],**kw)['command']
        cmd=self.frame(a['inventory'],[self.success(inspect,self.proof(inspect,a))],**kw)['command']
        self.assertEqual(cmd['action'],'storage_withdraw')
        b=expected_transfer(a,cmd['action'],cmd['storage'])
        response=self.frame(b['inventory'],[self.success(cmd,self.proof(cmd,a,b))],**kw)
        self.assertEqual(response['command']['action'],'craft')
        self.assertEqual(response['command']['recipe']['output_id'],'minecraft:torch')
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='storage_withdrawn'")),1)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))

    def test_persistent_furnace_job_withdraws_fuel_then_reinspects_furnace(self):
        recipe=dict(id='minecraft:iron_ingot_from_smelting_raw_iron',input_id='minecraft:raw_iron',
                    output_id='minecraft:iron_ingot',cook_ticks=200,fuel_id='minecraft:coal',fuel_ticks=1600)
        self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                          ('furnace-job',base.WORLD,'minecraft:overworld',json.dumps(POS),json.dumps(recipe),'planned','now','now'))
        a=snapshot({0:('minecraft:raw_iron',1)},{0:('minecraft:coal',1)})
        kw=dict(capabilities=list(ACTIONS)+['furnace_inspect','furnace_load','furnace_take'])
        inspect=self.frame(a['inventory'],**kw)['command']
        cmd=self.frame(a['inventory'],[self.success(inspect,self.proof(inspect,a))],**kw)['command']
        self.assertEqual(cmd['action'],'storage_withdraw')
        self.assertEqual(cmd['storage']['item_id'],'minecraft:coal')
        b=expected_transfer(a,cmd['action'],cmd['storage'])
        response=self.frame(b['inventory'],[self.success(cmd,self.proof(cmd,a,b))],**kw)
        self.assertEqual(response['command']['action'],'furnace_inspect')
        self.assertEqual(response['command']['furnace']['job_id'],'furnace-job')


if __name__=='__main__':unittest.main()
