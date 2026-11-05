"""Persistent focus over native projects; dependencies never authorize physical actions."""
import hashlib
import json
import math
import time
from uuid import uuid4
from agent.memory import now
from agent.construction import BLUEPRINT, PLANKS, DOORS
from agent.crafting import ingredients
from agent.motivation import MotivationEngine
from agent.needs import project_needs


SCHEMA = '''
CREATE TABLE IF NOT EXISTS LongProjects(id TEXT PRIMARY KEY,world TEXT NOT NULL,dimension TEXT NOT NULL,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,
 condition TEXT NOT NULL,deficits TEXT NOT NULL,fingerprint TEXT NOT NULL,stagnation INTEGER NOT NULL DEFAULT 0,
 retry_after REAL NOT NULL DEFAULT 0,reason TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,
 UNIQUE(world,dimension,source_kind,source_id));
CREATE INDEX IF NOT EXISTS long_projects_world ON LongProjects(world,dimension,status);
CREATE TABLE IF NOT EXISTS ProjectDependencies(project TEXT NOT NULL,node TEXT NOT NULL,status TEXT NOT NULL,
 requires TEXT NOT NULL,detail TEXT NOT NULL,PRIMARY KEY(project,node),FOREIGN KEY(project) REFERENCES LongProjects(id));
CREATE TABLE IF NOT EXISTS ProjectGoalLinks(project TEXT NOT NULL,goal TEXT NOT NULL,reason TEXT NOT NULL,
 created TEXT NOT NULL,PRIMARY KEY(project,goal),FOREIGN KEY(project) REFERENCES LongProjects(id));
CREATE TABLE IF NOT EXISTS ProjectDecisions(id TEXT PRIMARY KEY,project TEXT NOT NULL,kind TEXT NOT NULL,
 reason TEXT NOT NULL,context TEXT NOT NULL,created TEXT NOT NULL,FOREIGN KEY(project) REFERENCES LongProjects(id));
'''


