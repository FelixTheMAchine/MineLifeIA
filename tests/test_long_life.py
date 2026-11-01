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
from agent.storage import ACTIONS, expected_transfer


class LongLifeTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success

    def test_160_cycles_resources_hunger_night_pause_loss_and_restarts(self):
        snap=snapshot({0:('minecraft:dirt',6),1:('minecraft:coal',1),2:('minecraft:bread',8)},
                      {0:('minecraft:stick',4),1:('minecraft:coal',4)})
        position=dict(x=0.,y=64.,z=0.);food=20;pending=[];commands=set();lost=None
        executed=set();counts={};clock=[100.]
        self.engine.clock=lambda:clock[0]
        self.engine.storage.clock=lambda:clock[0]

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

        for cycle in range(160):
            clock[0]+=2.1
            if cycle in (2,70,130):
                self.engine=CognitiveEngine(self.m,self.writer)
                self.engine.clock=lambda:clock[0];self.engine.storage.clock=lambda:clock[0]
                self.session=str(uuid4());pending=[]
            active=cycle not in (55,56,115,116)
            danger=cycle in (85,86)
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
            target={k:cmd['target'][k] for k in ('x','y','z')};ev=dict(target=target,server_verified=True)
            if cmd['action'] in ACTIONS:
                snap['sync_id']+=1;a=copy.deepcopy(snap)
                if cmd['action']!='storage_inspect':
                    self.assertEqual(content(a),content(cmd['storage']['baseline']))
                    snap=expected_transfer(a,cmd['action'],cmd['storage'])
                ev.update(job_id=cmd['storage']['job_id'],before=a,after=copy.deepcopy(snap))
            elif cmd['action']=='craft':
                r=cmd['recipe'];before=snap['inventory'].copy()
                for item,n in r['inputs'].items():change(item,-n)
                change(r['output_id'],r['output_count'])
                ev.update(recipe=r['id'],crafted_delta=r['output_count'],inventory_before=before,inventory_after=snap['inventory'].copy())
            elif cmd['action']=='eat':
                before=snap['inventory'].copy();old=food;change(cmd['food']['id'],-1);food=min(20,food+5)
                ev.update(food_before=old,food_after=food,inventory_before=before,inventory_after=snap['inventory'].copy())
            else:
                position=dict(x=target['x']+.5,y=target['y'],z=target['z']+.5)
                ev.update(position=position.copy(),dimension='minecraft:overworld')
            if cycle==1:
                lost=cmd['id']  # Server changed inventory; its response is deliberately lost before restart.
            else:pending=[self.success(cmd,ev)]
            self.assertEqual(sum(c['count'] for c in snap['slots']+snap['player_slots'] if c['id']=='minecraft:dirt'),6)
            self.assertTrue(all(0<=c['count']<=64 for c in snap['slots']+snap['player_slots']))

        self.assertTrue({'storage_inspect','storage_withdraw','craft','eat','explore'}<=commands,commands)
        self.assertGreaterEqual(len(self.m.rows("SELECT * FROM Events WHERE type='ate'")),3)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE dedup=? AND type='storage_withdrawn'",(lost,)))
        self.assertLessEqual(len(executed),160)
        self.assertEqual(self.m.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type IN ('shelter_completed','cooked','crop_harvested')"))
