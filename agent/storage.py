"""Single chest logistics: intentions persist before clicks; only exact server proofs count."""
import copy
import json
import math
import time
from uuid import uuid4
from agent.memory import now
from agent.construction import PLANKS, DOORS

ACTIONS = {'storage_inspect', 'storage_deposit', 'storage_withdraw'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS StorageJobs(id TEXT PRIMARY KEY,world TEXT NOT NULL,dimension TEXT NOT NULL,
 station TEXT NOT NULL,status TEXT NOT NULL,inspection TEXT,last_session TEXT,intent TEXT,last_event TEXT,
 revision INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS storage_jobs_world ON StorageJobs(world,dimension,status);
'''
MATERIALS = {'minecraft:'+name for name in ('cobblestone','stone','dirt','sand','gravel','glass','coal',
 'charcoal','raw_iron','iron_ingot','stick','torch','crafting_table','furnace','chest')} | PLANKS | DOORS
MATERIALS |= {'minecraft:'+wood+suffix for wood in ('oak','spruce','birch','jungle','acacia','dark_oak',
 'mangrove','cherry','crimson','warped') for suffix in ('_log','_stem')}


def content(snapshot):
    return {k:v for k,v in snapshot.items() if k != 'sync_id'}


def valid_snapshot(value, station, dimension):
    if not isinstance(value, dict) or value.get('station') != station or value.get('dimension') != dimension:
        return False
    if value.get('station_opened') is not True or value.get('cursor_empty') is not True:
        return False
    if type(value.get('sync_id')) is not int or value['sync_id'] < 1:
        return False
    aggregate = {}
    for key, size in (('slots',27),('player_slots',36)):
        cells = value.get(key)
        if not isinstance(cells,list) or len(cells) != size:
            return False
        for c in cells:
            if (not isinstance(c,dict) or set(c) != {'id','count','components','standard'}
                    or not isinstance(c['id'],str) or type(c['count']) is not int or not 0<=c['count']<=64
                    or not isinstance(c['components'],str) or len(c['components'])>16384
                    or type(c['standard']) is not bool
                    or (c['count']==0) != (c['id']=='minecraft:air')
                    or c['count']==0 and (c['components'] or not c['standard'])):
                return False
            if key=='player_slots' and c['count']:
                aggregate[c['id']] = aggregate.get(c['id'],0)+c['count']
    return value.get('inventory')==aggregate and all(type(v) is int for v in value['inventory'].values())


def cell(snapshot, slot):
    if type(slot) is not int or not 0<=slot<63:
        raise ValueError('invalid storage slot')
    return snapshot['slots'][slot] if slot<27 else snapshot['player_slots'][slot-54 if slot>=54 else slot-18]


def expected_transfer(snapshot, action, request):
    """Return the complete expected state, rejecting ambiguous/component-bearing transfers."""
    if action not in ACTIONS-{'storage_inspect'}:
        raise ValueError('invalid storage action')
    source,destination = request['source_slot'],request['destination_slot']
    if action=='storage_deposit' and not (27<=source<63 and 0<=destination<27):
        raise ValueError('invalid deposit direction')
    if action=='storage_withdraw' and not (0<=source<27 and 27<=destination<63):
        raise ValueError('invalid withdrawal direction')
    a,b = cell(snapshot,source),cell(snapshot,destination)
    item = request['item_id']
    if (item not in MATERIALS or a['id']!=item or a['count']<1 or not a['standard'] or not b['standard']
            or b['count']>=64 or b['count'] and (a['id'],a['components']) != (b['id'],b['components'])):
        raise ValueError('incompatible storage cells')
    result = copy.deepcopy(snapshot)
    x,y = cell(result,source),cell(result,destination)
    x['count'] -= 1
    if not x['count']:
        x.update(id='minecraft:air',components='',standard=True)
    if not y['count']:
        y.update(id=item,components=a['components'],standard=True)
    y['count'] += 1
    delta = -1 if action=='storage_deposit' else 1
    result['inventory'][item] = result['inventory'].get(item,0)+delta
    if not result['inventory'][item]:
        del result['inventory'][item]
    return result


class StorageManager:
    def __init__(self,memory,construction=None,crafting=None,clock=time.monotonic):
        self.m,self.construction,self.crafting,self.clock=memory,construction,crafting,clock
        self.checked={}
        self.idle_until={}
        self.reason='Nenhum bau simples inspecionado.'

    def current(self,s):
        rows=self.m.rows("SELECT * FROM StorageJobs WHERE world=? AND dimension=? AND status<>'conflict' ORDER BY created LIMIT 1",(s.world,s.dimension))
        if not rows:return None
        row=rows[0]
        for key in ('station','inspection','intent'):
            row[key]=json.loads(row[key]) if row[key] else None
        return row

    def reservations(self,s):
        """Concrete additive reservations; protected foods/tools/seeds never enter MATERIALS."""
        inv=s.player.inventory
        reserved={}
        wood=12+(self.construction.wood_demand(s) if self.construction else 0)
        for item in sorted(PLANKS):
            n=min(inv.get(item,0),wood)
            reserved[item]=n;wood-=n
        for item in sorted(k for k in inv if k.endswith(('_log','_stem'))):
            n=min(inv[item],math.ceil(wood/4));reserved[item]=n;wood=max(0,wood-n*4)
        for item,n in (('minecraft:stick',4),('minecraft:cobblestone',8),('minecraft:iron_ingot',3),('minecraft:coal',4),('minecraft:charcoal',4),('minecraft:torch',8),('minecraft:crafting_table',1),('minecraft:furnace',1),('minecraft:chest',1)):
            reserved[item]=max(reserved.get(item,0),n)
        if self.construction and self.construction.requirements(s)[1]:
            for item in DOORS:reserved[item]=1
        for row in self.m.rows("SELECT recipe FROM FurnaceJobs WHERE world=? AND dimension=? AND status NOT IN ('completed','recovered','lost','conflict')",(s.world,s.dimension)):
            r=json.loads(row['recipe'])
            for key in ('input_id','fuel_id'):
                if r.get(key):reserved[r[key]]=reserved.get(r[key],0)+1
        if self.crafting:
            for r in getattr(s,'recipes',[]):
                if self.crafting.demand(s,r.output_id)>inv.get(r.output_id,0):
                    recipe=r.model_dump(mode='json')
                    for item,n in (recipe.get('inputs') or {recipe['input_id']:recipe.get('input_count',1)}).items():
                        reserved[item]=reserved.get(item,0)+n
        return reserved

    def demands(self,s):
        inv=s.player.inventory
        needs={}
        if self.construction:
            wood=self.construction.wood_demand(s)-sum(inv.get(k,0) for k in PLANKS)
            if wood>0:
                for item in PLANKS:needs[item]=inv.get(item,0)+wood
        if self.crafting:
            for r in getattr(s,'recipes',[]):
                if self.crafting.demand(s,r.output_id)>inv.get(r.output_id,0):
                    recipe=r.model_dump(mode='json')
                    for item,n in (recipe.get('inputs') or {recipe['input_id']:recipe.get('input_count',1)}).items():
                        needs[item]=max(needs.get(item,0),n)
        # Missing basic materials are useful even when recipes cannot yet be advertised.
        for item,n in (('minecraft:cobblestone',8),('minecraft:stick',4)):
            if not any(k.endswith(('_pickaxe','_axe')) and v for k,v in inv.items()):needs[item]=max(needs.get(item,0),n)
        for row in self.m.rows("SELECT recipe,inspection FROM FurnaceJobs WHERE world=? AND dimension=? AND status IN ('planned','empty','recoverable')",(s.world,s.dimension)):
            recipe=json.loads(row['recipe'])
            inspection=json.loads(row['inspection']) if row['inspection'] else {}
            slots=inspection.get('slots',[])
            for index,key in enumerate(('input_id','fuel_id')):
                item=recipe.get(key)
                if item not in MATERIALS:continue
                # A unit already observed in the furnace is not another inventory deficit.
                loaded=(len(slots)==3 and slots[index].get('id')==item and slots[index].get('count',0)>0)
                if not loaded:needs[item]=needs.get(item,0)+1
        return needs

    def _proposal(self,s,job,action,request):
        self.reason={'storage_inspect':'Inspecionar o bau real antes de transferir recursos.',
                     'storage_deposit':'Guardar uma unidade excedente, preservando reservas concretas.',
                     'storage_withdraw':'Buscar uma unidade necessaria ao projeto atual.'}[action]
        return dict(subject=f"storage:{job['id']}:{action}:{job['revision']}:{s.session}",description=self.reason,
                    reason='Inventario e todos os slots do bau sao revalidados no servidor.',priority=245 if action=='storage_withdraw' else 225,
                    kind=action,skill=action,params=dict(target={**job['station'],'id':'minecraft:chest'},storage=request))

    def propose(self,s):
        if not ACTIONS<=set(s.capabilities) or s.player.danger:return None
        job=self.current(s)
        if job is None:
            stations=sorted(getattr(s,'storage',[]),key=lambda b:math.dist((b.x,b.y,b.z),(s.player.x,s.player.y,s.player.z)))
            for station in stations:
                p={k:getattr(station,k) for k in ('x','y','z')};encoded=json.dumps(p,sort_keys=True)
                if self.m.rows("SELECT 1 FROM StorageJobs WHERE world=? AND dimension=? AND station=? AND status='conflict'",(s.world,s.dimension,encoded)):continue
                stamp=now();jid=str(uuid4())
                self.m.db.execute('INSERT INTO StorageJobs(id,world,dimension,station,status,created,updated) VALUES(?,?,?,?,?,?,?)',(jid,s.world,s.dimension,encoded,'planned',stamp,stamp))
                job=self.current(s);break
            if job is None:
                reserved=self.reservations(s)
                if ('place' in s.capabilities and s.player.inventory.get('minecraft:chest',0)>0
                        and any(n>reserved.get(item,0) for item,n in s.player.inventory.items() if item in MATERIALS)):
                    project=self.construction.current(s) if self.construction else None
                    for spot in getattr(s,'placement_spots',[]):
                        if project and abs(spot.x-project['anchor']['x'])<=1 and -1<=spot.z-project['anchor']['z']<=2:continue
                        target=dict(x=spot.x,y=spot.y,z=spot.z,id='minecraft:chest')
                        return dict(subject=f"place-chest:{s.dimension}:{spot.x}:{spot.y}:{spot.z}",
                                    description='Colocar um bau simples para guardar excedentes',
                                    reason='Bau no inventario, excedentes livres e apoio observado.',priority=220,
                                    kind='place',skill='place_workstation',params=dict(target=target,
                                    placement=dict(item_id='minecraft:chest',support=spot.support.model_dump())))
                return None
        if math.dist(tuple(job['station'][k] for k in ('x','y','z')),(s.player.x,s.player.y,s.player.z))>12:return None
        if self.clock()<self.idle_until.get(job['id'],-1e30):return None
        failures=self.m.rows('SELECT COALESCE(sum(attempts),0) n FROM GoalPlans WHERE world=? AND subject LIKE ?',
                             (s.world,f"storage:{job['id']}:%"))[0]['n']
        if failures>=3 or job['revision']>=256:
            self.m.db.execute("UPDATE StorageJobs SET status='conflict',updated=? WHERE id=?",(now(),job['id']))
            self.reason='Bau suspenso apos falhas repetidas; preservar seu conteudo.'
            return None
        request={'job_id':job['id']}
        recent=job['last_session']==str(s.session) and self.clock()-self.checked.get(job['id'],-1e30)<10
        if not recent or job['inspection'] is None or job['status'] in ('intent','uncertain','planned'):
            return self._proposal(s,job,'storage_inspect',request)
        snap=job['inspection']
        if snap['inventory']!=s.player.inventory:
            return self._proposal(s,job,'storage_inspect',request)
        reserved,needs=self.reservations(s),self.demands(s)
        for action,source_range,dest_range in (('storage_withdraw',range(27),range(27,63)),('storage_deposit',range(27,63),range(27))):
            for source in source_range:
                c=cell(snap,source);item=c['id']
                if item not in MATERIALS or not c['standard']:continue
                if action=='storage_deposit' and s.player.inventory.get(item,0)<=reserved.get(item,0):continue
                if action=='storage_withdraw' and s.player.inventory.get(item,0)>=needs.get(item,0):continue
                for dest in dest_range:
                    req={**request,'item_id':item,'source_slot':source,'destination_slot':dest,'baseline':snap}
                    try:expected_transfer(snap,action,req)
                    except ValueError:continue
                    return self._proposal(s,job,action,req)
        self.reason='Sem excedentes livres ou materiais necessarios no bau inspecionado.'
        self.idle_until[job['id']]=self.clock()+30
        return None

    def prepare_command(self,s,cmd):
        if cmd['action']=='storage_inspect':return
        job=self.current(s);req=cmd['storage']
        if not job or req['job_id']!=job['id'] or job['status'] not in ('inspected','retry','resolved') or job['intent'] is not None:
            raise ValueError('storage intent unavailable')
        baseline=req['baseline']
        if (not valid_snapshot(baseline,job['station'],s.dimension) or content(baseline)!=content(job['inspection'])
                or baseline['inventory']!=s.player.inventory or job['last_session']!=str(s.session)):
            raise ValueError('storage baseline stale')
        intent={'command_id':str(cmd['id']),'action':cmd['action'],'request':req,
                'before':baseline,'expected':expected_transfer(baseline,cmd['action'],req)}
        self.m.db.execute("UPDATE StorageJobs SET intent=?,status='intent',updated=? WHERE id=?",(json.dumps(intent),now(),job['id']))

    def validate(self,s,cmd,ev):
        job=self.current(s);req=cmd.get('storage',{})
        if not job or req.get('job_id')!=job['id'] or ev.get('job_id')!=job['id'] or ev.get('server_verified') is not True:return False
        a,b=ev.get('before'),ev.get('after')
        if not all(valid_snapshot(x,job['station'],s.dimension) for x in (a,b)):return False
        if cmd['action']=='storage_inspect':return a==b
        intent=job['intent']
        if (not intent or intent['command_id']!=str(cmd['id']) or intent['action']!=cmd['action'] or intent['request']!=req
                or content(a)!=content(intent['before']) or a['sync_id']!=b['sync_id']):return False
        try:return content(b)==content(expected_transfer(a,cmd['action'],req))
        except (KeyError,TypeError,ValueError):return False

    def accept(self,s,cmd,ev,event_id):
        job=self.current(s)
        if not self.validate(s,cmd,ev):raise ValueError('invalid storage evidence')
        snap=ev['after'];status='inspected';intent=None
        if cmd['action']=='storage_inspect' and job['intent']:
            pending=job['intent']
            if content(snap)==content(pending['expected']):status='resolved'
            elif content(snap)==content(pending['before']):status='retry'
            else:status='conflict';intent=pending
        self.m.db.execute('UPDATE StorageJobs SET status=?,inspection=?,intent=?,last_session=?,last_event=?,revision=revision+1,updated=? WHERE id=?',
                          (status,json.dumps(snap),json.dumps(intent) if intent else None,str(s.session),event_id,now(),job['id']))
        self.checked[job['id']]=self.clock()
        self.idle_until.pop(job['id'],None)
        return status

    def interrupt(self,s,cmd):
        job=self.current(s)
        if job and cmd.get('storage',{}).get('job_id')==job['id']:
            self.checked.pop(job['id'],None)
            self.m.db.execute("UPDATE StorageJobs SET status=CASE WHEN intent IS NULL THEN status ELSE 'uncertain' END,last_session=NULL,updated=? WHERE id=?",(now(),job['id']))
