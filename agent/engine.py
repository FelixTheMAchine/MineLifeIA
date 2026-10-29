import json
import math
import time
from uuid import uuid4
from agent.memory import now
from agent.motivation import MotivationEngine, PERSONALITY
from agent.interests import InterestManager
from agent.goals import GoalManager
from agent.skills import SkillRegistry
from agent.exploration import ExplorationManager, region
from agent.autobiography import Autobiography
from agent.philosophy import PhilosophicalReflectionEngine


def valid_inventory(value):
    return isinstance(value, dict) and len(value) <= 256 and all(isinstance(k,str) and type(v) is int and 0 <= v <= 1000000 for k,v in value.items())


class CognitiveEngine:
    """Cognição por eventos; um executor físico, planejamento em frequência controlada."""
    def __init__(self, memory, journal, settings=None, clock=time.monotonic):
        self.m, self.journal, self.clock = memory, journal, clock
        settings = settings or {}
        self.interval = max(.5, min(10, settings.get('decision_interval', 2.0)))
        self.goals = GoalManager(memory, max(1, min(32, settings.get('max_active_goals', 8))))
        self.skills, self.interests = SkillRegistry(), InterestManager(memory)
        self.motivation, self.exploration = MotivationEngine(memory), ExplorationManager(memory)
        self.autobiography = Autobiography(memory)
        self.philosophy = PhilosophicalReflectionEngine(memory, self.autobiography)
        self.sessions, self.last_plan, self.command_sent = {}, {}, {}
        self.latest, self.last_seen, self.control = None, 0.0, None
        self.state, self.reason, self.dominant = 'PAUSED', 'Aguardando autorização local', 'DISCOVERY'
        self.planning_cycles = 0
        self.initialized = set()
        self.advice = None
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
        return self.m.event(s.world, str(s.session), s.day, kind, text, True, evidence, dedup)

    def _goal_id(self, exp):
        rows = self.m.rows('SELECT goal_id FROM ExperimentGoals WHERE experiment=?', (exp['id'],))
        return rows[0]['goal_id'] if rows else exp['id']

    def _command(self, s, exp, action, **extra):
        payload = dict(id=str(uuid4()), action=action, target=json.loads(exp['target']), timeout_ms=20000, **extra)
        self.m.db.execute('INSERT INTO Commands VALUES(?,?,?,?,?,?,?,?)',
                          (payload['id'], s.world, str(s.session), exp['id'], json.dumps(payload), 'sent', None, now()))
        self.command_sent[payload['id']] = self.clock()
        self._state(s, 'EXPLORING' if action == 'explore' else 'EXPERIMENTING',
                    {'approach': 'Aproximando de um alvo observado', 'break': 'Testando quebra de tronco',
                     'collect': 'Verificando coleta', 'observe': 'Verificando um bloco',
                     'craft': 'Testando receita desbloqueada na grade 2×2', 'explore': 'Avançando para fronteira local validada',
                     'eat': 'Recuperando a fome com alimento disponível'}[action])
        return payload

    def _knowledge(self, s, subject, status, eid):
        existing = self.m.rows('SELECT * FROM Knowledge WHERE world=? AND subject=?', (s.world, subject))
        ids = json.loads(existing[0]['evidence_ids']) if existing else []
        ids = list(dict.fromkeys(ids + [eid]))
        if existing and existing[0]['status'] == 'confirmed': status = 'confirmed'
        self.m.db.execute('INSERT INTO Knowledge VALUES(?,?,?,?) ON CONFLICT(world,subject) DO UPDATE SET '
                          'status=excluded.status,evidence_ids=excluded.evidence_ids', (s.world, subject, status, json.dumps(ids)))

    def _complete(self, s, exp, eid, subject):
        gid = self._goal_id(exp)
        self.m.db.execute("UPDATE Experiments SET status='completed',phase='done',evidence_ids=? WHERE id=?", (json.dumps([eid]), exp['id']))
        self.m.db.execute("UPDATE Goals SET status='completed' WHERE id=?", (gid,))
        self.m.db.execute("UPDATE Hypotheses SET status='confirmed',evidence_ids=? WHERE id=?", (json.dumps([eid]), exp['hypothesis']))
        plans = self.m.rows('SELECT * FROM GoalPlans WHERE goal_id=?', (gid,))
        if plans:
            self.skills.record(self.m, s.world, plans[0]['skill'], True)
            self.m.db.execute("UPDATE Questions SET status='answered' WHERE world=? AND subject=?", (s.world, plans[0]['subject']))
        self.interests.update(s, self.interests.topic(subject), eid)
        self.motivation.learn(s, eid, True)
        event_type = self.m.rows('SELECT type FROM Events WHERE id=?', (eid,))[0]['type']
        knowledge = self.m.rows('SELECT evidence_ids FROM Knowledge WHERE world=? AND subject=?', (s.world, subject))
        first_evidence = bool(knowledge and len(json.loads(knowledge[0]['evidence_ids'])) == 1)
        importance = {'crafted': .82, 'collected': .8, 'region_reached': .68, 'observed': .35}.get(event_type, .3)
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
        self.m.db.execute('UPDATE Experiments SET status=? WHERE id=?', (status, exp['id']))
        self.m.db.execute('UPDATE Goals SET status=? WHERE id=?', (status, gid))
        personality = self.motivation.values(s.world)
        self.goals.cooldown = max(30, min(180, 60 + (personality['prudence']-60)*.5 - (personality['persistence']-90)*.2))
        self.goals.failure(gid, reason, status == 'cancelled')
        cancelled = status == 'cancelled'
        text = ('Interrompi uma ação após a suspensão do controle; isso não contradiz minha hipótese.' if cancelled else
                f"Minha tentativa de {cmd['action']} não terminou com evidência suficiente ({reason}). Vou considerar outra oportunidade antes de tentar novamente.")
        target = json.loads(exp['target'])
        eid = self._event(s, 'attempt_cancelled' if cancelled else 'attempt_failed', text,
                          {'command': cmd['id'], 'goal': gid, 'subject': target.get('id',''),
                           'reason': reason, 'outcome': status}, cmd['id'])
        if not cancelled:
            self.autobiography.record(s.world, eid, 'setbacks', .68, .6,
                                      {'day': s.day, 'subject': target.get('id',''), 'reason': reason})
            self.philosophy.consider(s.world, s.day, str(s.session), eid)
            plans = self.m.rows('SELECT skill FROM GoalPlans WHERE goal_id=?', (gid,))
            if plans: self.skills.record(self.m, s.world, plans[0]['skill'], False)
            self.interests.update(s, self.interests.topic(json.loads(exp['target'])['id']), eid, False)
            self.motivation.learn(s, eid, False)
        self.m.db.execute('INSERT OR IGNORE INTO Reflections VALUES(?,?,?,?,?,?,?,?)',
                          (str(uuid4()), s.world, exp['id'], 'FAILURE', 0.0, json.dumps([eid]),
                           'Aplicar cooldown, mudar alvo; abandonar após duas falhas', now()))
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
            phase = 'observe' if kind == 'observe' else 'break'
        elif action == 'break':
            valid &= (ev.get('server_verified') is True and ev.get('before_block') == target['id'] and
                      ev.get('after_block') == 'minecraft:air' and type(ev.get('mined_delta')) is int and ev['mined_delta'] >= 1 and
                      valid_inventory(ev.get('inventory_before')))
            phase = 'collect'
            if valid:
                eid = self._event(s, 'block_removed', f"Consegui quebrar {subject}. O servidor confirmou a remoção; ainda preciso verificar a coleta.", ev, cmd['id'])
                self._knowledge(s, subject, 'partial', eid)
                self.journal.write(s.world, s.day, 'reflection', eid)
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
                eid = self._event(s, 'region_reached', f"Cheguei à região que escolhi investigar. Observei o bioma {s.biome}; vou usar essa visita para orientar meus próximos destinos.", ev, cmd['id'])
        elif action == 'craft':
            recipe = cmd['recipe']
            a, b = ev.get('inventory_before', {}), ev.get('inventory_after', {})
            valid &= (valid_inventory(a) and valid_inventory(b) and ev.get('server_verified') is True
                      and ev.get('recipe') == recipe['id'] and type(ev.get('crafted_delta')) is int and ev.get('crafted_delta') == recipe['output_count']
                      and a.get(recipe['input_id'], 0) - b.get(recipe['input_id'], 0) == recipe.get('input_count',1)
                      and b.get(recipe['output_id'], 0) - a.get(recipe['output_id'], 0) == recipe['output_count'])
            if valid:
                subject = 'recipe:' + recipe['id']
                eid = self._event(s, 'crafted', f"Testei a receita {recipe['id']}: consumi {recipe.get('input_count',1)} {recipe['input_id']} e obtive {recipe['output_count']} {recipe['output_id']}. As mudanças de inventário e a fabricação foram verificadas no servidor.", ev, cmd['id'])
                self._knowledge(s, subject, 'confirmed', eid)
                self.goals.supersede(s.world, 'application:' + recipe['input_id'])
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
                        ack=[str(r.id) for r in s.results], control=self.control, command=None)
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
        else: response['command'] = self.decide(s, changed or previous is None)
        if not s.active or not s.armed or unsafe or response['control'] in ('stop', 'pause'):
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
            if item.startswith('recipe:'):
                self.goals.ensure(s, subject, 'Investigar ferramentas usando uma bancada', 'Usar uma bancada e receitas 3×3 requer um controlador ainda não implementado; fabricar o item bancada na grade 2×2 já é possível.',
                                  40, 'future', {}, 'craft_table', 'MEDIUM_TERM', blocked=True)
            elif not any(r.input_id == item for r in s.recipes):
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
        self.m.db.execute("UPDATE Goals SET status='deferred' WHERE world=? AND status='pending'", (s.world,))
        self._state(s, 'PLANNING', 'Consultando memória, necessidades e oportunidades')
        self.exploration.record(s)
        known = {r['subject']: r for r in self.m.rows("SELECT * FROM Knowledge WHERE world=? AND status='confirmed'", (s.world,))}
        candidates = [b for b in s.blocks if (b.id if b.log else 'observation:'+b.id) not in known]
        frontiers = self.exploration.candidates(s)
        self.dominant, personality = self.motivation.evaluate(s, bool(candidates), len(frontiers))
        self._derive(s, known)
        # Hunger is an executable need only when safe food is available in the hotbar.
        if s.player.food <= self.motivation.safety_limits(s.world)[1]:
            foods = [f.model_dump() for f in s.player.foods if self._safe_food(f.model_dump(), s.player.inventory)]
            if foods and 'eat' in s.capabilities:
                food = max(foods, key=lambda f: (f['nutrition'], f['count'], f['id']))
                meal_prefix = f'meal:{s.day}:'
                meal_number = self.m.rows('SELECT count(*) n FROM GoalPlans WHERE world=? AND subject LIKE ?',
                                          (s.world, meal_prefix + '%'))[0]['n'] + 1
                subject = meal_prefix + food['id'] + ':' + str(meal_number)
                target = dict(x=math.floor(s.player.x), y=math.floor(s.player.y), z=math.floor(s.player.z), id=food['id'])
                gid = self.goals.ensure(s, subject, 'Comer alimento para recuperar minhas reservas',
                                        'Fome baixa observada e alimento seguro no inventário.',
                                        1000 + (20-s.player.food)*10, 'survival',
                                        {'target': target, 'food': food}, 'eat_food', 'IMMEDIATE')
                if gid:
                    goal = next(g for g in self.goals.rows(s.world) if g['id'] == gid)
                    hypothesis = str(uuid4())
                    self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                                      (hypothesis, s.world, goal['description'], 'Consumir o alimento deve elevar a fome e reduzir sua quantidade no inventário.'))
                    hypothesis = self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?',
                                             (s.world, goal['description']))[0]['id']
                    exp = dict(id=str(uuid4()), world=s.world, session=str(s.session), hypothesis=hypothesis,
                               target=json.dumps(target, sort_keys=True), phase='eat', status='running', evidence_ids='[]')
                    self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)', exp)
                    self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)', (exp['id'], gid))
                    self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?", (gid,))
                    return self._command(s, exp, 'eat', food=food)
            self._state(s, 'WAITING_FOR_SAFE_ACTION', 'Fome baixa; sem alimento seguro executável no inventário')
            return None
        if s.time >= 12000:
            self._state(s, 'WAITING_FOR_SAFE_ACTION', 'Noite: aguardando luz; abrigo e combate ainda não executáveis')
            return None
        offered = set()
        for recipe in s.recipes:
            subject = 'recipe:' + recipe.id
            if subject in known or not (recipe.output_id.endswith('_planks') or recipe.output_id in ('minecraft:stick','minecraft:crafting_table')): continue
            if s.player.inventory.get(recipe.input_id, 0) < recipe.input_count: continue
            params = dict(target=dict(x=math.floor(s.player.x), y=math.floor(s.player.y), z=math.floor(s.player.z), id='minecraft:air'), recipe=recipe.model_dump())
            gid = self.goals.ensure(s, subject, 'Testar a receita ' + recipe.id, 'Receita desbloqueada, recurso disponível e resultado ainda não verificado.',
                                    110 + (personality['creativity']-90)*.2 + self.interests.score(s.world, self.interests.topic(recipe.id))*.05,
                                    'craft', params, 'craft_planks')
            self.goals.question(s, subject, f'A receita {recipe.id} produz {recipe.output_id} usando meu material?')
            if gid: offered.add(gid)
        for b in sorted(candidates, key=lambda b: math.dist((s.player.x, s.player.y, s.player.z), (b.x, b.y, b.z))):
            if math.dist((s.player.x, s.player.y, s.player.z), (b.x, b.y, b.z)) > 14: continue
            subject = ('log:' if b.log else 'observe:') + b.id
            skill = 'investigate_log' if b.log else 'observe_block'
            if not self.skills.available(skill, s.capabilities): continue
            target = b.model_dump(exclude={'log'})
            if self.m.rows("SELECT 1 FROM Experiments WHERE world=? AND target=? AND status IN ('failed','unverified')", (s.world, json.dumps(target, sort_keys=True))): continue
            question = f'O que consigo obter de {b.id}?' if b.log else f'Consigo confirmar de perto a presença de {b.id}?'
            gid = self.goals.ensure(s, subject, question, 'Novidade observada e habilidade disponível; segurança será revalidada ao caminhar.',
                                    personality['curiosity'] + self.interests.score(s.world, self.interests.topic(b.id))*.1 - (0 if b.log else 15) + (personality['learning']-95)*.1,
                                    'log' if b.log else 'observe', {'target': target}, skill)
            if gid:
                self.goals.question(s, subject, question)
                offered.add(gid)
        for length, key, target in frontiers:
            if not self.skills.available('explore_region', s.capabilities): break
            subject = f'explore:{s.dimension}:{key}'
            gid = self.goals.ensure(s, subject, 'Explorar uma região ainda não visitada',
                                    'Fronteira local anunciada pelo navegador; caminho será revalidado a cada passo.',
                                    70 + personality['exploration']*.1 + (personality['ambition']-75)*.1 - length*.1, 'explore', {'target': target}, 'explore_region')
            if gid:
                self.goals.question(s, subject, 'Que recursos e bioma vou observar na próxima região acessível?')
                offered.add(gid)
        goals = self.goals.rows(s.world)
        if self.advice and self.advice.get('world') == s.world:
            preferred = self.advice.get('preferred_subject')
            goals.sort(key=lambda g: (g['subject']==preferred, g['priority']), reverse=True)
        for goal in goals:
            if goal['id'] not in offered or goal['status'] != 'pending' or goal['cooldown'] > time.time(): continue
            if not self.skills.available(goal['skill'], s.capabilities):
                self.m.db.execute("UPDATE Goals SET status='blocked',reason='Habilidade não anunciada pelo mod' WHERE id=?", (goal['id'],))
                continue
            params = json.loads(goal['params'])
            hypothesis = str(uuid4())
            self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                              (hypothesis, s.world, goal['description'], 'O experimento pode produzir evidência para esta pergunta.'))
            hypothesis = self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?', (s.world, goal['description']))[0]['id']
            phase = 'craft' if goal['kind']=='craft' else 'explore' if goal['kind']=='explore' else 'approach'
            exp = dict(id=str(uuid4()), world=s.world, session=str(s.session), hypothesis=hypothesis,
                       target=json.dumps(params['target'], sort_keys=True), phase=phase, status='running', evidence_ids='[]')
            self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)', exp)
            self.m.db.execute('INSERT INTO ExperimentGoals VALUES(?,?)', (exp['id'], goal['id']))
            self.m.db.execute("UPDATE Goals SET status='running' WHERE id=?", (goal['id'],))
            self.m.db.execute('UPDATE Interests SET goals=? WHERE world=? AND topic=?',
                              (json.dumps([goal['id']]), s.world, self.interests.topic(params['target']['id'])))
            return self._command(s, exp, phase, **({'recipe': params['recipe']} if phase == 'craft' else {}))
        reason = f'Nenhuma novidade executável ou fronteira não visitada com rota segura. Reavaliando a cada {self.interval} s.'
        if 'explore' not in s.capabilities: reason += ' Instale o mod 0.2 para anunciar exploração e crafting.'
        self._state(s, 'WAITING_FOR_SAFE_ACTION', reason)
        return None

    @staticmethod
    def _safe_food(food, inventory):
        if not isinstance(food, dict) or food.get('id') not in inventory:
            return False
        if not all(type(food.get(k)) is int for k in ('slot', 'count', 'nutrition')):
            return False
        if not (0 <= food['slot'] <= 8 and 1 <= food['count'] <= 64 and 1 <= food['nutrition'] <= 20):
            return False
        return food['id'] not in {'minecraft:rotten_flesh', 'minecraft:spider_eye', 'minecraft:poisonous_potato',
                                  'minecraft:pufferfish', 'minecraft:raw_chicken', 'minecraft:chorus_fruit'}

    def snapshot(self):
        s = self.latest
        world = s.world if s else None
        connected = bool(s and self.clock()-self.last_seen < 3)
        tables = {}
        for table in ('Knowledge','Hypotheses','Experiments','Goals','JournalEntries','PublicationQueue','Questions',
                      'Interests','Motivations','SpatialRegions','Reflections','SkillProgress','PersonalityChanges',
                      'LifeMemories','PhilosophicalQuestions','PhilosophicalRevisions','CognitiveSuggestions'):
            tables[table] = self.m.rows(f'SELECT * FROM {table} WHERE world=? ORDER BY rowid DESC LIMIT 60', (world,)) if world else []
        p = self.m.rows('SELECT values_json FROM Personality WHERE world=?', (world,)) if world else []
        return dict(connected=connected, observation=s.model_dump(mode='json') if s else None,
                    state=self.state if connected else 'PAUSED', reason=self.reason if connected else 'Sem heartbeat do mod; controle físico desativado',
                    motivation=self.dominant, personality=json.loads(p[0]['values_json']) if p else PERSONALITY,
                    planning_cycles=self.planning_cycles, decision_interval=self.interval, auto_publish=False,
                    skills=[dict(name=v.name,actions=v.actions,preconditions=v.preconditions,success=v.success) for v in self.skills.skills.values()], **tables)

    def record_advice(self, suggestion):
        """Persiste saídas do LLM como propostas não verificadas; não as transforma em fatos ou diário."""
        if not suggestion or not self.latest or suggestion.get('world') != self.latest.world:
            return
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
