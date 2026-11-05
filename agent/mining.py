"""Surface resource demand; offered tools/targets come from the client, outcomes need evidence."""
import math
import json
from agent.crafting import has_tool

YIELDS = {'minecraft:stone':'minecraft:cobblestone', 'minecraft:cobblestone':'minecraft:cobblestone',
          'minecraft:coal_ore':'minecraft:coal', 'minecraft:iron_ore':'minecraft:raw_iron',
          'minecraft:dirt':'minecraft:dirt','minecraft:grass_block':'minecraft:dirt','minecraft:sand':'minecraft:sand','minecraft:red_sand':'minecraft:red_sand'}


def mining_evidence(offer, ev):
    before,after=ev.get('inventory_before'),ev.get('inventory_after')
    return (ev.get('server_verified') is True and ev.get('before_block')==offer['id']
            and ev.get('after_block')=='minecraft:air' and type(ev.get('mined_delta')) is int and ev['mined_delta']==1
            and ev.get('tool_id')==offer['tool_id'] and ev.get('tool_suitable') is True
            and type(ev.get('tool_before_damage')) is int and ev['tool_before_damage']==offer['tool_damage']
            and type(ev.get('tool_after_damage')) is int and ev['tool_after_damage']==offer['tool_damage']+offer.get('tool_wear',1)
            and isinstance(before,dict) and isinstance(after,dict)
            and all(type(v) is int and v>=0 for inv in (before,after) for v in inv.values())
            and (offer['tool_id']=='minecraft:air' or before.get(offer['tool_id'],0)==after.get(offer['tool_id'],0)>0))


