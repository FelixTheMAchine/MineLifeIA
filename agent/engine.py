import json
import math
import time
from uuid import uuid4
from agent.memory import now
from agent.motivation import MotivationEngine, PERSONALITY
from agent.needs import project_needs
from agent.interests import InterestManager
from agent.goals import GoalManager
from agent.skills import SkillRegistry
from agent.exploration import ExplorationManager, region
from agent.autobiography import Autobiography
from agent.philosophy import PhilosophicalReflectionEngine
from agent.food import FoodAcquisitionManager
from agent.crafting import CraftingPlanner, ingredients, craft_evidence
from agent.construction import ConstructionPlanner, CAPABILITIES as SHELTER_ACTIONS
from agent.night import NightSurvivalManager
from agent.mining import MiningPlanner, mining_evidence
from agent.cooking import CookingManager, ACTIONS as FURNACE_ACTIONS
from agent.cognition import CognitiveLanguageEngine
from agent.identity import IdentityEngine
from agent.failure_assessment import assess_failure
from agent.routes import RouteManager
from agent.agriculture import AgriculturePlanner
from agent.storage import StorageManager, MATERIALS as STORAGE_MATERIALS
from agent.projects import ProjectManager
from agent.social import SocialManager, ACTIONS as SOCIAL_ACTIONS
from agent.mind import ContextBuilder, ReflectionManager


def valid_inventory(value):
    return isinstance(value, dict) and len(value) <= 256 and all(isinstance(k,str) and type(v) is int and 0 <= v <= 1000000 for k,v in value.items())


