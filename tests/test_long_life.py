"""Many changing observation cycles against the real planner and temporary SQLite.

The adapter supplies synthetic server proofs. It never launches Minecraft and
does not establish survival, path safety, or food production in the real game.
"""
import copy
import unittest
from uuid import uuid4
import test_pipeline as base
from test_storage import snapshot, stack, content
from agent.engine import CognitiveEngine
from agent.memory import MemoryManager
from agent.journal.writer import JournalWriter
from agent.storage import ACTIONS, expected_transfer
from life_metrics import LifeMetrics, world_fingerprint


class LongLifeTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def test_400_cycles_resources_hunger_night_pause_loss_and_restarts(self):
        snap=snapshot({0:('minecraft:dirt',6),1:('minecraft:coal',1),2:('minecraft:bread',8)},
                      {0:('minecraft:stick',4),1:('minecraft:coal',4)})
        position=dict(x=0.,y=64.,z=0.);food=20;pending=[];commands=set();lost=None
        executed=set();counts={};clock=[100.]
        self.engine.clock=lambda:clock[0]
        self.engine.storage.clock=lambda:clock[0]
        metrics=LifeMetrics(self.m,base.WORLD)

        def change(item,delta):
            remaining=abs(delta)
            for c in snap['player_slots']:
                if delta<0 and c['id']==item and remaining:
                    n=min(c['count'],remaining);remaining-=n;c['count']-=n
                    if not c['count']:c.update(stack())
                elif delta>0 and remaining and (c['id']==item or not c['count']):
                    n=min(64-c['count'],remaining);remaining-=n
                    if not c['count']:c.update(stack(item,0));c['components']=stack(item,1)['components']
                    c['count']+=n
            self.assertEqual(remaining,0)
            inventory={}
            for c in snap['player_slots']:
                if c['count']:inventory[c['id']]=inventory.get(c['id'],0)+c['count']
            snap['inventory']=inventory

        for cycle in range(400):
            clock[0]+=2.1
            if cycle in (2,70,130,230,330):
                if cycle in (230,330):
                    self.m.close()
                    self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
                    self.writer=JournalWriter(self.m,self.root/'journals')
                    metrics.memory=self.m
                self.engine=CognitiveEngine(self.m,self.writer)
                self.engine.clock=lambda:clock[0];self.engine.storage.clock=lambda:clock[0]
                self.session=str(uuid4());pending=[]
            active=cycle%100 not in (55,56)
            danger=cycle%100 in (85,86)
            if cycle in (25,60,95,140):food=4
            recipes=[]
            if snap['inventory'].get('minecraft:coal',0) and snap['inventory'].get('minecraft:stick',0):
                recipes=[dict(id='minecraft:torch',input_id='minecraft:coal',input_count=1,
                              inputs={'minecraft:coal':1,'minecraft:stick':1},output_id='minecraft:torch',output_count=4)]
            foods=[dict(id='minecraft:bread',slot=i,count=c['count'],nutrition=5)
                   for i,c in enumerate(snap['player_slots']) if c['id']=='minecraft:bread' and c['count']]
            self.engine.last_plan[base.WORLD]=-1e30
            response=self.step(pending,active=active,armed=active,control_state='ACTIVE' if active else 'EMERGENCY_STOP',
                               day=1+cycle//50,time=13000 if 40<=cycle%100<50 else 1000,
                               blocks=[],storage=[snap['station']],recipes=recipes,
                               frontiers=[dict(x=int(position['x'])-12,y=64,z=0,safe=True,path_length=12)],
                               capabilities=list(ACTIONS)+['craft','eat','explore'],
                               player=dict(**position,health=20,food=food,danger=danger,inventory=snap['inventory'].copy(),foods=foods))
            pending=[];cmd=response['command']
            metrics.observe(response)
            if response['interrupt']:
                pending=[dict(id=response['interrupt'],status='cancelled',reason='physiological_preemption',evidence={})]
            if not active:self.assertIsNone(cmd)
            if danger:
                self.assertIsNone(cmd);self.assertEqual(response['control'],'pause')
            if cmd is None:continue
            self.assertIn(cmd['action'],ACTIONS|{'craft','eat','explore'})
            # An issued command can be retransmitted; the physical adapter never executes it twice.
            if cmd['id'] in executed:continue
            executed.add(cmd['id']);commands.add(cmd['action']);counts[cmd['action']]=counts.get(cmd['action'],0)+1
            before_stock=copy.deepcopy(snap);delta={}
            target={k:cmd['target'][k] for k in ('x','y','z')};ev=dict(target=target,server_verified=True)
            if cmd['action'] in ACTIONS:
                snap['sync_id']+=1;a=copy.deepcopy(snap)
                if cmd['action']!='storage_inspect':
                    self.assertEqual(content(a),content(cmd['storage']['baseline']))
                    snap=expected_transfer(a,cmd['action'],cmd['storage'])
                ev.update(job_id=cmd['storage']['job_id'],before=a,after=copy.deepcopy(snap))
            elif cmd['action']=='craft':
                r=cmd['recipe'];before=snap['inventory'].copy()
                delta={item:-n for item,n in r['inputs'].items()}
                delta[r['output_id']]=delta.get(r['output_id'],0)+r['output_count']
                for item,n in r['inputs'].items():change(item,-n)
                change(r['output_id'],r['output_count'])
                ev.update(recipe=r['id'],crafted_delta=r['output_count'],inventory_before=before,inventory_after=snap['inventory'].copy())
            elif cmd['action']=='eat':
                before=snap['inventory'].copy();old=food;change(cmd['food']['id'],-1);food=min(20,food+5)
                delta={cmd['food']['id']:-1}
                ev.update(food_before=old,food_after=food,inventory_before=before,inventory_after=snap['inventory'].copy())
            else:
                position=dict(x=target['x']+.5,y=target['y'],z=target['z']+.5)
                ev.update(position=position.copy(),dimension='minecraft:overworld')
            self.assertTrue(metrics.conserve(before_stock,snap,delta))
            if cycle==1:
                lost=cmd['id']  # Server changed inventory; its response is deliberately lost before restart.
            else:pending=[self.success(cmd,ev)]
            self.assertEqual(sum(c['count'] for c in snap['slots']+snap['player_slots'] if c['id']=='minecraft:dirt'),6)
            self.assertTrue(all(0<=c['count']<=64 for c in snap['slots']+snap['player_slots']))

        self.assertTrue({'storage_inspect','storage_withdraw','craft','eat','explore'}<=commands,commands)
        self.assertGreaterEqual(len(self.m.rows("SELECT * FROM Events WHERE type='ate'")),3)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE dedup=? AND type='storage_withdrawn'",(lost,)))
        self.assertLessEqual(len(executed),400)
        report=metrics.report()
        self.assertEqual(report['cycles'],400)
        self.assertGreater(report['progress_cycles'],10,report)
        self.assertGreater(report['completed_goals'],0,report)
        self.assertGreater(report['recovered_storage'],0,report)
        self.assertEqual(report['conservation_checks'],len(executed))
        self.assertEqual(report['conservation_failures'],0)
        self.assertFalse(self.m.rows('SELECT * FROM CognitiveSuggestions'))
        print('Synthetic 400-cycle metrics:',report)
        self.assertEqual(self.m.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('shelter_completed','cooked','crop_harvested')"))

    def test_240_cycles_world_switch_isolation_f10_danger_and_retransmission_without_llm(self):
        other='b'*64
        metrics={world:LifeMetrics(self.m,world) for world in (base.WORLD,other)}
        position=dict(x=0.,y=64.,z=0.);pending=[];executed=set();last_result=None
        isolated=None;clock=[100.]
        self.engine.clock=lambda:clock[0]
        for cycle in range(240):
            clock[0]+=4
            world=base.WORLD if cycle<120 else other
            dimension='minecraft:overworld' if cycle<120 else 'minecraft:the_nether'
            if cycle==120:
                self.session=str(uuid4())
                self.engine=CognitiveEngine(self.m,self.writer)
                self.engine.clock=lambda:clock[0]
                # Constructor recovery reconciles prior sessions before new-world observations.
                isolated=world_fingerprint(self.m,base.WORLD)
                position=dict(x=0.,y=64.,z=0.)
                # A previous world's genuine result must not become evidence in the new world.
                pending=[last_result] if last_result else []
            active=cycle%60 not in (30,31)
            danger=cycle%60 in (40,41)
            self.engine.last_plan[world]=-1e30
            response=self.step(pending,world=world,dimension=dimension,
                               active=active,armed=active,control_state='ACTIVE' if active else 'EMERGENCY_STOP',
                               blocks=[],capabilities=['explore'],
                               frontiers=[dict(x=int(position['x'])-12,y=64,z=0,safe=True,path_length=12)],
                               player=dict(**position,health=20,food=20,danger=danger,inventory={}))
            pending=[];cmd=response['command'];metrics[world].observe(response)
            if not active or danger:self.assertIsNone(cmd)
            if danger:self.assertEqual(response['control'],'pause')
            if cmd:
                persisted=self.m.rows('SELECT world,session FROM Commands WHERE id=?',(cmd['id'],))[0]
                self.assertEqual((persisted['world'],persisted['session']),(world,self.session))
                self.assertEqual(cmd['action'],'explore')
                if cmd['id'] not in executed:
                    executed.add(cmd['id'])
                    target={k:cmd['target'][k] for k in ('x','y','z')}
                    position=dict(x=target['x']+.5,y=target['y'],z=target['z']+.5)
                    last_result=self.success(cmd,dict(target=target,position=position.copy(),
                                                     server_verified=True,dimension=dimension))
                    # Lose the first acknowledgement in each world; the backend may retransmit.
                    if len(metrics[world].seen)>1:pending=[last_result]
                else:
                    pending=[last_result]
            if isolated is not None:
                self.assertTrue(metrics[other].isolated(base.WORLD,isolated))
        for world,measurement in metrics.items():
            report=measurement.report()
            self.assertEqual(report['cycles'],120)
            self.assertGreater(report['progress_cycles'],10,report)
            self.assertGreaterEqual(report['repeated_commands'],1,report)
            self.assertFalse(self.m.rows('SELECT * FROM CognitiveSuggestions WHERE world=?',(world,)))
            print('Synthetic isolated-world metrics:',report)
        self.assertEqual(metrics[other].report()['world_isolation_checks'],120)
        self.assertEqual(metrics[other].report()['world_isolation_failures'],0)
        self.assertEqual(self.m.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_metrics_detect_inventory_creation_and_same_count_world_mutation(self):
        metrics=LifeMetrics(self.m,base.WORLD)
        before=snapshot({0:('minecraft:dirt',1)})
        after=snapshot({0:('minecraft:dirt',2)})
        self.assertFalse(metrics.conserve(before,after))
        self.assertFalse(metrics.report()['inventory_conserved'])
        eid=self.m.event(base.WORLD,self.session,1,'fixture','Before',True,{},'metrics-fixture')
        fingerprint=world_fingerprint(self.m,base.WORLD)
        self.m.db.execute('UPDATE Events SET description=? WHERE id=?',('Changed without adding rows',eid))
        self.assertFalse(metrics.isolated(base.WORLD,fingerprint))
        self.assertEqual(metrics.report()['world_isolation_failures'],1)
