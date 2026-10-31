"""Persistent one-unit furnace jobs. A transfer, a cooked output and a meal are distinct facts."""
import json
import math
import time
from uuid import uuid4
from agent.memory import now
from agent.construction import PLANKS

ACTIONS={'furnace_load','furnace_inspect','furnace_take'}
FOOD_OUTPUTS={'minecraft:baked_potato','minecraft:cooked_beef','minecraft:cooked_porkchop','minecraft:cooked_chicken',
              'minecraft:cooked_mutton','minecraft:cooked_rabbit','minecraft:cooked_cod','minecraft:cooked_salmon'}
OUTPUTS=FOOD_OUTPUTS|{'minecraft:iron_ingot'}


def inventory(value):
    return isinstance(value,dict) and len(value)<=256 and all(type(v) is int and 0<=v<=1000000 for v in value.values())


def compatible(slots,recipe):
    return all(c['count']==0 or c['count']==1 and c['id']==recipe[key]
               for c,key in zip(slots,('input_id','fuel_id','output_id'))) and slots[0]['count']+slots[2]['count']<=1


class CookingManager:
    def __init__(self,memory,construction,clock=time.monotonic):
        self.m,self.construction,self.clock=memory,construction,clock
        self.checked={}
        self.reason='Nenhum preparo em andamento.'

    def current(self,s):
        rows=self.m.rows("SELECT * FROM FurnaceJobs WHERE world=? AND dimension=? AND status NOT IN ('completed','recovered','lost','conflict') ORDER BY created LIMIT 1",(s.world,s.dimension))
        if not rows:return None
        row=rows[0]
        for key in ('station','recipe','inspection'):row[key]=json.loads(row[key]) if row[key] else None
        return row

    def desired(self,s):
        result=[]
        for r in s.cooking:
            if r.output_id not in OUTPUTS or s.player.inventory.get(r.input_id,0)<1:continue
            if s.player.food<=8 and r.output_id not in FOOD_OUTPUTS:continue
            limit=3 if r.output_id in FOOD_OUTPUTS else 4
            if s.player.inventory.get(r.output_id,0)>=limit:continue
            result.append(r)
        return result

    def need_furnace(self,s):
        return ACTIONS<=set(s.capabilities) and bool(self.desired(s)) and not any(b.id=='minecraft:furnace' for b in s.blocks)

    def interrupt(self,s,cmd):
        """Clicks may have reached the server even when an action was cancelled or its proof was lost."""
        job=self.current(s)
        if not job or cmd.get('furnace',{}).get('job_id')!=job['id']:return
        self.checked.pop(job['id'],None)
        self.m.db.execute('UPDATE FurnaceJobs SET last_session=NULL,updated=? WHERE id=?',(now(),job['id']))

    def propose(self,s):
        if not ACTIONS<=set(s.capabilities) or s.player.danger:return None
        job=self.current(s)
        if job is None:
            if s.time>=12000:return None
            stations=sorted((b for b in s.blocks if b.id=='minecraft:furnace' and not b.lit),key=lambda b:math.dist((b.x,b.y,b.z),(s.player.x,s.player.y,s.player.z)))
            choices=self.desired(s)
            for recipe in choices:
                if recipe.fuel_id is None or s.player.inventory.get(recipe.fuel_id,0)<1:continue
                if recipe.fuel_id in PLANKS and sum(s.player.inventory.get(k,0) for k in PLANKS)<=self.construction.wood_demand(s):continue
                for station in stations:
                    pos={k:getattr(station,k) for k in ('x','y','z')}
                    if math.dist(tuple(pos.values()),(s.player.x,s.player.y,s.player.z))>12:continue
                    if self.m.rows("SELECT 1 FROM FurnaceJobs WHERE world=? AND dimension=? AND station=? AND status IN ('conflict','lost')",(s.world,s.dimension,json.dumps(pos,sort_keys=True))):continue
                    jid=str(uuid4());stamp=now()
                    self.m.db.execute('INSERT INTO FurnaceJobs(id,world,dimension,station,recipe,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                                      (jid,s.world,s.dimension,json.dumps(pos,sort_keys=True),recipe.model_dump_json(),'planned',stamp,stamp))
                    job=self.current(s);break
                if job:break
            if job is None:
                self.reason='Sem receita, combustível livre ou fornalha fria observada; não iniciar transferências.'
                return None
        target={**job['station'],'id':'minecraft:furnace'}
        if math.dist(tuple(job['station'][k] for k in ('x','y','z')),(s.player.x,s.player.y,s.player.z))>14:
            self.reason='Preparo persistido fora do alcance local; continuar outras atividades até reobservar a estação.';return None
        recent=job['last_session']==str(s.session) and self.clock()-self.checked.get(job['id'],-1e30)<5
        if not recent or job['inspection'] is None:
            action='furnace_inspect'
        else:
            snap=job['inspection'];slots=snap['slots']
            if job['status']=='ready':action='furnace_take'
            elif job['status']=='recoverable':action='furnace_take'
            elif job['status']=='empty':
                if snap['lit'] or s.time>=12000:return None
                r=job['recipe']
                if s.player.inventory.get(r['input_id'],0)<1 or s.player.inventory.get(r['fuel_id'],0)<1:
                    self.reason='Materiais reservados indisponíveis; aguardar sem repetir transferências.';return None
                if r['fuel_id'] in PLANKS and sum(s.player.inventory.get(k,0) for k in PLANKS)<=self.construction.wood_demand(s):
                    self.reason='Madeira necessária ao abrigo; preservar a reserva em vez de usá-la como combustível.';return None
                action='furnace_load'
            else:
                self.reason='Fornalha processando; reavaliar em cinco segundos sem manter uma ação física presa.';return None
        params=dict(job_id=job['id'],recipe=job['recipe'],recover=job['status']=='recoverable')
        failures=self.m.rows('SELECT COALESCE(sum(attempts),0) n FROM GoalPlans WHERE world=? AND subject LIKE ?',
                             (s.world,f"furnace:{job['id']}:{action}:%"))[0]['n']
        if failures>=2 or job['revision']>=64:
            self.m.db.execute("UPDATE FurnaceJobs SET status='conflict',updated=? WHERE id=?",(now(),job['id']))
            self.reason='Preparo suspenso após falhas ou ausência prolongada de progresso; preservar conteúdo da estação.'
            return None
        self.reason={'furnace_inspect':'Revalidar o conteúdo real antes de continuar o preparo.',
                     'furnace_load':'Transferir uma unidade de ingrediente e combustível pela interface nativa.',
                     'furnace_take':'Recolher o resultado observado; em uma interrupção, recuperar recursos compatíveis.'}[action]
        return dict(subject=f"furnace:{job['id']}:{action}:{job['revision']}:{s.session}",description=self.reason,
                    reason='Estado persistente e inspeção da estação; nenhuma refeição presumida.',priority=235,
                    kind=action,skill=action,params=dict(target=target,furnace=params))

    def validate(self,s,cmd,ev):
        job=self.current(s);request=cmd['furnace']
        if not job or ev.get('server_verified') is not True or ev.get('job_id')!=job['id'] or request['job_id']!=job['id'] or ev.get('recipe')!=job['recipe']:return False
        for snapshot in (ev.get('before'),ev.get('after')):
            if not isinstance(snapshot,dict) or snapshot.get('station')!=job['station'] or snapshot.get('dimension')!=s.dimension or snapshot.get('station_opened') is not True:return False
            if type(snapshot.get('lit')) is not bool or not inventory(snapshot.get('inventory')):return False
            slots=snapshot.get('slots')
            if not isinstance(slots,list) or len(slots)!=3 or any(not isinstance(c,dict) or not isinstance(c.get('id'),str) or type(c.get('count')) is not int or not 0<=c['count']<=64 or (c['count']==0)!=(c['id']=='minecraft:air') for c in slots):return False
        a,b=ev['before'],ev['after'];r=job['recipe'];action=cmd['action']
        if action=='furnace_inspect':return a==b
        if not compatible(a['slots'],r) or not compatible(b['slots'],r):return False
        delta={k:b['inventory'].get(k,0)-a['inventory'].get(k,0) for k in a['inventory'].keys()|b['inventory'].keys()}
        delta={k:v for k,v in delta.items() if v}
        if action=='furnace_load':
            return (not a['lit'] and not any(c['count'] for c in a['slots']) and b['slots'][0]['count']+b['slots'][2]['count']==1
                    and delta=={r['input_id']:-1,r['fuel_id']:-1})
        slot=ev.get('take_slot');recover=request.get('recover',False)
        if type(slot) is not int or slot not in ((0,1) if recover else (2,)):return False
        return (a['slots'][slot]['count']==1 and b['slots'][slot]['count']==0
                and (not recover or not a['lit'] and not b['lit'])
                and all(a['slots'][i]==b['slots'][i] for i in range(3) if i!=slot)
                and delta=={a['slots'][slot]['id']:1})

    def accept(self,s,cmd,ev,event_id):
        job=self.current(s);snap=ev['after'];slots=snap['slots'];status='processing';load=job['load_event']
        if cmd['action']=='furnace_load':load=event_id
        if cmd['action']=='furnace_take' and ev['take_slot']==2:status='completed'
        elif not compatible(slots,job['recipe']):status='conflict'
        elif slots[2]['count']==1:status='ready'
        elif slots[0]['count']==1 or slots[1]['count']==1:status='processing' if snap['lit'] or slots[0]['count']==slots[1]['count']==1 else 'recoverable'
        elif job['status']=='recoverable' or cmd['action']=='furnace_take':status='recovered'
        elif load:status='lost'
        else:status='empty'
        self.m.db.execute('UPDATE FurnaceJobs SET status=?,load_event=?,last_event=?,last_session=?,inspection=?,revision=revision+1,updated=? WHERE id=?',
                          (status,load,event_id,str(s.session),json.dumps(snap),now(),job['id']))
        self.checked[job['id']]=self.clock()