class CognitiveEngine:
    """Cognição por eventos; um executor físico, planejamento em frequência controlada."""
    def __init__(self, memory, journal, settings=None, clock=time.monotonic, mind_config=None):
        self.m, self.journal, self.clock = memory, journal, clock
        settings = settings or {}
        self.interval = max(.5, min(10, settings.get('decision_interval', 2.0)))
        self.goals = GoalManager(memory, max(1, min(32, settings.get('max_active_goals', 8))))
        self.skills, self.interests = SkillRegistry(), InterestManager(memory)
        self.foods = FoodAcquisitionManager()
        self.crafting = CraftingPlanner(memory)
        self.mining = MiningPlanner(memory,self.crafting)
        self.construction=ConstructionPlanner(memory,clock)
        self.cooking=CookingManager(memory,self.construction,clock)
        self.night=NightSurvivalManager(self.construction)
        self.motivation, self.exploration = MotivationEngine(memory), ExplorationManager(memory)
        self.autobiography = Autobiography(memory)
        self.language=CognitiveLanguageEngine(memory,self.autobiography,self.skills)
        self.mind=ReflectionManager(memory,self.language,mind_config)
        self.mind_context=ContextBuilder(memory,self.language,mind_config)
        self.mind.set_epoch(0,str(uuid4()))
        self.identity=IdentityEngine(memory)
        self.routes=RouteManager(memory)
        self.agriculture=AgriculturePlanner(memory)
        self.storage=StorageManager(memory,self.construction,self.crafting,clock)
        self.projects=ProjectManager(memory,safety_limits=self.motivation.safety_limits)
        self.social=SocialManager(memory)
        self.philosophy = PhilosophicalReflectionEngine(memory, self.autobiography)
        self.sessions, self.last_plan, self.command_sent = {}, {}, {}
        self.latest, self.last_seen, self.control = None, 0.0, None
        self.state, self.reason, self.dominant = 'PAUSED', 'Aguardando autorização local', 'DISCOVERY'
        self.planning_cycles = 0
        self.initialized = set()
        self.advice = None
        self.m.db.execute("UPDATE SocialAttempts SET status='uncertain' WHERE status='intent'")
        self.m.db.execute("UPDATE SocialPeople SET last_session=NULL WHERE EXISTS (SELECT 1 FROM SocialAttempts a "
                          "WHERE a.world=SocialPeople.world AND a.person_uuid=SocialPeople.person_uuid AND a.status='uncertain')")
        self.m.db.execute("UPDATE Commands SET status='interrupted' WHERE status='sent'")
        self.m.db.execute("UPDATE Experiments SET status='interrupted' WHERE status='running'")
        self.m.db.execute("UPDATE Goals SET status='suspended' WHERE status='running'")
        self.m.db.commit()

    def _state(self, s, state, reason):
        self.state, self.reason = state, reason
        self.m.db.execute('INSERT INTO CognitiveState VALUES(?,?,?,?,?) ON CONFLICT(world) DO UPDATE SET '
                          'state=excluded.state,reason=excluded.reason,motivation=excluded.motivation,updated=excluded.updated',
                          (s.world, state, reason, self.dominant, now()))

    def _event(self, s, kind, text, evidence, dedup):
        return self.m.event(s.world, str(s.session), s.day, kind, text, True, {**evidence,'dimension':s.dimension}, dedup)

    def _goal_id(self, exp):
        rows = self.m.rows('SELECT goal_id FROM ExperimentGoals WHERE experiment=?', (exp['id'],))
        return rows[0]['goal_id'] if rows else exp['id']

    def _command(self, s, exp, action, **extra):
        payload = dict(id=str(uuid4()), action=action, target=json.loads(exp['target']), timeout_ms=20000, **extra)
        if action.startswith('storage_'):self.storage.prepare_command(s,payload)
        if action in SOCIAL_ACTIONS:self.social.prepare_command(s,payload)
        self.m.db.execute('INSERT INTO Commands VALUES(?,?,?,?,?,?,?,?)',
                          (payload['id'], s.world, str(s.session), exp['id'], json.dumps(payload), 'sent', None, now()))
        self.command_sent[payload['id']] = self.clock()
        self._state(s, 'EXPLORING' if action == 'explore' else 'EXPERIMENTING',
                    {'approach': 'Aproximando de um alvo observado', 'break': 'Testando quebra de tronco',
                     'collect': 'Verificando coleta', 'observe': 'Verificando um bloco',
                     'mine': 'Minerando um recurso exposto com ferramenta adequada',
                     'plant':'Plantando em solo agrícola existente',
                     'till':'Preparando solo próximo de água observada',
                     'storage_inspect':'Revalidando baú e inventário',
                     'storage_deposit':'Guardando uma unidade excedente no baú',
                     'storage_withdraw':'Recuperando uma unidade para um projeto',
                     'social_observe':'Confirmando um encontro com pessoa observada',
                     'social_contact':'Verificando a interface de contato MCA',
                     'furnace_load':'Carregando ingrediente e combustível', 'furnace_inspect':'Inspecionando o preparo persistido',
                     'furnace_take':'Retirando itens da fornalha com verificação',
                     'craft': 'Fabricando na grade 2×2', 'craft_table': 'Fabricando na bancada 3×3',
                     'place': 'Colocando estação no espaço observado', 'explore': 'Avançando para fronteira local validada',
                     'build_shelter':'Construindo uma etapa do abrigo', 'inspect_shelter':'Verificando o abrigo no mundo',
                     'enter_shelter':'Entrando no abrigo', 'leave_shelter':'Saindo do abrigo para retomar atividades',
                     'eat': 'Recuperando a fome com alimento disponível', 'pickup': 'Recolhendo um item observado',
                     'harvest': 'Colhendo cultivo maduro observado', 'sleep': 'Tentando repouso noturno em cama observada'}[action])
        return payload

    def _knowledge(self, s, subject, status, eid):
        existing = self.m.rows('SELECT * FROM Knowledge WHERE world=? AND subject=?', (s.world, subject))
        ids = json.loads(existing[0]['evidence_ids']) if existing else []
        ids = list(dict.fromkeys(ids + [eid]))
        if existing and existing[0]['status'] == 'confirmed': status = 'confirmed'
        self.m.db.execute('INSERT INTO Knowledge VALUES(?,?,?,?) ON CONFLICT(world,subject) DO UPDATE SET '
                          'status=excluded.status,evidence_ids=excluded.evidence_ids', (s.world, subject, status, json.dumps(ids)))

    def _inventory_gains(self,s,cmd,evidence,origin):
        """Record server inventory increases separately; coincidence does not prove a drop's origin."""
        before,after=evidence.get('inventory_before'),evidence.get('inventory_after')
        if not valid_inventory(before) or not valid_inventory(after):return
        for item,count in sorted(after.items()):
            gained=count-before.get(item,0)
            if gained<=0:continue
            proof=dict(item_id=item,before_count=before.get(item,0),after_count=count,
                       command=cmd['id'],removal_event=origin,server=evidence)
            eid=self._event(s,'inventory_gained',f"Durante esta ação, meu inventário ganhou {gained} unidade(s) de {item}. O aumento foi confirmado pelo servidor; não identifiquei individualmente a origem desses itens.",
                            proof,cmd['id']+':inventory:'+item)
            self._knowledge(s,'inventory:'+item,'confirmed',eid)

    def _complete(self, s, exp, eid, subject):
        gid = self._goal_id(exp)
        self.m.db.execute("UPDATE Experiments SET status='completed',phase='done',evidence_ids=? WHERE id=?", (json.dumps([eid]), exp['id']))
        self.m.db.execute("UPDATE Goals SET status='completed' WHERE id=?", (gid,))
        self.m.db.execute("UPDATE Hypotheses SET status='confirmed',evidence_ids=? WHERE id=?", (json.dumps([eid]), exp['hypothesis']))
        self.mind.record_outcome(s,gid,eid,success=True)
        plans = self.m.rows('SELECT * FROM GoalPlans WHERE goal_id=?', (gid,))
        if plans:
            self.skills.record(self.m, s.world, plans[0]['skill'], True)
            self.m.db.execute("UPDATE Questions SET status='answered' WHERE world=? AND subject=?", (s.world, plans[0]['subject']))
        event_type = self.m.rows('SELECT type FROM Events WHERE id=?', (eid,))[0]['type']
        if event_type in ('construction_step','shelter_inspected','furnace_inspected','furnace_loaded'):
            self._state(s,'PLANNING','Etapa auditada; reavaliando o projeto e as necessidades')
            return
        self.interests.update(s, self.interests.topic(subject), eid)
        self.identity.observe(s,eid)
        self.motivation.learn(s, eid, True)
        event_type = self.m.rows('SELECT type FROM Events WHERE id=?', (eid,))[0]['type']
        knowledge = self.m.rows('SELECT evidence_ids FROM Knowledge WHERE world=? AND subject=?', (s.world, subject))
        first_evidence = bool(knowledge and len(json.loads(knowledge[0]['evidence_ids'])) == 1)
        importance = {'crafted': .82, 'collected': .8, 'region_reached': .68, 'observed': .35,
                      'slept': .86, 'crop_harvested': .74, 'placed': .85,'shelter_completed':.94,
                      'shelter_entered':.8,'shelter_left':.65,'resource_mined':.74,'cooked':.86}.get(event_type, .3)
        self.autobiography.record(s.world, eid, self.interests.topic(subject), importance,
                                  1.0 if first_evidence else .55, {'day': s.day, 'subject': subject})
        self.philosophy.consider(s.world, s.day, str(s.session), eid)
        self.m.db.execute('INSERT OR IGNORE INTO Reflections VALUES(?,?,?,?,?,?,?,?)',
                          (str(uuid4()), s.world, exp['id'], 'FACT', 1.0, json.dumps([eid]),
                           'Consultar conhecimentos e procurar a próxima oportunidade executável', now()))
        self.journal.write(s.world, s.day, 'reflection', eid)
        self._state(s, 'LEARNING', 'Resultado verificado; procurando possibilidades derivadas')

    def _failure(self, s, exp, cmd, reason, status='failed'):
        gid = self._goal_id(exp)
        assessment = assess_failure(status, reason)
        if cmd['action']=='pickup':self.mining.pickup_outcome(s,gid,cmd,cancelled=status=='cancelled',reason=reason)
        if cmd['action'] in FURNACE_ACTIONS:self.cooking.interrupt(s,cmd)
        if cmd['action'].startswith('storage_'):self.storage.interrupt(s,cmd)
        if cmd['action'] in SOCIAL_ACTIONS:self.social.interrupt(s,cmd)
        self.m.db.execute('UPDATE Experiments SET status=? WHERE id=?', (status, exp['id']))
        self.m.db.execute('UPDATE Goals SET status=? WHERE id=?', (status, gid))
        personality = self.motivation.values(s.world)
        self.goals.cooldown = max(30, min(180, 60 + (personality['prudence']-60)*.5 - (personality['persistence']-90)*.2))
        self.goals.failure(gid, reason, status == 'cancelled', uncertain=not assessment.count_attempt)
        cancelled = status == 'cancelled'
        text = ('Interrompi uma ação após a suspensão do controle; isso não contradiz minha hipótese.' if cancelled else
                f"Minha tentativa de {cmd['action']} não terminou com evidência suficiente ({reason}). Vou considerar outra oportunidade antes de tentar novamente.")
        target = json.loads(exp['target'])
        eid = self._event(s, 'attempt_cancelled' if cancelled else 'attempt_failed', text,
                          {'command': cmd['id'], 'goal': gid, 'subject': target.get('id',''),
                           'reason': reason, 'outcome': status, 'failure_category': assessment.category,
                           'physical_outcome': 'inconclusive', 'origin': assessment.origin}, cmd['id'])
        self.mind.record_outcome(s,gid,eid,success=False)
        if not cancelled:
            self.autobiography.record(s.world, eid, 'uncertain_attempts', .55, .5,
                                      {'day': s.day, 'subject': target.get('id',''), 'reason': reason})
            self.philosophy.consider(s.world, s.day, str(s.session), eid)
        self.m.db.execute('INSERT OR IGNORE INTO Reflections VALUES(?,?,?,?,?,?,?,?)',
                          (str(uuid4()), s.world, exp['id'], 'UNCERTAIN', 0.0, json.dumps([eid]),
                           'Aplicar cooldown e reobservar antes de atribuir causa física.', now()))
        self.journal.write(s.world, s.day, 'reflection', eid)

    def _result(self, s, result):
        rows = self.m.rows("SELECT * FROM Commands WHERE id=? AND world=? AND session=? AND status='sent'",
                           (str(result.id), s.world, str(s.session)))
        if not rows: return False
        command = rows[0]
        exp = self.m.rows('SELECT * FROM Experiments WHERE id=?', (command['experiment'],))[0]
        cmd, ev = json.loads(command['payload']), result.evidence
        target, action = json.loads(exp['target']), cmd['action']
        self.m.db.execute('UPDATE Commands SET status=?,result=? WHERE id=?', (result.status, result.model_dump_json(), command['id']))
        self.command_sent.pop(command['id'], None)
        if result.status != 'success':
            self._failure(s, exp, cmd, result.reason, result.status)
            return True
        valid = ev.get('target') == {k: target[k] for k in ('x', 'y', 'z')}
        phase, eid, subject = None, None, target['id']
        plans = self.m.rows('SELECT kind FROM GoalPlans WHERE goal_id=?', (self._goal_id(exp),))
        kind = plans[0]['kind'] if plans else 'log'
        if action == 'approach':
            valid &= ev.get('in_reach') is True
            phase = 'observe' if kind == 'observe' else 'harvest' if kind == 'harvest' else 'sleep' if kind == 'sleep' else 'break'
        elif action == 'break':
            valid &= (ev.get('server_verified') is True and ev.get('before_block') == target['id'] and
                      ev.get('after_block') == 'minecraft:air' and type(ev.get('mined_delta')) is int and ev['mined_delta'] >= 1 and
                      valid_inventory(ev.get('inventory_before')))
            phase = 'collect'
            if valid:
                eid = self._event(s, 'block_removed', f"Consegui quebrar {subject}. O servidor confirmou a remoção; ainda preciso verificar a coleta.", ev, cmd['id'])
                self._knowledge(s, subject, 'partial', eid)
                self.journal.write(s.world, s.day, 'reflection', eid)
        elif action == 'mine':
            valid &= (mining_evidence(cmd['mining'],ev) and valid_inventory(ev.get('inventory_before')) and valid_inventory(ev.get('inventory_after')))
            if valid:
                subject='mining:'+target['id']
                tool=cmd['mining']['tool_id'];method='a mão vazia' if tool=='minecraft:air' else tool
                eid=self._event(s,'resource_mined',f"Removi {target['id']} usando {method}. O servidor confirmou a mineração e a variação de durabilidade de {cmd['mining'].get('tool_wear',1)} unidade(s); os itens no chão ainda precisam de coleta verificada.",ev,cmd['id'])
                self._knowledge(s,subject,'confirmed',eid)
                self._inventory_gains(s,cmd,ev,eid)
                self.mining.intend(s,self._goal_id(exp),cmd,verified=True)
        elif action in SOCIAL_ACTIONS:
            valid &= self.social.validate(s,cmd,ev)
            if valid:
                person=ev['person_uuid'];name=ev['after']['name'];subject='person:'+person
                kind='person_observed' if action=='social_observe' else 'social_contact'
                text=(f'Observei {name}, identificado pelo UUID {person}. O servidor confirmou tipo, presença, posição, alcance e visibilidade.'
                      if action=='social_observe' else
                      f'Confirmei no cliente a interface MCA de contato com {name}, UUID {person}, e o estado de interação no servidor. O conteúdo de conversa e o relacionamento permanecem desconhecidos.')
                eid=self._event(s,kind,text,ev,cmd['id'])
                self.social.accept(s,cmd,ev,eid)
                self._knowledge(s,subject,'confirmed',eid)
        elif action.startswith('storage_'):
            valid &= self.storage.validate(s,cmd,ev)
            if valid:
                subject='storage:'+cmd['storage']['job_id']
                kind={'storage_inspect':'storage_inspected','storage_deposit':'storage_deposited','storage_withdraw':'storage_withdrawn'}[action]
                text={'storage_inspect':'Inspecionei os slots do baú e meu inventário. Esta observação não atribui transferências anteriores sem confirmação.',
                      'storage_deposit':'Guardei uma unidade de recurso no baú. A origem, o destino e a conservação dos demais slots foram confirmados pelo servidor.',
                      'storage_withdraw':'Retirei uma unidade de recurso do baú. A origem, o destino e a conservação dos demais slots foram confirmados pelo servidor.'}[action]
                eid=self._event(s,kind,text,ev,cmd['id'])
                self.storage.accept(s,cmd,ev,eid)
        elif action=='till':
            valid &= self.agriculture.validate_till(s,cmd,ev)
            if valid:
                subject='agriculture:tilling'
                eid=self._event(s,'soil_tilled','Preparei uma célula de solo com enxada. O servidor confirmou o solo arado, a água próxima e o desgaste; hidratação e produção ainda precisam ser observadas.',ev,cmd['id'])
                self._knowledge(s,subject,'confirmed',eid)
        elif action=='plant':
            valid &= self.agriculture.validate(s,cmd,ev)
            if valid:
                subject='planting:'+cmd['planting']['crop_id']
                eid=self._event(s,'planted',f"Plantei {cmd['planting']['crop_id']} em solo agrícola existente. O servidor confirmou uma planta jovem, o uso e o consumo da semente; ainda não observei crescimento ou colheita dessa planta.",ev,cmd['id'])
                self._knowledge(s,subject,'confirmed',eid)
        elif action == 'harvest':
            valid &= (ev.get('server_verified') is True and ev.get('before_block') == target['id']
                      and ev.get('after_block') == 'minecraft:air'
                      and ev.get('before_crop_mature') is True
                      and type(ev.get('mined_delta')) is int and ev['mined_delta'] >= 1)
            if valid:
                eid = self._event(s, 'crop_harvested', f'Retirei o bloco maduro {subject}. A remoção foi confirmada pelo servidor; ainda não confirmei os itens que possam ter caído.', ev, cmd['id'])
                self._knowledge(s, 'harvest:' + subject, 'confirmed', eid)
        elif action == 'sleep':
            before_time, after_time = ev.get('time_before'), ev.get('time')
            valid &= (ev.get('server_verified') is True and ev.get('rest_completed') is True
                      and ev.get('bed_block') == target['id']
                      and type(before_time) is int and type(after_time) is int
                      and 0 < after_time-before_time <= 24000
                      and before_time % 24000 >= 12542 and after_time % 24000 < 12000
                      and type(ev.get('sleep_count_before')) is int and type(ev.get('sleep_count_after')) is int
                      and ev['sleep_count_after'] > ev['sleep_count_before'])
            if valid:
                subject = f"bed:{target['x']}:{target['y']}:{target['z']}"
                eid = self._event(s,'slept','Usei a cama observada; a estatística de repouso e a passagem do horário noturno para o dia foram confirmadas pelo servidor.',ev,cmd['id'])
                self._knowledge(s,subject,'confirmed',eid)
        elif action == 'collect':
            before = cmd.get('baseline', 0)
            inventory = ev.get('inventory_after', {})
            after = inventory.get(subject, 0) if isinstance(inventory, dict) else 0
            valid &= ev.get('server_verified') is True and valid_inventory(inventory) and type(after) is int and after > before
            if valid:
                eid = self._event(s, 'collected', f"Minha investigação de {subject} resultou na coleta verificada de {after-before} unidade(s). Agora posso procurar aplicações desse material e comparar outras oportunidades.",
                                  {'subject': subject, 'break_command': cmd['break_command'], 'collect_command': cmd['id'],
                                   'before_count': before, 'after_count': after, 'server': ev}, cmd['id'])
                self._knowledge(s, subject, 'confirmed', eid)
        elif action == 'observe':
            valid &= ev.get('server_verified') is True and ev.get('after_block') == subject
            if valid:
                eid = self._event(s, 'observed', f"Examinei {subject} de perto e confirmei sua presença. Ainda não testei suas utilidades nem o material que ele fornece.", ev, cmd['id'])
                self._knowledge(s, 'observation:' + subject, 'confirmed', eid)
        elif action == 'explore':
            try:
                xyz = tuple(float(ev['position'][k]) for k in ('x', 'y', 'z'))
                valid &= (all(math.isfinite(v) for v in xyz) and math.dist(xyz, (target['x']+.5, target['y'], target['z']+.5)) < 1.25
                          and region(*xyz) == region(target['x']+.5, target['y'], target['z']+.5)
                          and ev.get('dimension') == s.dimension and ev.get('server_verified') is True)
            except (KeyError, TypeError, ValueError): valid = False
            if valid:
                subject = 'exploration'
                text=(f"Alcancei um trecho do retorno planejado no bioma {s.biome}. Ainda preciso revalidar o caminho até o destino lembrado." if cmd.get('route') else
                      f"Cheguei à região que escolhi investigar. Observei o bioma {s.biome}; vou usar essa visita para orientar meus próximos destinos.")
                eid = self._event(s, 'region_reached',text,ev,cmd['id'])
                self.routes.record(s,cmd,eid)
        elif action in SHELTER_ACTIONS:
            valid &= self.construction.validate(s,cmd,ev)
            if valid:
                project=self.construction.current(s)
                kind={'build_shelter':'construction_step','inspect_shelter':'shelter_inspected',
                      'enter_shelter':'shelter_entered','leave_shelter':'shelter_left'}[action]
                text={'build_shelter':f'Coloquei um componente do abrigo: {target["id"]}. Esta etapa tem prova de uso e consumo; a estrutura completa exige inspeção separada.',
                      'inspect_shelter':'Inspecionei os componentes do projeto; a presença observada não atribui a mim ações que ficaram sem confirmação.',
                      'enter_shelter':'Entrei no pequeno refúgio e fechei a porta. Minha posição e a estrutura foram confirmadas; isso não garante proteção contra todos os perigos.',
                      'leave_shelter':'Saí do refúgio pela porta e a fechei. Posso voltar a considerar as oportunidades observadas.'}[action]
                if action=='leave_shelter' and not ev['complete']:
                    kind='construction_departed'
                    text='Saí do local do projeto incompleto pela passagem disponível. Confirmei minha posição externa; não registrei o lugar como abrigo concluído.'
                eid=self._event(s,kind,text,ev,cmd['id'])
                self.construction.accept(s,cmd,ev,eid)
                subject='shelter:'+project['id']
                if action=='inspect_shelter' and ev['complete'] and not self.m.rows("SELECT 1 FROM Events WHERE world=? AND dedup=?",(s.world,'shelter-complete:'+project['id'])):
                    eid=self._event(s,'shelter_completed','Concluí a verificação do meu primeiro refúgio planejado neste local. Paredes, teto, piso, espaço interno e porta foram conferidos no mundo; ainda preciso observar como ele será usado.',
                                    {**ev,'inspection_event':eid},'shelter-complete:'+project['id'])
                    self._knowledge(s,subject,'confirmed',eid)
        elif action in FURNACE_ACTIONS:
            valid &= self.cooking.validate(s,cmd,ev)
            if valid:
                job=self.cooking.current(s);r=job['recipe'];subject='cooking:'+r['id']
                kind='furnace_inspected' if action=='furnace_inspect' else 'furnace_loaded'
                text='Inspecionei o conteúdo real da fornalha antes de continuar o preparo.' if action=='furnace_inspect' else f"Transferi uma unidade de {r['input_id']} e uma de {r['fuel_id']} para a fornalha; ainda preciso verificar o resultado."
                if action=='furnace_load' and r['fuel_id'] is None:
                    text=f"Transferi uma unidade de {r['input_id']} para a fornalha usando calor restante observado; ainda preciso verificar o resultado."
                if action=='furnace_take':
                    slot=ev['take_slot'];item=ev['before']['slots'][slot]['id']
                    kind='cooked' if slot==2 and job['load_event'] else 'furnace_recovered'
                    text=(f"Preparei e retirei uma unidade de {item}. A carga anterior, o resultado na fornalha e o aumento do inventário têm evidências próprias; ainda não registrei o consumo." if kind=='cooked' else
                          f"Retirei uma unidade observada de {item} da fornalha e confirmei o aumento do inventário. Esta recuperação não atribui a mim um preparo que ficou sem confirmação.")
                    ev={**ev,'load_event':job['load_event']}
                eid=self._event(s,kind,text,ev,cmd['id'])
                self.cooking.accept(s,cmd,ev,eid)
                if kind=='cooked':self._knowledge(s,subject,'confirmed',eid)
        elif action in ('craft','craft_table'):
            recipe = cmd['recipe']
            a, b = ev.get('inventory_before', {}), ev.get('inventory_after', {})
            valid &= (valid_inventory(a) and valid_inventory(b) and craft_evidence(recipe,ev)
                      and (action=='craft_table') == (recipe.get('grid',2)==3))
            if valid:
                subject = 'recipe:' + recipe['id']
                consumed=', '.join(f'{v} {k}' for k,v in sorted(ingredients(recipe).items()))
                eid = self._event(s, 'crafted', f"Testei a receita {recipe['id']}: consumi {consumed} e obtive {recipe['output_count']} {recipe['output_id']}. As mudanças de inventário e a fabricação foram verificadas no servidor.", ev, cmd['id'])
                self._knowledge(s, subject, 'confirmed', eid)
                for item in ingredients(recipe): self.goals.supersede(s.world, 'application:' + item)
        elif action == 'place':
            placement=cmd['placement'];item=placement['item_id']
            a,b=ev.get('inventory_before'),ev.get('inventory_after')
            valid &= (valid_inventory(a) and valid_inventory(b) and ev.get('server_verified') is True
                      and item==target['id'] and ev.get('before_block')=='minecraft:air'
                      and ev.get('after_block')==item and ev.get('support')==placement['support']
                      and type(ev.get('used_delta')) is int and ev['used_delta']==1
                      and a.get(item,0)-b.get(item,0)==1)
            if valid:
                subject=f"placement:{s.dimension}:{item}:{target['x']}:{target['y']}:{target['z']}"
                eid=self._event(s,'placed',f'Coloquei {item} em um espaço livre. O servidor confirmou o bloco, o consumo de uma unidade e a estatística de uso. Isso registra uma estação colocada, sem afirmar que construí um abrigo.',ev,cmd['id'])
                self._knowledge(s,subject,'confirmed',eid)
        elif action == 'eat':
            food = cmd['food']
            before, after = ev.get('inventory_before', {}), ev.get('inventory_after', {})
            food_before, food_after = ev.get('food_before'), ev.get('food_after')
            valid &= (ev.get('server_verified') is True and valid_inventory(before) and valid_inventory(after)
                      and food.get('id') == target['id'] and type(food_before) is int and type(food_after) is int
                      and food_after > food_before and before.get(target['id'], 0) - after.get(target['id'], 0) == 1)
            if valid:
                subject = 'food:' + target['id']
                eid = self._event(s, 'ate', f'Comi uma unidade de {target["id"]}; o servidor confirmou aumento da fome de {food_before} para {food_after} e redução do inventário.', ev, cmd['id'])
                self._knowledge(s, subject, 'confirmed', eid)
        elif action == 'pickup':
            item = cmd['item']; before, after = ev.get('inventory_before', {}), ev.get('inventory_after', {})
            item_id = item['item_id']; old_count = before.get(item_id, 0) if isinstance(before, dict) else -1
            new_count = after.get(item_id, 0) if isinstance(after, dict) else -1
            present_after = ev.get('entity_present_after')
            count_before, count_after = ev.get('entity_count_before'), ev.get('entity_count_after')
            entity_changed = (ev.get('entity_present_before') is True and
                              ((present_after is False) or (type(count_before) is int and type(count_after) is int and count_after < count_before)))
            valid &= (ev.get('server_verified') is True and valid_inventory(before) and valid_inventory(after)
                      and ev.get('item_id') == item_id and ev.get('entity_id') == item['entity_id']
                      and ev.get('entity_changed') is not True
                      and type(old_count) is int and type(new_count) is int and new_count > old_count and entity_changed
                      and type(count_before) is int and type(count_after) is int and 0<=count_after<count_before
                      and new_count-old_count<=count_before-count_after)
            if valid:
                subject = item_id
                eid = self._event(s, 'collected', f'Recolhi {new_count-old_count} unidade(s) de {item_id}; o inventário e a redução ou remoção da entidade de item foram confirmados pelo servidor.', ev, cmd['id'])
                self._knowledge(s, subject, 'confirmed', eid)
                self.mining.pickup_outcome(s,self._goal_id(exp),cmd,success=True)
        else: valid = False
        if not valid:
            self.m.db.execute("UPDATE Commands SET status='unverified' WHERE id=?", (cmd['id'],))
            self._failure(s, exp, cmd, 'evidence_mismatch', 'unverified')
        elif phase:
            self.m.db.execute('UPDATE Experiments SET phase=? WHERE id=?', (phase, exp['id']))
        elif eid:
            self._complete(s, exp, eid, subject)
        return True

    def step(self, s):
        sid, tick = str(s.session), self.clock()
        previous = self.sessions.get(sid)
        if previous and (previous['world'] != s.world or previous['dimension'] != s.dimension or s.seq <= previous['seq']):
            raise ValueError('Sessão, dimensão ou sequência inválida')
        if self.latest and sid != str(self.latest.session) and tick-self.last_seen < 3:
            raise ValueError('Outro cliente está conectado')
        if previous is None:
            prior_worlds=self.m.rows('SELECT DISTINCT world FROM Observations WHERE session=? LIMIT 2',(sid,))
            if any(row['world']!=s.world for row in prior_worlds):
                raise ValueError('Sessão já vinculada a outro mundo persistido')
            self.m.db.execute("UPDATE SocialAttempts SET status='uncertain' WHERE world=? AND session<>? AND status='intent'",(s.world,sid))
            self.m.db.execute("UPDATE SocialPeople SET last_session=NULL WHERE world=? AND EXISTS (SELECT 1 FROM SocialAttempts a "
                              "WHERE a.world=SocialPeople.world AND a.person_uuid=SocialPeople.person_uuid AND a.status='uncertain' AND a.session<>?)",(s.world,sid))
            self.m.db.execute("UPDATE Experiments SET status='interrupted' WHERE world=? AND status='running'", (s.world,))
            self.m.db.execute("UPDATE Goals SET status='suspended' WHERE world=? AND status='running'", (s.world,))
            self.m.db.execute("UPDATE Commands SET status='interrupted' WHERE world=? AND status='sent'", (s.world,))
            self.control = None
            if len(self.sessions) > 64: self.sessions.clear()
        self.sessions[sid] = dict(seq=s.seq, world=s.world, dimension=s.dimension)
        self.latest, self.last_seen = s, tick
        self.m.db.execute('INSERT OR IGNORE INTO Worlds VALUES(?,?)', (s.world, now()))
        if s.world not in self.initialized:
            self.motivation.initialize(s.world, sid, s.day)
            self.autobiography.backfill(s.world,128)
            self.initialized.add(s.world)
        if s.seq % 4 == 1 or s.results:
            self.m.db.execute('INSERT OR IGNORE INTO Observations VALUES(?,?,?,?,?,?,?)',
                              (str(uuid4()), s.world, sid, s.day, now(), s.seq, s.model_dump_json()))
            self.m.db.execute('DELETE FROM Observations WHERE world=? AND rowid NOT IN '
                              '(SELECT rowid FROM Observations WHERE world=? ORDER BY rowid DESC LIMIT 10000)', (s.world, s.world))
        changed = False
        for result in s.results: changed = self._result(s, result) or changed
        self.journal.finalize_before(s.world, s.day)
        response = dict(protocol=1, session=sid, seq=s.seq, control_epoch=s.control_epoch,
                        ack=[str(r.id) for r in s.results], control=self.control, command=None,interrupt=None)
        self.control = None
        health_limit, food_limit = self.motivation.safety_limits(s.world)
        unsafe = s.player.health <= health_limit or s.player.danger
        if unsafe:
            response['control'] = 'pause'
            self.dominant = 'SURVIVAL'
            self._state(s, 'WAITING_FOR_SAFE_ACTION', 'Perigo, pouca vida ou fome; controle físico suspenso')
        elif s.control_state == 'EMERGENCY_STOP' or response['control'] == 'stop':
            self._state(s, 'EMERGENCY_STOP', 'Parada explícita; F8 necessário')
        elif not s.active or not s.armed or response['control'] == 'pause':
            self._state(s, 'PAUSED', 'Controle pausado ou sem autorização local')
        else:
            pending=self.m.rows("SELECT id,payload FROM Commands WHERE world=? AND session=? AND status='sent' ORDER BY created DESC LIMIT 1",(s.world,sid))
            edible=any(self._safe_food(f.model_dump(),s.player.inventory) for f in s.player.foods)
            interruptible={'storage_inspect','storage_deposit','storage_withdraw','build_shelter','mine','pickup','explore','till','furnace_inspect','furnace_load','furnace_take',*SOCIAL_ACTIONS}
            if pending and s.player.food<=food_limit and edible and 'eat' in s.capabilities and json.loads(pending[0]['payload'])['action'] in interruptible:
                # Await the client's cancellation result before planning a meal.
                # The click may already have reached the server; its intention stays intact.
                response['interrupt']=pending[0]['id']
                self._state(s,'SURVIVAL','Interromper trabalho atual para usar alimento disponível; preservar o progresso.')
            else:
                response['command'] = self.decide(s, changed or previous is None)
                if self.control in ('pause','stop'):
                    response['control'] = self.control
        if not s.active or not s.armed or unsafe or response['control'] in ('stop', 'pause'):
            self.projects.suspend(s,'Controle pausado ou condicao fisiologica insegura; preservar progresso.')
            self.m.db.execute("UPDATE Goals SET status='suspended' WHERE world=? AND status='running'", (s.world,))
        response.update(state=self.state, reason=self.reason)
        self.m.db.commit()
        return response

    def _derive(self, s, known):
        for item, row in known.items():
            if not (item.endswith('_log') or item.startswith('recipe:')): continue
            ids = json.loads(row['evidence_ids'])
            if ids: self.interests.update(s, self.interests.topic(item), ids[-1])
            subject = 'application:' + item
            self.goals.question(s, subject, f'Que aplicações de {item} consigo testar com minhas habilidades atuais?', ids[-1] if ids else None)
            if item.startswith('recipe:') and 'craft_table' not in s.capabilities:
                self.goals.ensure(s, subject, 'Investigar ferramentas usando uma bancada', 'Usar uma bancada e receitas 3×3 requer um controlador ainda não implementado; fabricar o item bancada na grade 2×2 já é possível.',
                                  40, 'future', {}, 'craft_table', 'MEDIUM_TERM', blocked=True)
            elif not item.startswith('recipe:') and not any(item in ingredients(r.model_dump()) for r in s.recipes):
                self.goals.ensure(s, subject, 'Investigar crafting com ' + item,
                                  'Aguardando uma receita 2×2 desbloqueada e anunciada pelo mod.', 50, 'future', {}, 'craft_planks', 'MEDIUM_TERM', blocked=True)

    def decide(self, s, force=False):
        pending = self.m.rows("SELECT * FROM Commands WHERE session=? AND status='sent' ORDER BY created DESC", (str(s.session),))
        if pending:
            c = pending[0]
            if self.clock()-self.command_sent.get(c['id'], self.clock()) > 25:
                exp = self.m.rows('SELECT * FROM Experiments WHERE id=?', (c['experiment'],))[0]
                self.m.db.execute("UPDATE Commands SET status='timeout' WHERE id=?", (c['id'],))
                self._failure(s, exp, json.loads(c['payload']), 'backend_command_timeout')
                self._state(s, 'WAITING_FOR_SAFE_ACTION', 'Comando sem confirmação; solicitando pausa')
                self.control = 'pause'
                return None
            return json.loads(c['payload'])
        experiments = self.m.rows("SELECT * FROM Experiments WHERE world=? AND session=? AND status='running'", (s.world, str(s.session)))
        if experiments:
            exp = experiments[0]
            if exp['phase'] == 'collect':
                prior = self.m.rows("SELECT * FROM Commands WHERE experiment=? AND status='success' ORDER BY created DESC", (exp['id'],))
                broken = next(c for c in prior if json.loads(c['payload'])['action'] == 'break')
                target = json.loads(exp['target'])
                return self._command(s, exp, 'collect', baseline=json.loads(broken['result'])['evidence']['inventory_before'].get(target['id'], 0), break_command=broken['id'])
            return self._command(s, exp, exp['phase'])
        tick = self.clock()
        if not force and tick-self.last_plan.get(s.world, -1e30) < self.interval: return None
        self.last_plan[s.world] = tick
        self.planning_cycles += 1
        if self.planning_cycles%16==1:self.autobiography.backfill(s.world,128)
        self.goals.begin_cycle(s.world)
        self._state(s, 'PLANNING', 'Consultando memória, necessidades e oportunidades')
        self.exploration.record(s)
        known = {r['subject']: r for r in self.m.rows("SELECT * FROM Knowledge WHERE world=? AND status='confirmed'", (s.world,))}
        need_wood=self.crafting.needs_wood(s)
        candidates = [b for b in s.blocks if not b.bed and (b.harvestable or b.log and need_wood or (b.id if b.log else 'observation:'+b.id) not in known)]
        frontiers = self.exploration.candidates(s)
        exploration_history = self.exploration.yield_history(s)
        frontier_scores = [(length,key,target,self.exploration.score(s,length,target,exploration_history))
                           for length,key,target in frontiers]
        exploration_score = max((score for _,_,_,score in frontier_scores), key=lambda score:score['score'], default=None)
        self.dominant, personality = self.motivation.evaluate(s, bool(candidates), len(frontiers), exploration_score)
        self._derive(s, known)
        offered=set()
        # Food, its observed sources and executable preparation are considered before curiosity.
        if s.player.food <= self.motivation.safety_limits(s.world)[1]:
            self.projects.suspend(s,'Prioridade alimentar observada; retomar o projeto depois de recuperar as reservas.')
            foods = [f.model_dump() for f in s.player.foods if self._safe_food(f.model_dump(), s.player.inventory)]
            if 'eat' in s.capabilities:
                for food in sorted(foods,key=lambda f:(f['nutrition'],f['count'],f['id']),reverse=True):
                    command=self._start_eat(s,food)
                    if command:return command
            if s.time<12000 and 'eat' in s.capabilities:
                stored_food=self.storage.propose(s,food_only=True)
                if stored_food:
                    stored_food['category']='IMMEDIATE'
                    command=self._offer_project(s,stored_food)
                    if command:return command
            project=self.construction.current(s)
            if project:
                proposal=self.construction.propose(s,night=s.time>=12000)
                if proposal and proposal['kind']!='build_shelter':
                    command=self._offer_project(s,proposal)
                    if command:return command
            food_item = self.foods.choose(s.items, s.player, s.player.inventory,
                                          self.motivation.safety_limits(s.world)[1])
            if food_item is not None and 'pickup' in s.capabilities:
                pickup_command=self._start_pickup(s, food_item, 1200 + (20-s.player.food)*10,
                                          'Alimento com componente Food observado no mundo; estoque atual insuficiente.',
                                          'IMMEDIATE')
                if pickup_command: return pickup_command
            if s.time<12000:
                proposal=self.cooking.propose(s)
                if proposal:
                    command=self._offer_project(s,proposal)
                    if command:return command
            if s.player.inventory.get('minecraft:wheat',0)>=3 and s.time<12000:
                offered=self._work_goals(s,personality)
                for goal in self.goals.rows(s.world):
                    params=json.loads(goal['params'])
                    if goal['id'] in offered and goal['status']=='pending' and (goal['kind']=='place' or
                            params.get('recipe',{}).get('output_id') in ('minecraft:bread','minecraft:crafting_table') or
                            params.get('recipe',{}).get('output_id','').endswith('_planks')):
                        return self._start_planned(s,goal)
            if 'pickup' in s.capabilities and s.time<12000:
                wheat=self.foods.choose_resource([i for i in s.items if i.item_id=='minecraft:wheat'],s.player,s.player.inventory)
                if wheat is not None:
                    command=self._start_pickup(s,wheat,1100,'Reunir trigo observado para uma receita de alimento.','IMMEDIATE')
                    if command:return command
            if s.time < 12000 and self.skills.available('harvest_crop',s.capabilities):
                ripe = sorted((b for b in s.blocks if b.harvestable),
                              key=lambda b: (b.id=='minecraft:wheat',math.dist((s.player.x,s.player.y,s.player.z),(b.x,b.y,b.z))))
                for crop in ripe:
                    if math.dist((s.player.x,s.player.y,s.player.z),(crop.x,crop.y,crop.z)) > 14: continue
                    target = crop.model_dump(exclude={'log','harvestable','lit'})
                    if self.m.rows("SELECT 1 FROM Experiments WHERE world=? AND target=? AND status IN ('failed','unverified')",
                                   (s.world,json.dumps(target,sort_keys=True))): continue
                    command=self._start_harvest(s,crop,1500+(20-s.player.food)*10,
                                               'Fome baixa, sem alimento seguro no inventário ou no chão; cultivo maduro visível durante o dia.',
                                               'IMMEDIATE')
                    if command:return command
            self._state(s, 'WAITING_FOR_SAFE_ACTION', 'Fome baixa; sem alimento seguro executável no inventário')
            return None
        if s.time >= 12000:
            beds=sorted((b for b in s.blocks if b.bed),
                        key=lambda b: math.dist((s.player.x,s.player.y,s.player.z),(b.x,b.y,b.z)))
            if s.time>=12542 and s.dimension=='minecraft:overworld' and self.skills.available('sleep_in_bed',s.capabilities):
                for bed in beds:
                    if math.dist((s.player.x,s.player.y,s.player.z),(bed.x,bed.y,bed.z))<=14:
                        command=self._start_sleep(s,bed,1200+self.motivation.values(s.world)['prudence'],
                                                 'Noite observada; cama vanilla visível no Overworld e ameaça imediata ausente.',
                                                 'IMMEDIATE')
                        if command:return command
            proposal=self.night.propose(s)
            if proposal:
                command=self._offer_project(s,proposal)
                if command:return command
            shelter=self.construction.current(s)
            if shelter and shelter['status']=='ready':
                route=self.routes.request(s,shelter['anchor'],'shelter:'+shelter['id'],'Retornar em trechos ao refúgio conhecido')
                if route:
                    command=self._offer_project(s,route)
                    if command:return command
            reason=self.night.reason if self.construction.current(s) else ('Crepúsculo: aguardando a janela de sono do jogo.' if s.time<12542 else 'Noite: nenhuma cama ou abrigo próximo confirmado; aguardando uma ação segura.')
            if s.dimension!='minecraft:overworld': reason='Repouso em cama não disponível nesta dimensão; aguardando condição segura.'
            self._state(s, 'WAITING_FOR_SAFE_ACTION', reason)
            return None
        drop=self.mining.pending_drop(s)
        if drop is not None and 'pickup' in s.capabilities:
            command=self._start_pickup(s,drop,250,'Recolher recurso necessário já observado antes de minerar outro bloco.','SHORT_TERM')
            if command:return command
        acquisition_pending=self.mining.acquisition_pending(s) or drop is not None
        if acquisition_pending:
            # Retry cooldown preserves the acquisition instead of sending the player away.
            self._state(s,'WAITING_FOR_SAFE_ACTION','Aguardar recurso observado ou nova tentativa limitada de coleta antes de explorar.')
            return None
        farm_drop=self.agriculture.pending_drop(s)
        if farm_drop is not None:
            command=self._start_pickup(s,farm_drop,255,'Recolher sementes ou produtos observados perto de um cultivo colhido; a origem do item ainda não foi atribuída.','SHORT_TERM')
            if command:return command
        if 'pickup' in s.capabilities:
            reserve=sum(v for k,v in s.player.inventory.items() if any(f.id==k for f in s.player.foods) and self.foods.safe_id(k))
            item=self.foods.choose(s.items,s.player,s.player.inventory,20) if reserve<3 else None
            if item is None:
                item=self.foods.choose_resource([i for i in s.items if i.item_id=='minecraft:wheat'],s.player,s.player.inventory)
            if item is not None:
                command=self._start_pickup(s,item,200,'Formar reserva pequena com alimento ou trigo observado.','SHORT_TERM')
                if command:return command
        self.construction.prepare(s)
        self.projects.sync(s)
        storage=self.storage.propose(s)
        if storage:
            command=self._offer_project(s,storage)
            if command:return command
        storage_job=self.storage.current(s)
        storage_reserves=self.storage.reservations(s) if storage_job else {}
        storage_needed=(storage_job and (storage_job['status'] in ('intent','uncertain')
                        or any(n>s.player.inventory.get(item,0) for item,n in self.storage.demands(s).items())
                        or any(n>storage_reserves.get(item,0) for item,n in s.player.inventory.items()
                               if item in STORAGE_MATERIALS)))
        if storage_needed:
            route=self.routes.request(s,storage_job['station'],'storage:'+storage_job['id'],'Retornar ao baú para revalidar materiais armazenados')
            if route:
                command=self._offer_project(s,route)
                if command:return command
        need_wood=self.crafting.needs_wood(s)
        candidates = [b for b in s.blocks if not b.bed and (b.harvestable or b.log and need_wood or (b.id if b.log else 'observation:'+b.id) not in known)]
        native_project=self.construction.current(s)
        proposal=(self.construction.propose(s) if not native_project or self.projects.allows(s,'shelter',native_project['id']) else None)
        if proposal:
            command=self._offer_project(s,proposal)
            if command:return command
        native_job=self.cooking.current(s)
        cooking=(self.cooking.propose(s) if not native_job or self.projects.allows(s,'furnace',native_job['id']) else None)
        if cooking:
            command=self._offer_project(s,cooking)
            if command:return command
        job=self.cooking.current(s)
        if job:
            route=self.routes.request(s,job['station'],'furnace:'+job['id'],'Retornar à fornalha para revalidar o preparo pendente')
            if route:
                command=self._offer_project(s,route)
                if command:return command
        offered=self._work_goals(s,personality)
        for b in sorted(candidates, key=lambda b: math.dist((s.player.x, s.player.y, s.player.z), (b.x, b.y, b.z))):
            if math.dist((s.player.x, s.player.y, s.player.z), (b.x, b.y, b.z)) > 14: continue
            if b.harvestable:
                if not self.skills.available('harvest_crop', s.capabilities): continue
                target = b.model_dump(exclude={'log', 'harvestable','lit'})
                if self.m.rows("SELECT 1 FROM Experiments WHERE world=? AND target=? AND status IN ('failed','unverified')", (s.world, json.dumps(target, sort_keys=True))): continue
                subject = self.agriculture.crop_subject(s,b)
                question = f'Consigo colher o cultivo maduro {b.id} neste local?'
                gid = self.goals.ensure(s, subject, question, 'Estágio maduro observado em cultivo conhecido; remoção física será confirmada pelo servidor.',
                                        88 + personality['curiosity']*.04, 'harvest', {'target': target}, 'harvest_crop', 'SHORT_TERM')
                if gid:
                    self.goals.question(s, subject, question)
                    offered.add(gid)
                continue
            subject = f'resource:{b.id}:{b.x}:{b.y}:{b.z}' if b.log and b.id in known and need_wood else ('log:' if b.log else 'observe:') + b.id
            skill = 'investigate_log' if b.log else 'observe_block'
            if not self.skills.available(skill, s.capabilities): continue
            target = b.model_dump(exclude={'log','harvestable','bed','lit'})
            if self.m.rows("SELECT 1 FROM Experiments WHERE world=? AND target=? AND status IN ('failed','unverified')", (s.world, json.dumps(target, sort_keys=True))): continue
            question = f'O que consigo obter de {b.id}?' if b.log else f'Consigo confirmar de perto a presença de {b.id}?'
            gid = self.goals.ensure(s, subject, question, 'Novidade observada e habilidade disponível; segurança será revalidada ao caminhar.',
                                    personality['curiosity'] + self.interests.score(s.world, self.interests.topic(b.id))*.1 - (0 if b.log else 15) + (personality['learning']-95)*.1,
                                    'log' if b.log else 'observe', {'target': target}, skill)
            if gid:
                self.goals.question(s, subject, question)
                offered.add(gid)
        for length, key, target, score in frontier_scores:
            if acquisition_pending:break
            if not self.skills.available('explore_region', s.capabilities): break
            # Eligibility is physical/deterministic; narrative bonuses only rank
            # goals that have already met the activity threshold.
            if not score['eligible']:continue
            subject = f'explore:{s.dimension}:{key}'
            gid = self.goals.ensure(s, subject, 'Explorar uma região ainda não visitada',
                                    'Fronteira local; caminho será revalidado. '+json.dumps(score,sort_keys=True),
                                    score['score'], 'explore', {'target': target}, 'explore_region')
            if gid:
                self.goals.question(s, subject, 'Que recursos e bioma vou observar na próxima região acessível?')
                offered.add(gid)
        goals = self.goals.rows(s.world)
        ranked = []
        for goal in goals:
            params = json.loads(goal['params'])
            components = dict(priority=goal['priority'],
                              prior_cognitive=self.language.bonus(s.world,goal['kind'],params,goal['subject']),
                              learned_preferences=self.identity.bonus(s.world,goal['kind'],params),
                              project=self.projects.bonus(s,goal['kind'],params),
                              mind=self.mind.bonus(s,goal['kind'],params,goal['subject']))
            base = sum(value for key,value in components.items() if key != 'mind')
            ranked.append((goal,base,components['mind'],components))
        eligible = [entry for entry in ranked if entry[0]['id'] in offered and entry[0]['status']=='pending'
                    and entry[0]['cooldown']<=time.time() and self.skills.available(entry[0]['skill'],s.capabilities)]
        eligible_ids = {entry[0]['id'] for entry in eligible}
        baseline = max(eligible,key=lambda entry:entry[1])[0]['id'] if eligible else None
        ranked.sort(key=lambda entry:entry[1]+entry[2],reverse=True)
        for goal,_,mind_bonus,_ in ranked:
            if goal['id'] not in offered or goal['status'] != 'pending' or goal['cooldown'] > time.time(): continue
            if not self.skills.available(goal['skill'], s.capabilities):
                self.m.db.execute("UPDATE Goals SET status='blocked',reason='Habilidade não anunciada pelo mod' WHERE id=?", (goal['id'],))
                continue
            influenced=bool(mind_bonus and goal['id']!=baseline)
            alternatives=[dict(goal=other['id'],kind=other['kind'],subject=other['subject'],
                               components=parts,total=base_score+mind_score)
                          for other,base_score,mind_score,parts in ranked
                          if other['id'] in eligible_ids][:8]
            return self._start_planned(s,goal,mind_influenced=influenced,
                                       comparison=dict(baseline=baseline,alternatives=alternatives))
        if 'pickup' in s.capabilities:
            resource = self.foods.choose_resource(s.items, s.player, s.player.inventory)
            if resource is not None:
                pickup_command = self._start_pickup(s, resource, 68 + personality['curiosity']*.08,
                                                    'Recurso útil observado no chão e em quantidade baixa no inventário.',
                                                    'SHORT_TERM')
                if pickup_command is not None:
                    return pickup_command
        reason = f'Nenhuma novidade executável ou fronteira não visitada com rota segura. Reavaliando a cada {self.interval} s.'
        if exploration_score and not exploration_score['eligible']:
            reason = 'Baixa atividade: rendimento esperado de exploração abaixo do limiar; reavaliar oportunidades e recuperação temporal. '+json.dumps(exploration_score,sort_keys=True)
        if self.construction.current(s):reason+=' Projeto: '+self.construction.reason
        if 'explore' not in s.capabilities: reason += ' Instale o mod 0.2 para anunciar exploração e crafting.'
        self._state(s, 'WAITING_FOR_SAFE_ACTION', reason)
        return None

    def _offer_project(self,s,proposal):
        if not self.skills.available(proposal['skill'],s.capabilities):return None
        gid=self.goals.ensure(s,**proposal)
        goal=next((g for g in self.goals.rows(s.world) if g['id']==gid and g['status']=='pending'),None)
        if goal:return self._start_planned(s,goal)
        return None

    def _work_goals(self,s,personality):
        offered=set()
        for proposal in sorted(self.crafting.proposals(s,personality)+self.mining.proposals(s,personality)+self.agriculture.proposals(s,personality)+self.social.propose(s,personality),
                               key=lambda p:p['priority']+self.projects.bonus(s,p['kind'],p['params']),reverse=True):
            gid=self.goals.ensure(s,**proposal)
            if gid:
                self.goals.question(s,proposal['subject'],proposal['description']+' com verificação do resultado?')
                offered.add(gid)
        return offered

    def _record_goal_selection(self,s,goal,command,*,mind_influenced=False,comparison=None):
        observation=self.m.rows('SELECT id FROM Observations WHERE session=? AND seq=?',(str(s.session),s.seq))
        if not observation:
            self.m.db.execute('INSERT OR IGNORE INTO Observations VALUES(?,?,?,?,?,?,?)',
                              (str(uuid4()),s.world,str(s.session),s.day,now(),s.seq,s.model_dump_json()))
            observation=self.m.rows('SELECT id FROM Observations WHERE session=? AND seq=?',(str(s.session),s.seq))
        evidence=dict(goal=goal['id'],command=command['id'],observation_id=observation[0]['id'],observation_seq=s.seq,
                      reason=goal['reason'],mind_influenced=mind_influenced,
                      mode='ranked' if comparison is not None else 'direct',
                      baseline=comparison['baseline'] if comparison else None,
                      alternatives=comparison['alternatives'] if comparison else [])
        self._event(s,'goal_selected','Meta selecionada entre oportunidades observadas.',
                    evidence,'goal-selection:'+command['id'])

    def _start_planned(self,s,goal,*,mind_influenced=False,comparison=None):
        params=json.loads(goal['params'])
        self.projects.link(s,goal['id'],goal['kind'],params)
        hypothesis=str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis,s.world,goal['description'],'O experimento pode produzir evidência para este objetivo.'))
        hypothesis=self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',(s.world,goal['description']))[0]['id']
        phase=goal['kind'] if goal['kind'] in ('craft','craft_table','place','explore','mine','plant','till','storage_inspect','storage_deposit','storage_withdraw',*SHELTER_ACTIONS,*FURNACE_ACTIONS,*SOCIAL_ACTIONS) else 'approach'
        exp=dict(id=str(uuid4()),world=s.world,session=str(s.session),hypothesis=hypothesis,
                 target=json.dumps(params['target'],sort_keys=True),phase=phase,status='running',evidence_ids='[]')
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)',exp)
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)',(exp['id'],goal['id']))
        self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?",(goal['id'],))
        extra={k:params[k] for k in ('recipe','placement','shelter','mining','furnace','route','planting','tilling','storage','social') if k in params}
        command=self._command(s,exp,phase,**extra)
        if phase=='mine':self.mining.intend(s,goal['id'],command)
        self.mind.record_selection(s,goal,applied=mind_influenced)
        self._record_goal_selection(s,goal,command,mind_influenced=mind_influenced,comparison=comparison)
        return command

    def _start_eat(self,s,food):
        prefix=f'meal:{s.day}:{food["id"]}:'
        completed=self.m.rows("SELECT count(*) n FROM GoalPlans p JOIN Goals g ON g.id=p.goal_id "
                              "WHERE p.world=? AND p.subject LIKE ? AND g.status='completed'",(s.world,prefix+'%'))[0]['n']
        target=dict(x=math.floor(s.player.x),y=math.floor(s.player.y),z=math.floor(s.player.z),id=food['id'])
        gid=self.goals.ensure(s,prefix+str(completed),'Comer alimento para recuperar minhas reservas',
                              'Fome baixa observada e alimento seguro no inventário.',1000+(20-s.player.food)*10,
                              'survival',{'target':target,'food':food},'eat_food','IMMEDIATE')
        goal=next((g for g in self.goals.rows(s.world) if g['id']==gid and g['status']=='pending'),None)
        if not goal:return None
        hypothesis=str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis,s.world,goal['description'],'Consumir o alimento deve elevar a fome e reduzir sua quantidade no inventário.'))
        hypothesis=self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',(s.world,goal['description']))[0]['id']
        exp=dict(id=str(uuid4()),world=s.world,session=str(s.session),hypothesis=hypothesis,
                 target=json.dumps(target,sort_keys=True),phase='eat',status='running',evidence_ids='[]')
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)',exp)
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)',(exp['id'],gid))
        self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?",(gid,))
        command=self._command(s,exp,'eat',food=food)
        self._record_goal_selection(s,goal,command)
        return command

    def _start_pickup(self, s, item, priority, reason, category):
        data = item.model_dump(mode='json')
        target = dict(x=math.floor(item.x), y=math.floor(item.y), z=math.floor(item.z), id=item.item_id)
        subject = 'pickup:' + s.dimension + ':' + data['entity_id']
        params={'target': target, 'item': data}
        acquisition=next((gid for gid,_,intent in self.mining.intents(s) if intent['item_id']==item.item_id),None)
        if acquisition:params['acquisition_goal']=acquisition
        gid = self.goals.ensure(s, subject, 'Recolher ' + item.item_id,
                                reason, priority, 'pickup', params,
                                'pickup_item', category)
        if not gid:
            return None
        goal = next((g for g in self.goals.rows(s.world) if g['id'] == gid and g['status'] == 'pending'), None)
        if not goal:
            return None
        hypothesis = str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis, s.world, goal['description'],
                           'A aproximação pode mover o item para meu inventário; a entidade e a contagem serão verificadas.'))
        hypothesis = self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',
                                 (s.world, goal['description']))[0]['id']
        exp = dict(id=str(uuid4()), world=s.world, session=str(s.session), hypothesis=hypothesis,
                   target=json.dumps(target, sort_keys=True), phase='pickup', status='running', evidence_ids='[]')
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)', exp)
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)', (exp['id'], gid))
        self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?", (gid,))
        command=self._command(s, exp, 'pickup', item=data)
        self._record_goal_selection(s,goal,command)
        return command

    def _start_harvest(self, s, crop, priority, reason, category):
        target=crop.model_dump(exclude={'log','harvestable','lit'})
        subject=self.agriculture.crop_subject(s,crop)
        question=f'Consigo colher o cultivo maduro {crop.id} neste local?'
        gid=self.goals.ensure(s,subject,question,reason,priority,'harvest',{'target':target},'harvest_crop',category)
        if not gid: return None
        goal=next((g for g in self.goals.rows(s.world) if g['id']==gid and g['status']=='pending'),None)
        if not goal: return None
        hypothesis=str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis,s.world,question,'A remoção do cultivo maduro pode produzir recursos; o bloco será verificado pelo servidor.'))
        hypothesis=self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',(s.world,question))[0]['id']
        exp=dict(id=str(uuid4()),world=s.world,session=str(s.session),hypothesis=hypothesis,
                 target=json.dumps(target,sort_keys=True),phase='approach',status='running',evidence_ids='[]')
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)',exp)
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)',(exp['id'],gid))
        self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?",(gid,))
        command=self._command(s,exp,'approach')
        self._record_goal_selection(s,goal,command)
        return command

    def _start_sleep(self,s,bed,priority,reason,category):
        target=bed.model_dump(exclude={'log','harvestable','bed','lit'})
        subject=f"rest:{s.day}:{bed.x}:{bed.y}:{bed.z}"
        description='Repousar na cama observada para atravessar a noite com segurança'
        gid=self.goals.ensure(s,subject,description,reason,priority,'sleep',{'target':target},'sleep_in_bed',category)
        if not gid: return None
        goal=next((g for g in self.goals.rows(s.world) if g['id']==gid and g['status']=='pending'),None)
        if not goal: return None
        hypothesis=str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis,s.world,description,'Usar uma cama válida durante a noite pode avançar o horário; o servidor deve confirmar a passagem e a estatística de repouso.'))
        hypothesis=self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',(s.world,description))[0]['id']
        exp=dict(id=str(uuid4()),world=s.world,session=str(s.session),hypothesis=hypothesis,
                 target=json.dumps(target,sort_keys=True),phase='approach',status='running',evidence_ids='[]')
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)',exp)
        self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)',(exp['id'],gid))
        self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?",(gid,))
        command=self._command(s,exp,'approach')
        self._record_goal_selection(s,goal,command)
        return command

    def _safe_food(self, food, inventory):
        if not isinstance(food, dict) or food.get('id') not in inventory:
            return False
        if not all(type(food.get(k)) is int for k in ('slot', 'count', 'nutrition')):
            return False
        if not (0 <= food['slot'] <= 35 and 1 <= food['count'] <= 64 and 1 <= food['nutrition'] <= 20):
            return False
        return self.foods.safe_id(food['id'])

    def snapshot(self):
        s = self.latest
        world = s.world if s else None
        connected = bool(s and self.clock()-self.last_seen < 3)
        tables = {}
        for table in ('Knowledge','Hypotheses','Experiments','Goals','JournalEntries','PublicationQueue','Questions',
                      'Interests','Motivations','SpatialRegions','Reflections','SkillProgress','PersonalityChanges',
                      'LifeMemories','PhilosophicalQuestions','PhilosophicalRevisions','CognitiveSuggestions','ConstructionProjects','FurnaceJobs','StorageJobs',
                      'CognitivePlans','NarrativeDrafts','Preferences','PreferenceUpdates','ReturnRoutes','LongProjects','SocialPeople','SocialEncounters','SocialAttempts'):
            tables[table] = self.m.rows(f'SELECT * FROM {table} WHERE world=? ORDER BY rowid DESC LIMIT 60', (world,)) if world else []
        tables['construction']=self.construction.current(s) if s else None
        tables['cooking']=dict(job=self.cooking.current(s),reason=self.cooking.reason) if s else None
        tables['chapters']=self.autobiography.chapters(world) if s else []
        tables['generated_reflections']=self.philosophy.proposed_revisions(world) if s else []
        tables['mind']=self.mind.snapshot(world) if s else {}
        tables['mind']['context']=getattr(self.mind_context,'last_context',None) if s else None
        tables['mind']['context_error']=getattr(self.mind_context,'last_error',None)
        actions=self.m.rows("SELECT c.id,c.payload,c.status,eg.goal_id,e.plan_id FROM Commands c "
                            "JOIN ExperimentGoals eg ON eg.experiment=c.experiment "
                            "LEFT JOIN MindEvaluations e ON e.goal_id=eg.goal_id AND e.world=c.world AND e.session=c.session "
                            "AND e.kind='selection' AND e.outcome='influenced' "
                            "WHERE c.world=? AND c.session=? ORDER BY c.rowid DESC LIMIT 8",
                            (world,str(s.session))) if s else []
        tables['mind']['actions']=[dict(id=row['id'],action=json.loads(row['payload']).get('action'),status=row['status'],
                                        goal_id=row['goal_id'],plan_id=row['plan_id'],influenced=bool(row['plan_id'])) for row in actions]
        tables['mind']['results']=self.m.rows("SELECT ev.id,ev.type,ev.description,ev.timestamp,me.plan_id,me.goal_id,"
                                             "me.outcome,me.session FROM MindEvaluations me JOIN Events ev ON ev.id=me.event_id "
                                             "AND ev.world=me.world AND ev.session=me.session AND ev.verified=1 "
                                             "WHERE me.world=? AND me.session=? AND me.kind='outcome' ORDER BY me.created DESC LIMIT 12",
                                             (world,str(s.session))) if s else []
        tables['mind']['learning']={
            'memory': self.m.rows("SELECT lm.id,lm.source_event,lm.theme,lm.summary FROM LifeMemories lm "
                                  "JOIN Events ev ON ev.id=lm.source_event AND ev.world=lm.world AND ev.verified=1 "
                                  "AND ev.description=lm.summary WHERE lm.world=? ORDER BY lm.rowid DESC LIMIT 1",(world,)),
            'preference': self.m.rows("SELECT pu.source,pu.category,pu.subject,pu.old_value,pu.new_value "
                                      "FROM PreferenceUpdates pu JOIN Events ev ON ev.id=pu.source AND ev.world=pu.world "
                                      "AND ev.verified=1 WHERE pu.world=? ORDER BY pu.rowid DESC LIMIT 1",(world,))
        } if s else {'memory':[],'preference':[]}
        selection=self.m.rows("SELECT evidence,timestamp FROM Events WHERE world=? AND session=? "
                              "AND type='goal_selected' ORDER BY rowid DESC LIMIT 1",
                              (world,str(s.session))) if s else []
        tables['goal_selection']=dict(json.loads(selection[0]['evidence']),
                                      timestamp=selection[0]['timestamp']) if selection else None
        p = self.m.rows('SELECT values_json FROM Personality WHERE world=?', (world,)) if world else []
        return dict(connected=connected, observation=s.model_dump(mode='json') if s else None,
                    needs=project_needs(s,self.motivation.safety_limits(world) if world else (8,6)),
                    state=self.state if connected else 'PAUSED', reason=self.reason if connected else 'Sem heartbeat do mod; controle físico desativado',
                    motivation=self.dominant, personality=json.loads(p[0]['values_json']) if p else PERSONALITY,
                    planning_cycles=self.planning_cycles, decision_interval=self.interval, auto_publish=False,
                    skills=[dict(name=v.name,actions=v.actions,preconditions=v.preconditions,success=v.success) for v in self.skills.skills.values()], **tables)

    def record_advice(self, suggestion):
        """Persiste saídas do LLM como propostas não verificadas; não as transforma em fatos ou diário."""
        if not suggestion or not self.latest:return
        if suggestion.get('mind_version')==1:
            valid,reason=self.mind.validator.validate(self.latest,suggestion)
            self.mind.persist(self.latest,suggestion)
            if not valid:return
            if suggestion['output'].get('proposal'):
                legacy=self.mind.validator.to_legacy(suggestion)
                plan_id=self.language.accept(self.latest,legacy)
                if plan_id:self.mind.bind(plan_id,suggestion)
            return
        if suggestion.get('world')!=self.latest.world:return
        source_ids = suggestion.get('source_event_ids', [])
        if any(not self.m.rows('SELECT 1 FROM Events WHERE id=? AND world=? AND verified=1', (eid, self.latest.world))
               for eid in source_ids):
            return
        payload = {key: str(suggestion.get(key, '')) for key in
                   ('purpose','preferred_subject','question','hypothesis','interpretation','reflection','journal_draft','social_interpretation')}
        payload['source_event_ids'] = sorted(set(source_ids))
        key = __import__('hashlib').sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.m.db.execute('INSERT OR IGNORE INTO CognitiveSuggestions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (key,self.latest.world,payload['purpose'],payload['preferred_subject'],payload['question'],
                           payload['hypothesis'],payload['interpretation'],payload['journal_draft'],
                           payload['social_interpretation'],json.dumps(payload['source_event_ids']), 'unverified', now()))
        self.language.accept(self.latest,suggestion)
