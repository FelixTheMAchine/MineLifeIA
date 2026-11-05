"""Protocol/evidence fixtures in temporary databases; no Minecraft gameplay or real-world data."""
import copy
import json
import unittest
from uuid import uuid4
from pydantic import ValidationError
import test_pipeline as base
import test_workstations as work
from agent.engine import CognitiveEngine
from agent.protocol import CookingOffer, MiningOffer
from agent.memory import MemoryManager
from agent.journal.writer import JournalWriter

CAPS=['mine','pickup','furnace_load','furnace_inspect','furnace_take','eat']
FURNACE=dict(x=2,y=64,z=1,id='minecraft:furnace',log=False,lit=False)
ORE=dict(x=2,y=64,z=0,id='minecraft:stone',tool_id='minecraft:wooden_pickaxe',tool_slot=12,tool_damage=0,tool_max_damage=59)
COOK=dict(id='minecraft:cooked_chicken',input_id='minecraft:chicken',output_id='minecraft:cooked_chicken',cook_ticks=200,fuel_id='minecraft:coal',fuel_ticks=1600)
STOCK={'minecraft:chicken':2,'minecraft:coal':1}


class MiningCookingTest(unittest.TestCase):
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def setUp(self):
        base.PipelineTest.setUp(self)
        self.t=100.
        self.set_clock()

    def set_clock(self):
        self.engine.clock=lambda:self.t
        self.engine.cooking.clock=lambda:self.t

    def frame(self,inv=None,results=None,mining=(),cooking=(),blocks=(),food=20,foods=(),caps=None,**kw):
        self.engine.last_plan[base.WORLD]=-1e30
        return self.step(results,capabilities=CAPS if caps is None else caps,blocks=list(blocks),mining=list(mining),cooking=list(cooking),
                         player=dict(x=0,y=64,z=0,health=20,food=food,danger=False,inventory=inv or {},foods=list(foods)),**kw)

    def furnace_frame(self,inv=None,results=None,**kw):
        return self.frame(STOCK if inv is None else inv,results,cooking=[COOK],blocks=[FURNACE],**kw)

    def snapshot(self,inv,inputs=0,fuel=0,output=0,lit=False):
        slots=[dict(id=item if n else 'minecraft:air',count=n) for item,n in
               ((COOK['input_id'],inputs),(COOK['fuel_id'],fuel),(COOK['output_id'],output))]
        return dict(station={k:FURNACE[k] for k in ('x','y','z')},dimension='minecraft:overworld',station_opened=True,
                    slots=slots,lit=lit,inventory=dict(inv))

    def proof(self,c,a,b=None,slot=None):
        ev=dict(server_verified=True,target={k:c['target'][k] for k in ('x','y','z')},job_id=c['furnace']['job_id'],
                recipe=c['furnace']['recipe'],before=copy.deepcopy(a),after=copy.deepcopy(a if b is None else b))
        if slot is not None:ev['take_slot']=slot
        return ev

    def load(self):
        inspect=self.furnace_frame()['command'];self.assertEqual(inspect['action'],'furnace_inspect')
        load=self.furnace_frame(results=[self.success(inspect,self.proof(inspect,self.snapshot(STOCK)))])['command']
        self.assertEqual(load['action'],'furnace_load')
        after={'minecraft:chicken':1}
        ev=self.proof(load,self.snapshot(STOCK),self.snapshot(after,inputs=1,lit=True))
        self.furnace_frame(after,[self.success(load,ev)])
        return after

    def ready(self,inv):
        self.t+=6
        inspect=self.furnace_frame(inv)['command'];self.assertEqual(inspect['action'],'furnace_inspect')
        take=self.furnace_frame(inv,[self.success(inspect,self.proof(inspect,self.snapshot(inv,output=1,lit=True)))])['command']
        self.assertEqual(take['action'],'furnace_take')
        return take

    def mine_proof(self,c,inv):
        return dict(server_verified=True,target={k:c['target'][k] for k in ('x','y','z')},before_block=ORE['id'],after_block='minecraft:air',
                    mined_delta=1,tool_id=ORE['tool_id'],tool_suitable=True,tool_before_damage=0,tool_after_damage=1,
                    inventory_before=inv,inventory_after=inv)

    def test_tool_use_waits_for_drop_then_resumes_without_inventing_drops(self):
        inv={ORE['tool_id']:1}
        first=self.frame(inv,mining=[ORE])['command'];self.assertEqual(first['action'],'mine')
        other={**ORE,'x':3,'tool_damage':1}
        response=self.frame(inv,[self.success(first,self.mine_proof(first,inv))],mining=[other])
        self.assertIsNone(response['command'])
        for _ in range(3):response=self.frame(inv,mining=[other])
        second=response['command']
        self.assertEqual(second['action'],'mine');self.assertNotEqual(first['id'],second['id'])
        self.assertTrue(self.m.rows("SELECT * FROM Knowledge WHERE subject='mining:minecraft:stone' AND status='confirmed'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))
        self.assertFalse(self.m.rows("SELECT * FROM Knowledge WHERE subject='minecraft:cobblestone'"))
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))

    def test_native_pickup_during_mining_is_separate_inventory_fact(self):
        inv={ORE['tool_id']:1};c=self.frame(inv,mining=[ORE])['command'];proof=self.mine_proof(c,inv)
        proof['inventory_after']={**inv,'minecraft:cobblestone':1}
        self.frame(proof['inventory_after'],[self.success(c,proof)])
        gains=self.m.rows("SELECT * FROM Events WHERE type='inventory_gained'")
        self.assertEqual(len(gains),1)
        self.assertEqual(json.loads(gains[0]['evidence'])['after_count'],1)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))
        self.frame(proof['inventory_after'],[self.success(c,proof)])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='inventory_gained'")),1)
        entry=self.writer.write(base.WORLD,1)
        self.assertIn('origem desses itens',entry['text']);self.assertTrue(self.writer.validate_entry(entry))

    def test_mining_requires_wear_suitable_tool_inventory_and_command_target(self):
        inv={ORE['tool_id']:1}
        for mutate in (lambda ev:ev.update(tool_after_damage=0),lambda ev:ev.update(tool_suitable=False),
                       lambda ev:ev.update(tool_id='minecraft:wooden_axe'),lambda ev:ev.update(inventory_after={}),
                       lambda ev:ev.update(mined_delta=True),lambda ev:ev.update(target=dict(x=99,y=64,z=0))):
            c=self.frame(inv,mining=[{**ORE,'x':self.seq+2}])['command']
            ev=self.mine_proof(c,inv);mutate(ev)
            self.frame(inv,[self.success(c,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='resource_mined'"))

    def test_resources_in_stock_or_wrong_tool_capability_do_not_generate_mining(self):
        for inv,caps,offer in (({ORE['tool_id']:1,'minecraft:cobblestone':14},CAPS,ORE),
                               ({ORE['tool_id']:1},['mine'],ORE),({},CAPS,ORE),
                               ({'minecraft:wooden_axe':1},CAPS,{**ORE,'tool_id':'minecraft:wooden_axe','tool_suitable':False})):
            self.assertIsNone(self.frame(inv,mining=[offer],caps=caps)['command'])
        self.assertIsNone(self.frame({ORE['tool_id']:1},mining=[ORE],time=13000)['command'])
        self.assertIsNone(self.frame({ORE['tool_id']:1},mining=[ORE],food=4)['command'])

    def test_pickup_is_chosen_before_mining_another_resource(self):
        item=dict(entity_id=str(uuid4()),x=1,y=64,z=0,item_id='minecraft:cobblestone',count=1,edible=False)
        c=self.frame({ORE['tool_id']:1},mining=[ORE],items=[item])['command']
        self.assertEqual(c['action'],'pickup')
        proof=dict(target={k:c['target'][k] for k in ('x','y','z')},server_verified=True,
                   item_id=item['item_id'],entity_id=item['entity_id'],inventory_before={},inventory_after={},
                   entity_present_before=True,entity_present_after=False,entity_count_before=1,entity_count_after=0)
        self.frame(results=[self.success(c,proof)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))

    def test_furnace_load_inspect_take_and_meal_have_separate_evidence(self):
        inv=self.load()
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('cooked','ate')"))
        take=self.ready(inv);after={**inv,COOK['output_id']:1}
        meal=self.furnace_frame(after,[self.success(take,self.proof(take,self.snapshot(inv,output=1,lit=True),self.snapshot(after,lit=True),2))],
                                 food=4,foods=[dict(id=COOK['output_id'],slot=0,count=1,nutrition=6)])['command']
        self.assertEqual(meal['action'],'eat')
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='cooked'")),1)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='ate'"))
        self.furnace_frame(inv,[self.success(meal,dict(server_verified=True,target={k:meal['target'][k] for k in ('x','y','z')},
            inventory_before=after,inventory_after=inv,food_before=4,food_after=10))],food=10)
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='ate'")),1)
        self.assertTrue(self.m.rows("SELECT * FROM PhilosophicalQuestions WHERE theme='preparation-and-time'"))
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))
        for e in self.m.rows('SELECT * FROM JournalEntries'):self.assertTrue((self.root/'journals').exists())

    def test_waiting_for_cooking_does_not_emit_busy_commands(self):
        inv=self.load();start=len(self.m.rows('SELECT * FROM Commands'))
        for _ in range(50):
            self.assertIsNone(self.furnace_frame(inv)['command'])
        self.assertEqual(len(self.m.rows('SELECT * FROM Commands')),start)
        self.assertEqual(self.engine.cooking.current(self.engine.latest)['status'],'processing')

    def test_cooking_does_not_block_other_executable_opportunities(self):
        inv=self.load();inv[ORE['tool_id']]=1
        c=self.furnace_frame(inv,mining=[ORE])['command']
        self.assertEqual(c['action'],'mine')

    def test_restart_inspects_verified_load_before_collecting_without_replay(self):
        inv=self.load();old_ids={r['id'] for r in self.m.rows('SELECT id FROM Commands')}
        self.m.close();self.m=MemoryManager(self.root/'data'/'memory.sqlite3');self.writer=JournalWriter(self.m,self.root/'journals')
        self.engine=CognitiveEngine(self.m,self.writer);self.set_clock();self.session=str(uuid4())
        c=self.furnace_frame(inv)['command'];self.assertEqual(c['action'],'furnace_inspect');self.assertNotIn(c['id'],old_ids)
        take=self.furnace_frame(inv,[self.success(c,self.proof(c,self.snapshot(inv,output=1)))])['command']
        after={**inv,COOK['output_id']:1}
        self.furnace_frame(after,[self.success(take,self.proof(take,self.snapshot(inv,output=1),self.snapshot(after),2))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='cooked'")),1)

    def test_unacknowledged_load_can_recover_output_but_cannot_claim_cooking(self):
        c=self.furnace_frame()['command']
        load=self.furnace_frame(results=[self.success(c,self.proof(c,self.snapshot(STOCK)))])['command']
        self.assertEqual(load['action'],'furnace_load')
        self.engine=CognitiveEngine(self.m,self.writer);self.set_clock();self.session=str(uuid4())
        inv={'minecraft:chicken':1};c=self.furnace_frame(inv)['command']
        take=self.furnace_frame(inv,[self.success(c,self.proof(c,self.snapshot(inv,output=1)))])['command']
        after={**inv,COOK['output_id']:1}
        result=self.success(take,self.proof(take,self.snapshot(inv,output=1),self.snapshot(after),2))
        self.furnace_frame(after,[result]);self.furnace_frame(after,[result])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='furnace_recovered'")),1)

    def test_partial_transfer_recovers_input_without_inventing_preparation(self):
        c=self.furnace_frame()['command'];inv={'minecraft:chicken':1,'minecraft:coal':1}
        recover=self.furnace_frame(inv,[self.success(c,self.proof(c,self.snapshot(inv,inputs=1)))])['command']
        self.assertTrue(recover['furnace']['recover'])
        self.furnace_frame(STOCK,[self.success(recover,self.proof(recover,self.snapshot(inv,inputs=1),self.snapshot(STOCK),0))])
        self.assertTrue(self.m.rows("SELECT * FROM FurnaceJobs WHERE status='recovered'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))

    def test_cancelled_partial_load_reinspects_before_any_new_transfer(self):
        inspect=self.furnace_frame()['command']
        load=self.furnace_frame(results=[self.success(inspect,self.proof(inspect,self.snapshot(STOCK)))])['command']
        partial={'minecraft:chicken':1,'minecraft:coal':1}
        stopped=self.furnace_frame(partial,[dict(id=load['id'],status='cancelled',reason='paused',evidence={})],active=False)
        self.assertIsNone(stopped['command'])
        # Resume immediately, within the five-second inspection cache window.
        fresh=self.furnace_frame(partial)['command']
        self.assertEqual(fresh['action'],'furnace_inspect');self.assertNotEqual(fresh['id'],load['id'])
        recover=self.furnace_frame(partial,[self.success(fresh,self.proof(fresh,self.snapshot(partial,inputs=1)))])['command']
        self.assertEqual(recover['action'],'furnace_take');self.assertTrue(recover['furnace']['recover'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('furnace_loaded','cooked')"))
        self.assertEqual(self.m.rows('SELECT status FROM Commands WHERE id=?',(load['id'],))[0]['status'],'cancelled')

    def test_emergency_pause_preserves_verified_job_until_reauthorized(self):
        inv=self.load();job=self.engine.cooking.current(self.engine.latest)
        for flags in (dict(active=False),dict(armed=False),dict(control_state='EMERGENCY_STOP')):
            self.assertIsNone(self.furnace_frame(inv,**flags)['command'])
            self.assertEqual(self.engine.cooking.current(self.engine.latest)['load_event'],job['load_event'])
        self.t+=6
        fresh=self.furnace_frame(inv)['command'];self.assertEqual(fresh['action'],'furnace_inspect')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))

    def test_missing_fuel_after_inspection_waits_without_consumption(self):
        inspect=self.furnace_frame()['command'];inv={'minecraft:chicken':2}
        self.assertIsNone(self.furnace_frame(inv,[self.success(inspect,self.proof(inspect,self.snapshot(inv)))])['command'])
        for _ in range(3):self.assertIsNone(self.furnace_frame(inv)['command'])
        self.assertFalse(self.m.rows("SELECT * FROM Commands WHERE json_extract(payload,'$.action')='furnace_load'"))
        load=self.furnace_frame(STOCK)['command'];self.assertEqual(load['action'],'furnace_load')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('furnace_loaded','cooked')"))

    def test_full_inventory_failure_preserves_output_and_rechecks_station(self):
        inv=self.load();take=self.ready(inv)
        result=dict(id=take['id'],status='failed',reason='furnace_result_unavailable_or_full',evidence={})
        fresh=self.furnace_frame(inv,[result])['command']
        self.assertEqual(fresh['action'],'furnace_inspect')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))
        # A new inspection confirms that the output is still there. The earlier take is not replayed.
        retry=self.furnace_frame(inv,[self.success(fresh,self.proof(fresh,self.snapshot(inv,output=1,lit=True)))])['command']
        self.assertIsNone(retry)  # Reinspection must not bypass the failed goal's cooldown.
        import time
        from unittest.mock import patch
        with patch('agent.goals.time.time',return_value=time.time()+self.engine.goals.cooldown+1):
            retry=self.furnace_frame(inv)['command']
            self.assertEqual(retry['action'],'furnace_take');self.assertNotEqual(retry['id'],take['id'])
            after={**inv,COOK['output_id']:1}
            self.furnace_frame(after,[self.success(retry,self.proof(retry,self.snapshot(inv,output=1,lit=True),self.snapshot(after,lit=True),2))])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='cooked'")),1)

    def test_furnace_proof_requires_station_world_job_and_owned_interface(self):
        inspect=self.furnace_frame()['command'];good=self.proof(inspect,self.snapshot(STOCK))
        for path,value in ((('before','station','x'),999),(('after','dimension'),'minecraft:the_nether'),
                           (('after','station_opened'),False),(('job_id',),str(uuid4()))):
            bad=copy.deepcopy(good);part=bad
            for key in path[:-1]:part=part[key]
            part[path[-1]]=value
            self.assertFalse(self.engine.cooking.validate(self.engine.latest,inspect,bad))
        self.assertTrue(self.engine.cooking.validate(self.engine.latest,inspect,good))

    def test_foreign_contents_are_preserved_and_station_is_suspended(self):
        c=self.furnace_frame()['command'];snap=self.snapshot(STOCK);snap['slots'][2]=dict(id='minecraft:diamond',count=7)
        self.assertIsNone(self.furnace_frame(results=[self.success(c,self.proof(c,snap))])['command'])
        self.assertTrue(self.m.rows("SELECT * FROM FurnaceJobs WHERE status='conflict'"))
        for _ in range(4):self.assertIsNone(self.furnace_frame()['command'])

    def test_no_cooked_fact_without_inventory_gain(self):
        inv=self.load();take=self.ready(inv)
        forged=self.proof(take,self.snapshot(inv,output=1),self.snapshot(inv),2)
        self.furnace_frame(inv,[self.success(take,forged)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='cooked'"))
        self.assertTrue(self.m.rows("SELECT * FROM Commands WHERE status='unverified'"))

    def test_load_rejects_missing_fuel_consumption_and_wrong_station(self):
        c=self.furnace_frame()['command']
        load=self.furnace_frame(results=[self.success(c,self.proof(c,self.snapshot(STOCK)))])['command']
        ev=self.proof(load,self.snapshot(STOCK),self.snapshot({'minecraft:chicken':1,'minecraft:coal':1},inputs=1,lit=True))
        self.furnace_frame(results=[self.success(load,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='furnace_loaded'"))
        self.assertIsNone(self.engine.cooking.current(self.engine.latest)['load_event'])

    def test_furnace_requires_capabilities_fuel_recipe_and_respects_pause(self):
        self.assertIsNone(self.furnace_frame(caps=['furnace_inspect'])['command'])
        self.assertIsNone(self.furnace_frame({'minecraft:chicken':1})['command'])
        self.assertIsNone(self.frame(STOCK,cooking=[{**COOK,'output_id':'minecraft:diamond'}],blocks=[FURNACE])['command'])
        self.assertIsNone(self.furnace_frame(active=False,armed=False)['command'])
        self.assertFalse(self.m.rows('SELECT * FROM FurnaceJobs'))
        self.assertIsNone(self.furnace_frame(control_state='EMERGENCY_STOP')['command'])

    def test_furnace_goals_and_jobs_do_not_mix_worlds(self):
        self.load();before=len(self.m.rows('SELECT * FROM FurnaceJobs'))
        self.engine.last_seen=-100;self.session=str(uuid4())
        self.frame({},world='b'*64)
        self.assertIsNone(self.engine.cooking.current(self.engine.latest))
        self.assertEqual(len(self.m.rows('SELECT * FROM FurnaceJobs')),before)

    def test_no_mining_repeat_after_two_failures(self):
        inv={ORE['tool_id']:1};c=self.frame(inv,mining=[ORE])['command']
        for _ in range(2):
            self.frame(inv,[dict(id=c['id'],status='failed',reason='path_obstructed',evidence={})])
            self.m.db.execute('UPDATE GoalPlans SET cooldown=0')
            c=self.frame(inv,mining=[ORE])['command']
        self.assertIsNone(c)

    def test_protocol_refuses_worn_tools_and_insufficient_fuel(self):
        with self.assertRaises(ValidationError):MiningOffer(**{**ORE,'tool_damage':58})
        with self.assertRaises(ValidationError):CookingOffer(**{**COOK,'fuel_ticks':100})
        with self.assertRaises(ValidationError):CookingOffer(**{**COOK,'output_id':COOK['input_id']})

    def test_empty_hand_mines_safe_dirt_without_claiming_tool_wear(self):
        hand={**ORE,'id':'minecraft:dirt','tool_id':'minecraft:air','tool_slot':0,'tool_damage':0,'tool_max_damage':0,'tool_wear':0,'tool_required':False}
        c=self.frame(mining=[hand])['command'];self.assertEqual(c['action'],'mine')
        ev=self.mine_proof(c,{})
        ev.update(before_block='minecraft:dirt',tool_id='minecraft:air',tool_after_damage=0)
        self.frame(results=[self.success(c,ev)])
        event=self.m.rows("SELECT * FROM Events WHERE type='resource_mined'")[0]
        self.assertIn('0 unidade(s)',event['description'])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))

    def test_furnace_failure_budget_survives_reinspection(self):
        c=self.furnace_frame()['command']
        c=self.furnace_frame(results=[self.success(c,self.proof(c,self.snapshot(STOCK)))])['command']
        import time
        from unittest.mock import patch
        clock=[time.time()]
        with patch('agent.goals.time.time',side_effect=lambda:clock[0]):
            for attempt in range(2):
                fresh=self.furnace_frame(results=[dict(id=c['id'],status='failed',reason='path_obstructed',evidence={})])['command']
                if fresh is not None:
                    self.assertEqual(fresh['action'],'furnace_inspect')
                    c=self.furnace_frame(results=[self.success(fresh,self.proof(fresh,self.snapshot(STOCK)))])['command']
                    self.assertIsNone(c)
                clock[0]+=self.engine.goals.cooldown+1
                self.t+=6
                inspect=self.furnace_frame()['command']
                if inspect is None:
                    c=None
                    break
                self.assertEqual(inspect['action'],'furnace_inspect')
                c=self.furnace_frame(results=[self.success(inspect,self.proof(inspect,self.snapshot(STOCK)))])['command']
                if attempt==0:self.assertIsNotNone(c)
        self.assertIsNone(c)
        self.assertTrue(self.m.rows("SELECT * FROM FurnaceJobs WHERE status='conflict'"))
        self.assertEqual(self.m.rows("SELECT coalesce(sum(attempts),0) n FROM GoalPlans WHERE kind='furnace_load'")[0]['n'],2)

    def test_furnace_crafting_and_placement_connect_to_observed_food(self):
        caps=CAPS+['craft','craft_table','place']
        r=work.recipe('furnace',{'minecraft:cobblestone':8},'furnace',grid=3)
        c=self.frame({'minecraft:cobblestone':8,**STOCK},recipes=[r],blocks=[work.TABLE],cooking=[COOK],caps=caps)['command']
        self.assertEqual(c['action'],'craft_table')
        before={'minecraft:cobblestone':8,**STOCK};after={'minecraft:furnace':1,**STOCK}
        proof=dict(server_verified=True,target={k:c['target'][k] for k in ('x','y','z')},recipe=r['id'],inventory_before=before,inventory_after=after,
                   crafted_delta=1,grid=3,station=r['station'],station_opened=True)
        place=self.frame(after,[self.success(c,proof)],cooking=[COOK],placement_spots=[work.SPOT],caps=caps)['command']
        self.assertEqual(place['action'],'place');self.assertEqual(place['target']['id'],'minecraft:furnace')
