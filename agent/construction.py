"""Persistent shelter projects. Plans are intentions; only correlated server evidence advances steps."""
import json
import math
import time
from pathlib import Path
from uuid import uuid4
from agent.memory import now

BLUEPRINT = json.loads((Path(__file__).resolve().parents[1] / 'mod/src/main/resources/minelife_ai/blueprints/refuge_v1.json').read_text(encoding='utf-8'))
WOODS = ('oak','spruce','birch','jungle','acacia','dark_oak','mangrove','cherry','bamboo','crimson','warped')
PLANKS = {f'minecraft:{wood}_planks' for wood in WOODS}
DOORS = {f'minecraft:{wood}_door' for wood in WOODS}
CAPABILITIES = {'build_shelter','inspect_shelter','enter_shelter','leave_shelter'}


def position(anchor, offset):
    return {k: anchor[k]+offset[i] for i,k in enumerate(('x','y','z'))}


def inside(player, anchor):
    return abs(player.x-anchor['x']-.5)<.4 and abs(player.z-anchor['z']-.5)<.4 and abs(player.y-anchor['y'])<.5


def inventory_valid(value):
    return isinstance(value,dict) and len(value)<=256 and all(type(n) is int and 0<=n<=1000000 for n in value.values())


class ConstructionPlanner:
    def __init__(self,memory,clock=time.monotonic):
        self.m,self.clock=memory,clock
        self.checked={}
        self.reason='Nenhum projeto de abrigo selecionado.'

    def current(self,s):
        rows=self.m.rows("SELECT * FROM ConstructionProjects WHERE world=? AND dimension=? AND status<>'abandoned' ORDER BY created LIMIT 1",(s.world,s.dimension))
        if not rows:return None
        project=rows[0];project['anchor']=json.loads(project['anchor'])
        project['steps']=self.m.rows('SELECT * FROM ConstructionSteps WHERE project=? ORDER BY step',(project['id'],))
        return project

    def prepare(self,s):
        project=self.current(s)
        if project or not CAPABILITIES<=set(s.capabilities) or s.time>=11000 or s.dimension!='minecraft:overworld':return project
        sites=sorted(s.shelter_sites,key=lambda p:math.dist((p.x+.5,p.y,p.z+.5),(s.player.x,s.player.y,s.player.z)))
        if not sites:return None
        anchor=sites[0].model_dump();pid=str(uuid4());stamp=now()
        self.m.db.execute('INSERT INTO ConstructionProjects VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (pid,s.world,s.dimension,BLUEPRINT['id'],json.dumps(anchor),'planned',
                           'Preparar um refúgio pequeno em terreno livre observado; a estrutura ainda não existe.',None,None,stamp,stamp))
        self.m.db.executemany('INSERT INTO ConstructionSteps(project,step) VALUES(?,?)',[(pid,i) for i in range(len(BLUEPRINT['steps']))])
        return self.current(s)

    def requirements(self,s):
        p=self.current(s)
        if not p or p['status']=='ready':return 0,0
        missing=[BLUEPRINT['steps'][step['step']]['role'] for step in p['steps'] if step['status']=='pending']
        return missing.count('plank'),missing.count('door')

    def wood_demand(self,s):
        planks,door=self.requirements(s)
        if not planks and not door:return 0
        needs_door=door and not any(s.player.inventory.get(item,0) for item in DOORS)
        return planks+(6 if needs_door else 0)

    def _proposal(self,s,p,action,step=None,item=None):
        self.m.db.execute('UPDATE ConstructionProjects SET reason=?,updated=? WHERE id=?',(self.reason,now(),p['id']))
        serial=self.m.rows("SELECT count(*) n FROM Events WHERE world=? AND type='shelter_inspected' AND json_extract(evidence,'$.project')=?",(s.world,p['id']))[0]['n']
        token=f'{step}:{p["steps"][step]["revision"]}' if action=='build_shelter' else f'{s.session}:{serial}:{s.day}'
        data=dict(project=p['id'],blueprint=BLUEPRINT['id'],anchor=p['anchor'])
        target=dict(p['anchor'],id='minecraft:air')
        if step is not None:
            data.update(step=step,item_id=item)
            target=dict(position(p['anchor'],BLUEPRINT['steps'][step]['offset']),id=item)
        names={'inspect_shelter':'Verificar o estado real do abrigo planejado',
               'build_shelter':'Construir a próxima etapa do refúgio',
               'enter_shelter':'Entrar no refúgio e fechar a porta',
               'leave_shelter':'Sair do refúgio e retomar as atividades'}
        return dict(subject=f'{action}:{p["id"]}:{token}',description=names[action],reason=self.reason,
                    priority=1250 if action!='build_shelter' else 240,kind=action,skill=action,
                    params=dict(target=target,shelter=data),category='IMMEDIATE' if s.time>=12000 else 'MEDIUM_TERM')

    def propose(self,s,night=False):
        if not CAPABILITIES<=set(s.capabilities):return None
        p=self.current(s)
        if not p:return None
        if math.dist((s.player.x,s.player.y,s.player.z),tuple(p['anchor'][k] for k in ('x','y','z')))>14:
            self.reason='O abrigo lembrado está fora do alcance da navegação local.';return None
        elapsed=self.clock()-self.checked.get((p['id'],str(s.session)),-1e30)
        if p['last_session']!=str(s.session) or elapsed>=15 or p['status']=='verifying':
            self.reason='Inspecionar blocos reais antes de confiar na memória ou concluir proteção.'
            return self._proposal(s,p,'inspect_shelter')
        if p['status']=='ready':
            if night:
                last=self.m.rows('SELECT evidence FROM Events WHERE id=?',(p['last_inspection'],))
                evidence=json.loads(last[0]['evidence']) if last else {}
                if inside(s.player,p['anchor']) and evidence.get('door_open') is False:
                    self.reason='Dentro do refúgio inspecionado, com porta fechada; aguardando o dia e reavaliando a estrutura.'
                    return None
                self.reason='Refúgio próximo inspecionado; entrada e fechamento ainda precisam de confirmação.'
                return self._proposal(s,p,'enter_shelter')
            if inside(s.player,p['anchor']):
                self.reason='O dia permite retomar atividades; sair pela porta sem romper a estrutura.'
                return self._proposal(s,p,'leave_shelter')
            return None
        planks,doors=self.requirements(s)
        inv=s.player.inventory
        enough=sum(inv.get(k,0) for k in PLANKS)>=planks and sum(inv.get(k,0) for k in DOORS)>=doors
        if inside(s.player,p['anchor']) and any(r['status']!='pending' for r in p['steps']) and (night or p['status']=='blocked' or not enough):
            self.reason='O projeto ainda está incompleto; sair pela passagem existente para procurar uma alternativa segura.'
            return self._proposal(s,p,'leave_shelter')
        if night:
            self.reason='Abrigo incompleto; não há proteção confirmada. Construção será reavaliada durante o dia.';return None
        if p['status']=='blocked':
            self.reason=p['reason'];return None
        if not enough:
            self.reason=f'Preparando materiais para o abrigo: faltam reservas para {planks} tábuas e {doors} porta(s).'
            self.m.db.execute('UPDATE ConstructionProjects SET reason=? WHERE id=?',(self.reason,p['id']))
            return None
        next_step=next((r for r in p['steps'] if r['status']=='pending'),None)
        if next_step is None:
            self.reason='Todas as etapas têm evidência; falta verificar a estrutura completa.'
            return self._proposal(s,p,'inspect_shelter')
        index=next_step['step'];allowed=DOORS if BLUEPRINT['steps'][index]['role']=='door' else PLANKS
        item=max((k for k in allowed if inv.get(k,0)>0),key=lambda k:(inv[k],k))
        self.reason=f'Etapa {index+1}/{len(p["steps"])}: material reservado, colocação nativa e prova própria.'
        return self._proposal(s,p,'build_shelter',index,item)

    def validate(self,s,cmd,ev):
        data=cmd.get('shelter',{});p=self.current(s)
        if not p or data.get('project')!=p['id'] or data.get('anchor')!=p['anchor'] or data.get('blueprint')!=BLUEPRINT['id']:
            return False
        if ev.get('server_verified') is not True or ev.get('project')!=p['id'] or ev.get('anchor')!=p['anchor'] or ev.get('blueprint')!=BLUEPRINT['id']:
            return False
        if cmd['action']=='build_shelter':
            index=data.get('step')
            if type(index) is not int or not 0<=index<len(p['steps']) or ev.get('step')!=index:return False
            spec=BLUEPRINT['steps'][index];item=data.get('item_id')
            a,b=ev.get('inventory_before'),ev.get('inventory_after')
            valid=(item in (DOORS if spec['role']=='door' else PLANKS) and ev.get('after_block')==item
                   and ev.get('before_block')=='minecraft:air' and ev.get('face')==spec['face']
                   and ev.get('support')==position(p['anchor'],spec['support'])
                   and ev.get('target')==position(p['anchor'],spec['offset'])
                   and inventory_valid(a) and inventory_valid(b) and a.get(item,0)-b.get(item,0)==1
                   and type(ev.get('used_delta')) is int and ev['used_delta']==1)
            return valid and (spec['role']!='door' or ev.get('door_valid') is True and ev.get('door_open') is False)
        cells=ev.get('cells')
        if not isinstance(cells,list) or len(cells)!=len(p['steps']):return False
        for index,cell in enumerate(cells):
            if (not isinstance(cell,dict) or cell.get('step')!=index or cell.get('pos')!=position(p['anchor'],BLUEPRINT['steps'][index]['offset'])
                    or not isinstance(cell.get('id'),str)):return False
        if any(type(ev.get(key)) is not bool for key in ('floor_solid','interior_clear','door_valid','door_open','entrance_clear','complete','inside','outside')):return False
        if ev['entrance_clear'] and (cells[-1]['id']!='minecraft:air' or ev['door_valid']):return False
        if ev['door_valid'] and cells[-1]['id'] not in DOORS or ev['door_open'] and not ev['door_valid']:return False
        complete=(ev['floor_solid'] and ev['interior_clear'] and ev['door_valid'] and all(
            cell['id'] in (DOORS if BLUEPRINT['steps'][index]['role']=='door' else PLANKS) for index,cell in enumerate(cells)))
        if ev['complete']!=complete:return False
        if cmd['action'] in ('enter_shelter','leave_shelter'):
            xyz=ev.get('position',{})
            offset=(0,0,0) if cmd['action']=='enter_shelter' else (0,0,2)
            destination=position(p['anchor'],offset)
            try:near=math.dist(tuple(float(xyz[k]) for k in ('x','y','z')),(destination['x']+.5,destination['y'],destination['z']+.5))<.6
            except (KeyError,ValueError,TypeError):return False
            viable=complete if cmd['action']=='enter_shelter' else ev['floor_solid'] and ev['interior_clear'] and (ev['door_valid'] or ev['entrance_clear'])
            return viable and not ev['door_open'] and near and ev['inside' if cmd['action']=='enter_shelter' else 'outside']
        return cmd['action']=='inspect_shelter'

    def accept(self,s,cmd,ev,event_id):
        p=self.current(s);pid=p['id']
        if cmd['action']=='build_shelter':
            self.m.db.execute("UPDATE ConstructionSteps SET status='placed',item=?,evidence_id=? WHERE project=? AND step=?",
                              (cmd['shelter']['item_id'],event_id,pid,cmd['shelter']['step']))
            missing=self.m.rows("SELECT 1 FROM ConstructionSteps WHERE project=? AND status='pending'",(pid,))
            status='building' if missing else 'verifying'
            self.m.db.execute('UPDATE ConstructionProjects SET status=?,updated=? WHERE id=?',(status,now(),pid))
        else:
            conflict=False
            for index,cell in enumerate(ev['cells']):
                allowed=DOORS if BLUEPRINT['steps'][index]['role']=='door' else PLANKS
                if cell['id'] in allowed and (BLUEPRINT['steps'][index]['role']!='door' or ev['door_valid']):
                    # Presence after a restart is not proof that our interrupted command placed it.
                    old=p['steps'][index]
                    self.m.db.execute('UPDATE ConstructionSteps SET status=?,item=?,evidence_id=? WHERE project=? AND step=?',
                                      ('placed' if old['status']=='placed' else 'present',cell['id'],event_id,pid,index))
                elif cell['id']=='minecraft:air':
                    revision=p['steps'][index]['revision']+int(p['steps'][index]['status']!='pending')
                    self.m.db.execute("UPDATE ConstructionSteps SET status='pending',item=NULL,evidence_id=?,revision=? WHERE project=? AND step=?",(event_id,revision,pid,index))
                else:conflict=True
            conflict=conflict or not ev['floor_solid'] or not ev['interior_clear']
            status='ready' if ev['complete'] else 'blocked' if conflict else 'building'
            reason='Estrutura completa inspecionada; proteção não é garantia contra todos os perigos.' if ev['complete'] else 'Bloco inesperado, piso ou interior impedem construção; não remover automaticamente.' if conflict else 'Estrutura parcial inspecionada; continuar somente nas células vazias previstas.'
            self.m.db.execute('UPDATE ConstructionProjects SET status=?,reason=?,last_inspection=?,last_session=?,updated=? WHERE id=?',
                              (status,reason,event_id,str(s.session),now(),pid))
        self.checked[(pid,str(s.session))]=self.clock()