class ProjectManager:
    MAX_STAGNATION=24
    RETRY_SECONDS=60

    def __init__(self,memory,clock=time.time,safety_limits=None):
        self.m,self.clock=memory,clock
        self.safety_limits=safety_limits or MotivationEngine(memory).safety_limits

    def _decision(self,pid,kind,reason,context=None):
        self.m.db.execute('INSERT INTO ProjectDecisions VALUES(?,?,?,?,?,?)',
                          (str(uuid4()),pid,kind,reason,json.dumps(context or {},sort_keys=True),now()))

    def _proof(self,s,eid,kind,link):
        rows=self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND type=? AND verified=1',(eid,s.world,kind))
        if not rows:return False
        ev=json.loads(rows[0]['evidence'])
        dimension=ev.get('dimension',ev.get('after',{}).get('dimension'))
        return ev.get('server_verified') is True and dimension==s.dimension and ev.get(link[0])==link[1]

    def _sources(self,s):
        inv=s.player.inventory
        for p in self._native_rows(s,'ConstructionProjects',('ready','abandoned')):
            steps=self.m.rows('SELECT step,status FROM ConstructionSteps WHERE project=? ORDER BY step',(p['id'],))
            pending=[BLUEPRINT['steps'][r['step']]['role'] for r in steps if r['status']=='pending']
            wood=sum(inv.get(k,0) for k in PLANKS)
            door=bool(any(inv.get(k,0) for k in DOORS))
            demand=pending.count('plank')+(6 if 'door' in pending and not door else 0)
            deficits={'planks':max(0,demand-wood)} if demand>wood else {}
            complete=p['status']=='ready' and any(self._proof(s,p['last_inspection'],kind,('project',p['id']))
                                                  for kind in ('shelter_inspected','shelter_entered','shelter_left'))
            if complete:
                ev=json.loads(self.m.rows('SELECT evidence FROM Events WHERE id=?',(p['last_inspection'],))[0]['evidence'])
                complete=ev.get('project')==p['id'] and ev.get('complete') is True
            yield dict(kind='shelter',source=p['id'],native=p['status'],complete=complete,deficits=deficits,
                       deficit_keys=['planks'],
                       location=json.loads(p['anchor']), capabilities=['build_shelter','inspect_shelter','enter_shelter','leave_shelter'],
                       materials={k:v for k,v in inv.items() if k in PLANKS or k in DOORS or k.endswith('_log')},
                       benefit='Refugio local reutilizavel; protecao depende da inspecao fisica completa.',
                       verified_progress=self.m.rows("SELECT count(*) n FROM ConstructionSteps st JOIN Events e ON e.id=st.evidence_id "
                                                    "WHERE st.project=? AND st.status!='pending' AND e.world=? AND e.verified=1 "
                                                    "AND json_extract(e.evidence,'$.server_verified')=1 AND json_extract(e.evidence,'$.dimension')=?",
                                                    (p['id'],s.world,s.dimension))[0]['n'],
                       priority=240,condition='Estrutura completa inspecionada pelo executor nativo',
                       progress=[(r['step'],r['status']) for r in steps],
                       nodes=[('resources','blocked' if deficits else 'ready',[],dict(required_planks=demand,deficits=deficits)),
                              ('execute','completed' if not pending else 'ready' if not deficits and 'build_shelter' in s.capabilities else 'blocked',['resources'],dict(skill='build_shelter')),
                              ('verify','completed' if complete else 'ready' if not pending and 'inspect_shelter' in s.capabilities else 'blocked',['execute'],dict(skill='inspect_shelter'))])
        for p in self._native_rows(s,'FurnaceJobs',('completed','recovered')):
            r=json.loads(p['recipe']);snap=json.loads(p['inspection']) if p['inspection'] else None
            deficit={}
            if p['status'] in ('planned','empty','recoverable'):
                for key,slot in (('input_id',0),('fuel_id',1)):
                    item=r.get(key)
                    loaded=bool(snap and snap['slots'][slot]['id']==item and snap['slots'][slot]['count']>0)
                    if item and not loaded and inv.get(item,0)<1:deficit[item]=1
            complete=p['status'] in ('completed','recovered') and any(self._proof(s,p['last_event'],k,('job_id',p['id'])) for k in ('cooked','furnace_recovered'))
            yield dict(kind='furnace',source=p['id'],native=p['status'],complete=complete,deficits=deficit,
                       deficit_keys=[item for item in (r.get('input_id'),r.get('fuel_id')) if item],
                       location=json.loads(p['station']), capabilities=['furnace_inspect','furnace_load','furnace_take'],
                       materials={k:inv.get(k,0) for k in (r.get('input_id'),r.get('fuel_id')) if k},
                       benefit='Transformar uma unidade em '+r['output_id']+'; resultado exige retirada verificada.',
                       verified_progress=int(self._proof(s,p['load_event'],'furnace_loaded',('job_id',p['id'])))+int(complete),
                       priority=235,condition='Saida ou recuperacao retirada e inventario confirmado pelo executor',
                       progress=[p['status'],[(c['id'],c['count']) for c in snap['slots']] if snap else None,bool(p['load_event'])],
                       nodes=[('resources','blocked' if deficit else 'ready',[],dict(deficits=deficit)),
                              ('execute','completed' if p['load_event'] else 'ready' if not deficit and 'furnace_load' in s.capabilities else 'blocked',['resources'],dict(skill='furnace_load')),
                              ('verify','completed' if complete else 'ready' if p['status'] in ('ready','recoverable') and 'furnace_take' in s.capabilities else 'blocked',['execute'],dict(skill='furnace_take'))])

    def _native_rows(self,s,table,terminal):
        placeholders=','.join('?' for _ in terminal)
        # All pending native work survives a long history of completed jobs.
        pending=self.m.rows(f'SELECT * FROM {table} WHERE world=? AND dimension=? AND status NOT IN ({placeholders}) ORDER BY created',
                            (s.world,s.dimension,*terminal))
        history=self.m.rows(f'SELECT * FROM {table} WHERE world=? AND dimension=? AND status IN ({placeholders}) ORDER BY created DESC LIMIT 8',
                            (s.world,s.dimension,*terminal))
        return pending+history

    def _opportunity(self,s,source):
        if not project_needs(s,self.safety_limits(s.world))['risk']['work_allowed']['value'] or s.time>=12000:
            return False
        caps=set(s.capabilities);inv=s.player.inventory;deficits=source['deficits']
        nearby=math.dist((s.player.x,s.player.y,s.player.z),tuple(source['location'][k] for k in ('x','y','z')))<=14
        actionable=any(node in ('execute','verify') and status=='ready' and detail.get('skill') in caps
                       for node,status,_,detail in source['nodes'])
        if nearby and (set(source['capabilities'])<=caps or actionable) and source['native'] not in ('blocked','lost','conflict','processing'):
            return True
        needed=lambda item:item in deficits or bool(deficits.get('planks') and (item in PLANKS or item.endswith('_log')))
        if 'craft' in caps and any(needed(r.output_id) and all(inv.get(item,0)>=n for item,n in ingredients(r.model_dump()).items()) for r in s.recipes):
            return True
        if 'pickup' in caps and any(needed(item.item_id) and math.dist((s.player.x,s.player.y,s.player.z),(item.x,item.y,item.z))<=14 for item in s.items):
            return True
        return bool(deficits.get('planks') and {'approach','break','collect'}<=caps and any(b.log and math.dist((s.player.x,s.player.y,s.player.z),(b.x,b.y,b.z))<=14 for b in s.blocks))

    def _rationale(self,s,source):
        preferences=[]
        for p in self.m.rows('SELECT category,subject,weight,sources FROM Preferences WHERE world=? ORDER BY abs(weight) DESC LIMIT 8',(s.world,)):
            ids=json.loads(p['sources'])
            proofs=[eid for eid in ids if self.m.rows('SELECT 1 FROM Events WHERE id=? AND world=? AND verified=1',(eid,s.world))]
            if proofs:preferences.append(dict(category=p['category'],subject=p['subject'],weight=p['weight'],sources=proofs))
        return dict(need='Concluir dependencia nativa pendente: '+source['kind'],expected_benefit=source['benefit'],
                    available_capabilities=sorted(set(source['capabilities'])&set(s.capabilities)),
                    required_capabilities=source['capabilities'],observed_materials=source['materials'],
                    deficits=source['deficits'],evidenced_preferences=preferences,
                    preference_role='Context only; native dependency priority selects focus.',
                    observation=dict(session=str(s.session),seq=s.seq,dimension=s.dimension))

    def sync(self,s):
        """Call once per planning cycle, never for every sensor frame or proposal."""
        sources=list(self._sources(s))
        focused=self.focus(s)
        selected=(focused['source_kind'],focused['source_id']) if focused else None
        if selected is None:
            available=[source for source in sources if not source['complete'] and self._opportunity(s,source)
                       and self.allows(s,source['kind'],source['source'])]
            if available:
                candidate=max(available,key=lambda source:source['priority'])
                selected=(candidate['kind'],candidate['source'])
        for source in sources:
            signature=hashlib.sha256(json.dumps([source['native'],source['progress'],source['deficits'],
                                                [(n[0],n[1]) for n in source['nodes']]],sort_keys=True).encode()).hexdigest()
            rows=self.m.rows('SELECT * FROM LongProjects WHERE world=? AND dimension=? AND source_kind=? AND source_id=?',
                             (s.world,s.dimension,source['kind'],source['source']))
            old=rows[0] if rows else None;pid=old['id'] if old else str(uuid4());stamp=now()
            if old and old['status']=='abandoned':continue
            changed=not old or old['fingerprint']!=signature
            saved=self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? "
                              "AND json_type(context,'$.best_deficits')='object' ORDER BY rowid DESC LIMIT 1",(pid,))
            baseline=json.loads(saved[0]['context']) if saved else {}
            prior=json.loads(old['deficits']) if old else source['deficits']
            best=baseline.get('best_deficits',dict.fromkeys(source['deficit_keys'],0)|prior)
            improved=bool(old and (source['verified_progress']>baseline.get('best_progress',0)
                                  or any(source['deficits'].get(k,0)<v for k,v in best.items())))
            best={k:min(best.get(k,v),source['deficits'].get(k,0)) for k,v in (best|source['deficits']).items()}
            attempts=self.m.rows("SELECT count(DISTINCT c.id) n FROM Commands c JOIN ExperimentGoals x ON x.experiment=c.experiment "
                                 "JOIN ProjectGoalLinks l ON l.goal=x.goal_id WHERE l.project=? AND c.world=? "
                                 "AND c.status IN ('success','failed','timeout')",(pid,s.world))[0]['n']
            new_attempt=attempts>baseline.get('attempts',0)
            opportunity=selected==(source['kind'],source['source']) and self._opportunity(s,source)
            stagnant=0 if not old or improved else old['stagnation']+int(opportunity or new_attempt)
            state='completed' if source['complete'] else 'blocked' if source['native'] in ('blocked','lost','conflict') else 'active'
            reason='Acompanhar dependencias reais e conservar o progresso do executor.';retry=0.
            if state=='active' and not project_needs(s,self.safety_limits(s.world))['risk']['work_allowed']['value']:
                state='suspended';reason='Condicao fisiologica ou controle impede trabalho; preservar a intencao e revalidar depois.'
            if state=='active' and stagnant>=self.MAX_STAGNATION:
                if old and old['retry_after'] and self.clock()>=old['retry_after']:
                    stagnant=0;reason='Reavaliar depois do cooldown; nenhuma acao antiga sera repetida por esta camada.'
                else:
                    state='stalled';retry=old['retry_after'] if old and old['retry_after'] else self.clock()+self.RETRY_SECONDS
                    reason='Sem ganho de recursos ou progresso em 24 oportunidades relevantes; considerar outras atividades.'
            if state=='completed':reason='Condicao confirmada pelo registro verificado do executor nativo.'
            if state=='blocked':reason='Executor nativo bloqueado ou conteudo incerto; preservar recursos e buscar outra oportunidade.'
            if not old:
                self.m.db.execute('INSERT INTO LongProjects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (pid,s.world,s.dimension,source['kind'],source['source'],state,source['priority'],source['condition'],
                                   json.dumps(source['deficits']),signature,stagnant,retry,reason,stamp,stamp))
            else:
                self.m.db.execute('UPDATE LongProjects SET status=?,deficits=?,fingerprint=?,stagnation=?,retry_after=?,reason=?,updated=? WHERE id=?',
                                  (state,json.dumps(source['deficits']),signature,stagnant,retry,reason,stamp,pid))
            for node,status,requires,detail in source['nodes']:
                self.m.db.execute('INSERT INTO ProjectDependencies VALUES(?,?,?,?,?) ON CONFLICT(project,node) DO UPDATE SET '
                                  'status=excluded.status,requires=excluded.requires,detail=excluded.detail',
                                  (pid,node,status,json.dumps(requires),json.dumps(detail)))
            if not old or changed or new_attempt or old['status']!=state:
                kind='adopted' if not old else 'completed' if state=='completed' else 'replanned' if changed else state
                self._decision(pid,kind,reason,dict(deficits=source['deficits'],native_status=source['native'],
                                                   best_deficits=best,best_progress=max(source['verified_progress'],baseline.get('best_progress',0)),
                                                   attempts=attempts,relevant_opportunity=opportunity,
                                                   rationale=self._rationale(s,source)))

    def suspend(self,s,reason):
        for p in self.m.rows("SELECT id FROM LongProjects WHERE world=? AND dimension=? AND status='active'",(s.world,s.dimension)):
            self.m.db.execute("UPDATE LongProjects SET status='suspended',reason=?,updated=? WHERE id=?",(reason,now(),p['id']))
            self._decision(p['id'],'suspended',reason)

    def focus(self,s):
        rows=self.m.rows("SELECT * FROM LongProjects WHERE world=? AND dimension=? AND status='active' ORDER BY priority DESC,created,id",(s.world,s.dimension))
        if not rows:return None
        available={(source['kind'],source['source']) for source in self._sources(s)
                   if not source['complete'] and self._opportunity(s,source)}
        return next((row for row in rows if (row['source_kind'],row['source_id']) in available),None)

    def allows(self,s,kind,source_id):
        rows=self.m.rows('SELECT status,retry_after FROM LongProjects WHERE world=? AND dimension=? AND source_kind=? AND source_id=?',
                         (s.world,s.dimension,kind,source_id))
        if not rows:return True
        p=rows[0]
        return p['status']!='abandoned' and (p['status']!='stalled' or self.clock()>=p['retry_after'])

    def bonus(self,s,kind,params):
        if not project_needs(s,self.safety_limits(s.world))['risk']['work_allowed']['value']:return 0
        p=self.focus(s)
        if not p:return 0
        if params.get('shelter',{}).get('project')==p['source_id'] or params.get('furnace',{}).get('job_id')==p['source_id']:return 35
        deficits=json.loads(p['deficits']);item=params.get('recipe',{}).get('output_id')
        if kind=='storage_withdraw':item=params.get('storage',{}).get('item_id')
        if kind=='mine':
            block=params.get('target',{}).get('id')
            item={'minecraft:coal_ore':'minecraft:coal','minecraft:iron_ore':'minecraft:raw_iron','minecraft:stone':'minecraft:cobblestone'}.get(block,block)
        if item in deficits:return 35
        if deficits.get('planks') and (item in PLANKS or kind in ('log','mine') and params.get('target',{}).get('id','').endswith('_log')):return 35
        return 0

    def link(self,s,gid,kind,params):
        if not self.bonus(s,kind,params):return
        if not self.m.rows('SELECT id FROM Goals WHERE id=? AND world=?',(gid,s.world)):return
        p=self.focus(s)
        self.m.db.execute('INSERT OR IGNORE INTO ProjectGoalLinks VALUES(?,?,?,?)',
                          (p['id'],gid,'Objetivo executavel atende uma dependencia observada do projeto em foco.',now()))

    def abandon(self,s,pid,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Abandono exige justificativa')
        row=self.m.rows('SELECT * FROM LongProjects WHERE id=? AND world=? AND dimension=?',(pid,s.world,s.dimension))
        if not row:raise ValueError('Projeto fora do mundo atual')
        p=row[0];field='shelter' if p['source_kind']=='shelter' else 'furnace'
        key='project' if field=='shelter' else 'job_id'
        for cmd in self.m.rows("SELECT payload FROM Commands WHERE world=? AND status='sent'",(s.world,)):
            if json.loads(cmd['payload']).get(field,{}).get(key)==p['source_id']:
                raise ValueError('Aguardar cancelamento ou resultado do comando antes de abandonar')
        table='ConstructionProjects' if field=='shelter' else 'FurnaceJobs'
        native=self.m.rows(f'SELECT status FROM {table} WHERE id=?',(p['source_id'],))[0]
        self.m.db.execute(f'UPDATE {table} SET status=?,last_session=NULL,updated=? WHERE id=?',
                          ('abandoned' if field=='shelter' else 'conflict',now(),p['source_id']))
        self.m.db.execute("UPDATE LongProjects SET status='abandoned',reason=?,updated=? WHERE id=?",(reason,now(),pid))
        self._decision(pid,'abandoned',reason,dict(native_status=native['status']))

    def resume(self,s,pid,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Retomada exige justificativa')
        rows=self.m.rows('SELECT * FROM LongProjects WHERE id=? AND world=? AND dimension=?',(pid,s.world,s.dimension))
        if not rows:
            raise ValueError('Projeto fora do mundo atual')
        p=rows[0]
        field='shelter' if p['source_kind']=='shelter' else 'furnace'
        key='project' if field=='shelter' else 'job_id'
        for cmd in self.m.rows("SELECT payload FROM Commands WHERE world=? AND status='sent'",(s.world,)):
            if json.loads(cmd['payload']).get(field,{}).get(key)==p['source_id']:
                raise ValueError('Aguardar cancelamento ou resultado do comando antes de retomar')
        # A resumed intention must obtain a fresh physical inspection, including
        # within the same session. Preserve the native object and its evidence.
        table='ConstructionProjects' if p['source_kind']=='shelter' else 'FurnaceJobs'
        original=self.m.rows(f'SELECT * FROM {table} WHERE id=?',(p['source_id'],))[0]
        native=original['status'];context={}
        if p['status']=='abandoned':
            decisions=self.m.rows("SELECT context FROM ProjectDecisions WHERE project=? AND kind='abandoned' ORDER BY rowid DESC LIMIT 1",(pid,))
            if not decisions:raise ValueError('Estado nativo anterior indisponivel; reinspecao manual necessaria')
            native=json.loads(decisions[0]['context'])['native_status']
        if field=='furnace' and native=='conflict':
            station=json.loads(original['station'])
            competing=self.m.rows("SELECT 1 FROM FurnaceJobs WHERE world=? AND dimension=? AND id<>? "
                                  "AND status NOT IN ('completed','recovered','lost','conflict') "
                                  "AND json_extract(station,'$.x')=? AND json_extract(station,'$.y')=? "
                                  "AND json_extract(station,'$.z')=? LIMIT 1",
                                  (s.world,s.dimension,p['source_id'],station['x'],station['y'],station['z']))
            if competing:raise ValueError('Outro preparo ativo ocupa a mesma fornalha; revalidar antes de retomar')
            attempts=self.m.rows('SELECT kind,sum(attempts) n FROM GoalPlans WHERE world=? '
                                 "AND kind IN ('furnace_inspect','furnace_load','furnace_take') "
                                 "AND json_extract(params,'$.furnace.job_id')=? GROUP BY kind",(s.world,p['source_id']))
            context['furnace_resume']=dict(token=str(uuid4()),revision=original['revision'],
                attempts={row['kind']:row['n'] for row in attempts},previous_status=native,
                previous_load_event=original['load_event'],previous_last_event=original['last_event'],
                previous_inspection=json.loads(original['inspection']) if original['inspection'] else None)
            # Preserve old evidence in the decision, but do not attribute a later
            # output to a load whose continuity became uncertain during conflict.
            self.m.db.execute("UPDATE FurnaceJobs SET status='planned',load_event=NULL,last_session=NULL,updated=? WHERE id=?",
                              (now(),p['source_id']))
        elif p['status']=='abandoned':
            self.m.db.execute(f'UPDATE {table} SET status=?,last_session=NULL,updated=? WHERE id=?',(native,now(),p['source_id']))
        else:
            self.m.db.execute(f'UPDATE {table} SET last_session=NULL,updated=? WHERE id=?',(now(),p['source_id']))
        self.m.db.execute("UPDATE LongProjects SET status='suspended',fingerprint='',stagnation=0,retry_after=0,reason=?,updated=? WHERE id=?",(reason,now(),pid))
        self._decision(pid,'resumed',reason,context)