class MiningPlanner:
    def __init__(self,memory,crafting):
        self.m,self.crafting=memory,crafting

    def intents(self,s):
        rows=self.m.rows("SELECT goal_id,params FROM GoalPlans WHERE world=? AND kind='mine' ORDER BY rowid DESC LIMIT 64",(s.world,))
        return [(r['goal_id'],p,p['acquisition']) for r in rows
                if (p:=json.loads(r['params'])).get('acquisition',{}).get('status')=='pending'
                and p['acquisition'].get('dimension')==s.dimension]

    def save_intent(self,gid,params):
        self.m.db.execute('UPDATE GoalPlans SET params=? WHERE goal_id=?',(json.dumps(params),gid))

    def intend(self,s,gid,cmd,verified=False):
        """Persist demand before acting; removal and acquisition remain separate facts."""
        rows=self.m.rows('SELECT params FROM GoalPlans WHERE goal_id=?',(gid,))
        if not rows:return
        params=json.loads(rows[0]['params']);block=cmd['target']['id']
        output=YIELDS.get(block,block if block.endswith('_log') else '')
        if not output:return
        params['acquisition']=dict(status='pending',item_id=output,dimension=s.dimension,
                                   removal_command=cmd['id'],removal_session=str(s.session),
                                   removal_verified=verified,waits=0,attempts=0)
        self.save_intent(gid,params)

    def pickup_outcome(self,s,gid,cmd,success=False,cancelled=False,reason=''):
        rows=self.m.rows('SELECT params FROM GoalPlans WHERE goal_id=?',(gid,))
        if not rows:return
        parent=json.loads(rows[0]['params']).get('acquisition_goal')
        for intent_id,params,intent in self.intents(s):
            if parent!=intent_id:continue
            if success:
                intent.update(status='acquired',pickup_command=cmd['id'],pickup_session=str(s.session),entity_id=cmd['item']['entity_id'])
            elif not cancelled:
                intent['attempts']+=1
                intent['last_error']=reason
                if intent['attempts']>=2 or reason=='inventory_full':intent['status']='exhausted'
            self.save_intent(intent_id,params)

    def acquisition_pending(self,s):
        """Hold exploration briefly for asynchronous drops and bounded pickup retries."""
        pending=False
        for gid,params,intent in self.intents(s):
            # Failed or cancelled removal never establishes an asynchronous drop.
            # In-flight commands are handled before this planning stage.
            if not intent.get('removal_verified'):continue
            intent['checks']=intent.get('checks',0)+1
            visible='pickup' in s.capabilities and any(i.item_id==intent['item_id'] and self.available(s,i) for i in s.items)
            if not visible:
                intent['waits']+=1
                if intent['waits']>3:intent['status']='unobserved'
            if intent['checks']>24:intent['status']='expired'
            self.save_intent(gid,params)
            pending |= intent['status']=='pending'
        return pending

    def available(self,s,item):
        if math.dist((item.x,item.y,item.z),(s.player.x,s.player.y,s.player.z))>10:return False
        rows=self.m.rows('SELECT p.attempts,g.status FROM GoalPlans p JOIN Goals g ON p.goal_id=g.id WHERE p.world=? AND p.subject=?',
                         (s.world,'pickup:'+s.dimension+':'+str(item.entity_id)))
        return not rows or rows[0]['attempts']<2 and rows[0]['status']!='completed'

    def demand(self,s,item):
        inv=s.player.inventory
        if item.endswith('_log'):return 1 if self.crafting.needs_wood(s) else 0
        if item=='minecraft:cobblestone':
            # A small reserve covers stone tools and a furnace, not endless quarrying.
            tools=sum(3 for name in ('pickaxe','axe') if not has_tool(s,name,('stone','iron','diamond','netherite')))
            furnace=0 if inv.get('minecraft:furnace',0) or any(b.id=='minecraft:furnace' for b in s.blocks) else 8
            return tools+furnace
        if item=='minecraft:raw_iron':return max(0,4-inv.get('minecraft:iron_ingot',0)) if 'furnace_load' in s.capabilities else 0
        if item in ('minecraft:dirt','minecraft:sand','minecraft:red_sand'):
            return 0 if self.m.rows("SELECT 1 FROM Knowledge WHERE world=? AND subject=? AND status='confirmed'",(s.world,'mining:'+item)) else 1
        return {'minecraft:coal':4}.get(item,0)

    def proposals(self,s,personality):
        if s.player.danger or s.player.food<=8 or s.time>=12000 or not {'mine','pickup'}<=set(s.capabilities):return []
        rows=[]
        project=self.crafting.construction.current(s)
        for offer in s.mining:
            output=YIELDS.get(offer.id,offer.id if offer.id.endswith('_log') else '')
            if not output or self.demand(s,output)<=s.player.inventory.get(output,0):continue
            if math.dist((offer.x,offer.y,offer.z),(s.player.x,s.player.y,s.player.z))>12:continue
            if project and abs(offer.x-project['anchor']['x'])<=2 and abs(offer.z-project['anchor']['z'])<=3:continue
            tool=offer.tool_id
            if not offer.tool_suitable or tool!='minecraft:air' and not s.player.inventory.get(tool,0):continue
            if offer.tool_required and tool=='minecraft:air':continue
            target={k:getattr(offer,k) for k in ('x','y','z','id')}
            rows.append(dict(subject=f'mine:{s.dimension}:{offer.id}:{offer.x}:{offer.y}:{offer.z}',
                             description='Investigar '+offer.id+' usando '+tool,
                             reason='Recurso exposto e ferramenta adequada anunciados pelo mod; verificar remoção, desgaste e coleta separadamente.',
                             priority=155+(personality['prudence']-60)*.15,kind='mine',skill='mine_resource',
                             params=dict(target=target,mining=offer.model_dump())))
        return rows

    def pending_drop(self,s):
        # Pick up useful visible drops before digging another block. Disappearance alone is never proof.
        if 'pickup' not in s.capabilities or s.player.danger or s.player.food<=8 or s.time>=12000:return None
        wanted={intent['item_id'] for _,_,intent in self.intents(s)}
        items=[i for i in s.items if (i.item_id in YIELDS.values() or i.item_id.endswith('_log'))
               and (i.item_id in wanted or self.demand(s,i.item_id)>s.player.inventory.get(i.item_id,0))
               and self.available(s,i)]
        return min(items,key=lambda i:math.dist((i.x,i.y,i.z),(s.player.x,s.player.y,s.player.z)),default=None)
