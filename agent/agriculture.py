"""Observed planting and conservative native hoe use; never place water or advance growth."""
import json
import math
from datetime import datetime, timedelta, timezone

SEEDS={'minecraft:wheat_seeds':'minecraft:wheat','minecraft:beetroot_seeds':'minecraft:beetroots',
       'minecraft:carrot':'minecraft:carrots','minecraft:potato':'minecraft:potatoes'}

class AgriculturePlanner:
    def __init__(self,memory):self.m=memory

    def pending_drop(self,s):
        """Select a useful observed item near a recent verified harvest.

        Spatial/temporal association only schedules pickup; it never proves the
        entity originated from that harvest, or that its contents were collected.
        """
        if 'pickup' not in s.capabilities or s.player.danger or s.player.food<=8 or s.time>=12000:return None
        cutoff=(datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat()
        events=self.m.rows("SELECT evidence FROM Events WHERE world=? AND session=? AND day=? AND verified=1 "
                           "AND type='crop_harvested' AND timestamp>=? ORDER BY timestamp DESC LIMIT 24",
                           (s.world,str(s.session),s.day,cutoff))
        candidates=[]
        for row in events:
            ev=json.loads(row['evidence']);p=ev.get('target',{});crop=ev.get('before_block')
            if (ev.get('dimension')!=s.dimension or ev.get('server_verified') is not True
                    or ev.get('after_block')!='minecraft:air' or ev.get('before_crop_mature') is not True
                    or type(ev.get('mined_delta')) is not int or ev['mined_delta']<=0
                    or not all(type(p.get(k)) is int for k in ('x','y','z'))):continue
            seeds={seed for seed,plant in SEEDS.items() if plant==crop}
            products={'minecraft:wheat':'minecraft:wheat','minecraft:beetroots':'minecraft:beetroot',
                      'minecraft:carrots':'minecraft:carrot','minecraft:potatoes':'minecraft:potato'}
            useful=seeds|{products.get(crop)}
            for item in s.items:
                stock=s.player.inventory.get(item.item_id,0)
                if item.item_id not in useful or stock>=(8 if item.item_id in seeds else 16):continue
                distance=math.dist((item.x,item.y,item.z),(s.player.x,s.player.y,s.player.z))
                nearby=math.dist((item.x,item.y,item.z),(p['x']+.5,p['y']+.5,p['z']+.5))
                if distance>10 or nearby>2.5:continue
                reserve=item.item_id in seeds and stock<4
                candidates.append((0 if reserve else 1,distance,item.entity_id.int,item))
        return min(candidates,key=lambda row:row[:3],default=(None,None,None,None))[3]

    def planted(self,s,p):
        return self.m.rows("SELECT count(*) n FROM Events WHERE world=? AND type='planted' AND json_extract(evidence,'$.dimension')=? "
                           "AND json_extract(evidence,'$.target.x')=? AND json_extract(evidence,'$.target.y')=? AND json_extract(evidence,'$.target.z')=?",
                           (s.world,s.dimension,p.x,p.y,p.z))[0]['n']

    def crop_subject(self,s,crop):
        base=f'crop:{crop.id}:{crop.x}:{crop.y}:{crop.z}';cycles=self.planted(s,crop)
        return base+f':replanted:{s.dimension}:{cycles}' if cycles else base

    def proposals(self,s,personality):
        if s.time>=12000 or s.player.food<=8 or s.player.danger:return []
        rows=[]
        for site in s.farmland if 'plant' in s.capabilities else []:
            # A new client reports moisture. Wait for real hydration; legacy
            # observations (-1) retain their existing planting contract.
            if getattr(site,'moisture',-1)==0:continue
            for seed,crop in SEEDS.items():
                minimum=3 if seed in ('minecraft:carrot','minecraft:potato') else (2 if getattr(site,'moisture',-1)>=0 else 1)
                if s.player.inventory.get(seed,0)<minimum:continue
                harvests=self.m.rows("SELECT count(*) n FROM Events WHERE world=? AND type='crop_harvested' AND json_extract(evidence,'$.target.x')=? "
                                     "AND json_extract(evidence,'$.target.y')=? AND json_extract(evidence,'$.target.z')=? AND json_extract(evidence,'$.dimension')=?",
                                     (s.world,site.x,site.y,site.z,s.dimension))[0]['n']
                target={k:getattr(site,k) for k in ('x','y','z')}|dict(id=crop)
                rows.append(dict(subject=f'plant:{s.dimension}:{site.x}:{site.y}:{site.z}:{harvests}',description='Repor um cultivo em solo agrícola observado',
                                 reason='Solo arado vazio e semente existente; preservar comida e verificar o plantio sem presumir crescimento.',
                                 priority=135+(personality['creativity']-90)*.2,kind='plant',skill='plant_crop',
                                 params=dict(target=target,planting=dict(item_id=seed,crop_id=crop))))
                break
        # Preparing new ground is optional work: keep two edible roots, a seed
        # reserve, food for recovery, and two points of hoe durability afterward.
        seeds=any(s.player.inventory.get(seed,0)>=(3 if seed in ('minecraft:carrot','minecraft:potato') else 2) for seed in SEEDS)
        food=sum(f.count*f.nutrition for f in s.player.foods)
        if {'till','plant'}<=set(s.capabilities) and s.player.food>12 and food>=6 and seeds and not s.farmland:
            for site in getattr(s,'tilling',[]):
                if site.id not in ('minecraft:dirt','minecraft:grass_block') or site.tool_max_damage-site.tool_damage<3:continue
                water=site.water
                if not (abs(water.x-site.x)<=4 and abs(water.z-site.z)<=4 and water.y in (site.y,site.y+1)):continue
                rows.append(dict(subject=f'till:{s.dimension}:{site.x}:{site.y}:{site.z}',description='Preparar um solo junto à água observada',
                                 reason='Enxada utilizável, água observada e reservas de sementes e comida; confirmar o solo sem presumir hidratação.',
                                 priority=130,kind='till',skill='till_soil',params=dict(target=dict(x=site.x,y=site.y,z=site.z,id=site.id),
                                 tilling={k:getattr(site,k) for k in ('tool_id','tool_slot','tool_damage','tool_max_damage')}|dict(water=water.model_dump()))))
        return rows

    @staticmethod
    def validate_till(s,cmd,ev):
        request=cmd['tilling']; water=request['water']; target=cmd['target']
        before,after=ev.get('inventory_before'),ev.get('inventory_after')
        return (ev.get('server_verified') is True and ev.get('dimension')==s.dimension
                and ev.get('before_block')==target['id'] in ('minecraft:dirt','minecraft:grass_block')
                and ev.get('after_block')=='minecraft:farmland' and ev.get('water')==water and ev.get('water_observed') is True
                and abs(water['x']-target['x'])<=4 and abs(water['z']-target['z'])<=4 and water['y'] in (target['y'],target['y']+1)
                and type(ev.get('moisture')) is int and 0<=ev['moisture']<=7
                and ev.get('tool_plain') is True and ev.get('tool_id')==request['tool_id'] and ev.get('tool_damage_before')==request['tool_damage']
                and type(ev.get('tool_damage_after')) is int and ev['tool_damage_after']==request['tool_damage']+1
                and type(ev.get('used_delta')) is int and ev['used_delta']==1
                and isinstance(before,dict) and isinstance(after,dict) and before==after
                and all(type(v) is int and v>=0 for v in before.values()))

    @staticmethod
    def validate(s,cmd,ev):
        request=cmd['planting'];before,after=ev.get('inventory_before'),ev.get('inventory_after')
        return (ev.get('server_verified') is True and ev.get('dimension')==s.dimension
                and ev.get('before_block')=='minecraft:air' and ev.get('after_block')==SEEDS.get(request['item_id'])==request['crop_id']
                and ev.get('soil')=='minecraft:farmland' and type(ev.get('crop_age')) is int and ev['crop_age']==0
                and type(ev.get('used_delta')) is int and ev['used_delta']==1 and isinstance(before,dict) and isinstance(after,dict)
                and all(type(v) is int and v>=0 for inv in (before,after) for v in inv.values())
                and before.get(request['item_id'],0)-after.get(request['item_id'],0)==1)
