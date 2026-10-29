"""Demand for executable, game-advertised recipes. Facts still require command evidence."""
import math


def ingredients(recipe):
    return recipe.get('inputs') or {recipe['input_id']: recipe.get('input_count', 1)}


def craft_evidence(recipe, evidence):
    before, after = evidence.get('inventory_before'), evidence.get('inventory_after')
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if not all(type(v) is int and v >= 0 for counts in (before, after) for v in counts.values()):
        return False
    expected = {key: -count for key, count in ingredients(recipe).items()}
    expected[recipe['output_id']] = recipe['output_count']
    if any(after.get(k, 0)-before.get(k, 0) != expected.get(k, 0) for k in before.keys() | after.keys() | expected.keys()):
        return False
    if (evidence.get('server_verified') is not True or evidence.get('recipe') != recipe['id']
            or type(evidence.get('crafted_delta')) is not int or evidence['crafted_delta'] != recipe['output_count']):
        return False
    return recipe.get('grid', 2) == 2 or (evidence.get('grid') == 3 and evidence.get('station_opened') is True
                                         and evidence.get('station') == recipe.get('station'))


class CraftingPlanner:
    def __init__(self, memory):
        self.m = memory

    def has_table(self, s):
        return any(b.id == 'minecraft:crafting_table' for b in s.blocks)

    def remembered_table(self, s):
        return bool(self.nearby_memories(s))

    def nearby_memories(self,s):
        rows=self.m.rows("SELECT subject FROM Knowledge WHERE world=? AND status='confirmed' AND subject LIKE ?",
                         (s.world,'placement:'+s.dimension+':minecraft:crafting_table:%'))
        targets=[]
        for row in rows:
            try:x,y,z=map(int,row['subject'].rsplit(':',3)[1:])
            except ValueError:continue
            if math.dist((x,y,z),(s.player.x,s.player.y,s.player.z))>14:continue
            unavailable=self.m.rows("SELECT 1 FROM GoalPlans p JOIN Goals g ON g.id=p.goal_id "
                                    "WHERE p.world=? AND p.subject=? AND g.status='abandoned' LIMIT 1",
                                    (s.world,f'return-table:{s.dimension}:{x}:{y}:{z}'))
            if unavailable:continue
            targets.append(dict(x=x,y=y,z=z,id='minecraft:crafting_table'))
        return sorted(targets,key=lambda p:math.dist((p['x'],p['y'],p['z']),(s.player.x,s.player.y,s.player.z)))[:8]

    def needs_station(self,s):
        inv=s.player.inventory
        tools=all(any(k.endswith(suffix) and v>0 for k,v in inv.items()) for suffix in ('_pickaxe','_axe'))
        return (not tools or inv.get('minecraft:wheat',0)>=3 and inv.get('minecraft:bread',0)<3
                or inv.get('minecraft:cobblestone',0)>=8 and not inv.get('minecraft:furnace',0)
                or sum(v for k,v in inv.items() if k.endswith('_planks'))>=8 and not inv.get('minecraft:chest',0))

    def demand(self, s, output):
        inv = s.player.inventory
        station = self.has_table(s) or self.remembered_table(s)
        pickaxe = any(k.endswith('_pickaxe') and v > 0 for k, v in inv.items())
        axe = any(k.endswith('_axe') and v > 0 for k, v in inv.items())
        if output == 'minecraft:crafting_table':
            return 0 if station or not self.needs_station(s) else 1
        if output.endswith('_planks'):
            total = sum(v for k, v in inv.items() if k.endswith('_planks'))
            return inv.get(output, 0) + max(0, (12 if not pickaxe or not station else 4)-total)
        if output == 'minecraft:stick':
            return 4 if not pickaxe or not axe else 0
        if output.startswith('minecraft:wooden_'):
            return 1 if (output.endswith('_pickaxe') and not pickaxe or output.endswith('_axe') and not axe) else 0
        if output.startswith('minecraft:stone_'):
            stronger = any(inv.get('minecraft:'+tier+'_'+output.split('_')[-1], 0) for tier in ('iron','diamond','netherite'))
            return 0 if stronger else 1
        return {'minecraft:bread': 3, 'minecraft:torch': 8, 'minecraft:furnace': 1, 'minecraft:chest': 1}.get(output, 0)

    def needs_wood(self, s):
        if not {'craft','place','craft_table'} <= set(s.capabilities):
            return False
        raw = sum(v*4 if k.endswith('_log') else v for k,v in s.player.inventory.items() if k.endswith(('_log','_planks')))
        pickaxe = any(k.endswith('_pickaxe') and v > 0 for k,v in s.player.inventory.items())
        return raw < (12 if not pickaxe else 4)

    def proposals(self, s, personality):
        inv = s.player.inventory
        rows = []
        if not self.has_table(s) and self.needs_station(s) and {'approach','observe'}<=set(s.capabilities):
            for target in self.nearby_memories(s):
                rows.append(dict(subject=f"return-table:{s.dimension}:{target['x']}:{target['y']}:{target['z']}",
                                 description='Revisitar a bancada que coloquei nesta região',
                                 reason='A memória contém uma colocação verificada próxima; presença e rota precisam ser revalidadas.',
                                 priority=205,kind='observe',skill='observe_block',params=dict(target=target)))
        if 'place' in s.capabilities and inv.get('minecraft:crafting_table',0)>0 and self.needs_station(s) and not (self.has_table(s) or self.remembered_table(s)):
            for spot in sorted(s.placement_spots, key=lambda p: math.dist((p.x,p.y,p.z),(s.player.x,s.player.y,s.player.z))):
                if (spot.support.x,spot.support.y+1,spot.support.z)!=(spot.x,spot.y,spot.z):
                    continue
                target=dict(x=spot.x,y=spot.y,z=spot.z,id='minecraft:crafting_table')
                rows.append(dict(subject=f"place:{s.dimension}:{spot.x}:{spot.y}:{spot.z}", description='Colocar minha bancada em um espaço livre observado',
                                 reason='Bancada no inventário, apoio sólido e espaço livre anunciados pelo mod.',
                                 priority=220, kind='place', skill='place_workstation',
                                 params=dict(target=target,placement=dict(item_id=target['id'],support=spot.support.model_dump()))))
        for offer in s.recipes:
            recipe=offer.model_dump(mode='json',exclude_unset=True)
            action='craft_table' if offer.grid==3 else 'craft'
            if action not in s.capabilities or self.demand(s,offer.output_id)<=inv.get(offer.output_id,0):
                continue
            if any(inv.get(k,0)<v for k,v in ingredients(recipe).items()):
                continue
            if offer.grid==3 and (offer.station is None or not any(b.id=='minecraft:crafting_table' and
                    (b.x,b.y,b.z)==(offer.station.x,offer.station.y,offer.station.z) for b in s.blocks)):
                continue
            subject='recipe:'+offer.id
            known=self.m.rows("SELECT 1 FROM Knowledge WHERE world=? AND subject=? AND status='confirmed'",(s.world,subject))
            if known:
                prefix='supply:'+offer.id+':'
                completed=self.m.rows("SELECT count(*) n FROM GoalPlans p JOIN Goals g ON g.id=p.goal_id "
                                      "WHERE p.world=? AND p.subject LIKE ? AND g.status='completed'",(s.world,prefix+'%'))[0]['n']
                subject=prefix+str(completed)
            priority=180 if offer.output_id=='minecraft:crafting_table' else 160 if offer.output_id.endswith(('_pickaxe','_axe')) else 130
            if offer.output_id=='minecraft:bread':
                priority=1400 if s.player.food<=8 else 170
            target=offer.station.model_dump() if offer.station else dict(x=math.floor(s.player.x),y=math.floor(s.player.y),z=math.floor(s.player.z))
            target['id']='minecraft:crafting_table' if offer.station else 'minecraft:air'
            rows.append(dict(subject=subject,description='Fabricar '+offer.output_id,
                             reason='Receita desbloqueada anunciada pelo jogo; ingredientes presentes e estoque abaixo da necessidade.',
                             priority=priority+(personality['creativity']-90)*.2,kind=action,
                             skill='craft_table' if offer.grid==3 else 'craft_planks',
                             params=dict(target=target,recipe=recipe)))
        return sorted(rows,key=lambda row:row['priority'],reverse=True)
