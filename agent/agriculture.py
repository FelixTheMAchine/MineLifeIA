"""Planting on observed existing farmland. No tilling, water placement or accelerated growth."""
SEEDS={'minecraft:wheat_seeds':'minecraft:wheat','minecraft:beetroot_seeds':'minecraft:beetroots',
       'minecraft:carrot':'minecraft:carrots','minecraft:potato':'minecraft:potatoes'}

class AgriculturePlanner:
    def __init__(self,memory):self.m=memory

    def planted(self,s,p):
        return self.m.rows("SELECT count(*) n FROM Events WHERE world=? AND type='planted' AND json_extract(evidence,'$.dimension')=? "
                           "AND json_extract(evidence,'$.target.x')=? AND json_extract(evidence,'$.target.y')=? AND json_extract(evidence,'$.target.z')=?",
                           (s.world,s.dimension,p.x,p.y,p.z))[0]['n']

    def crop_subject(self,s,crop):
        base=f'crop:{crop.id}:{crop.x}:{crop.y}:{crop.z}';cycles=self.planted(s,crop)
        return base+f':replanted:{s.dimension}:{cycles}' if cycles else base

    def proposals(self,s,personality):
        if 'plant' not in s.capabilities or s.time>=12000 or s.player.food<=8 or s.player.danger:return []
        rows=[]
        for site in s.farmland:
            for seed,crop in SEEDS.items():
                if s.player.inventory.get(seed,0)<(3 if seed in ('minecraft:carrot','minecraft:potato') else 1):continue
                harvests=self.m.rows("SELECT count(*) n FROM Events WHERE world=? AND type='crop_harvested' AND json_extract(evidence,'$.target.x')=? "
                                     "AND json_extract(evidence,'$.target.y')=? AND json_extract(evidence,'$.target.z')=? AND json_extract(evidence,'$.dimension')=?",
                                     (s.world,site.x,site.y,site.z,s.dimension))[0]['n']
                target={**site.model_dump(),'id':crop}
                rows.append(dict(subject=f'plant:{s.dimension}:{site.x}:{site.y}:{site.z}:{harvests}',description='Repor um cultivo em solo agrícola observado',
                                 reason='Solo arado vazio e semente existente; preservar comida e verificar o plantio sem presumir crescimento.',
                                 priority=135+(personality['creativity']-90)*.2,kind='plant',skill='plant_crop',
                                 params=dict(target=target,planting=dict(item_id=seed,crop_id=crop))))
                break
        return rows

    @staticmethod
    def validate(s,cmd,ev):
        request=cmd['planting'];before,after=ev.get('inventory_before'),ev.get('inventory_after')
        return (ev.get('server_verified') is True and ev.get('dimension')==s.dimension
                and ev.get('before_block')=='minecraft:air' and ev.get('after_block')==SEEDS.get(request['item_id'])==request['crop_id']
                and ev.get('soil')=='minecraft:farmland' and type(ev.get('crop_age')) is int and ev['crop_age']==0
                and type(ev.get('used_delta')) is int and ev['used_delta']==1 and isinstance(before,dict) and isinstance(after,dict)
                and all(type(v) is int and v>=0 for inv in (before,after) for v in inv.values())
                and before.get(request['item_id'],0)-after.get(request['item_id'],0)==1)
