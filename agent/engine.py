import json
import math
import time
from uuid import uuid4
from agent.memory import now

PERSONALITY = dict(curiosity=90, creativity=85, persistence=85, prudence=55,
                   sociability=60, ambition=65)


class CognitiveEngine:
    """Um experimento por vez; decisões retomadas de dados duráveis e evidências."""
    def __init__(self, memory, journal):
        self.m = memory
        self.journal = journal
        self.sessions = {}
        self.latest = None
        self.last_seen = 0.0
        self.control = None
        # A queda do processo invalida comandos; jamais reenvie ação antiga na reconexão.
        self.m.db.execute("UPDATE Commands SET status='interrupted' WHERE status='sent'")
        self.m.db.execute("UPDATE Experiments SET status='interrupted' WHERE status='running'")
        self.m.db.execute("UPDATE Goals SET status='interrupted' WHERE status='running'")
        self.m.db.commit()

    def _event(self, s, kind, text, evidence, dedup, verified=True):
        return self.m.event(s.world, str(s.session), s.day, kind, text, verified, evidence, dedup)

    def _command(self, s, exp, action, **extra):
        payload = dict(id=str(uuid4()), action=action, target=json.loads(exp['target']),
                       timeout_ms=20000, **extra)
        self.m.db.execute('INSERT INTO Commands VALUES(?,?,?,?,?,?,?,?)',
                          (payload['id'], s.world, str(s.session), exp['id'], json.dumps(payload),
                           'sent', None, now()))
        return payload

    def _finish(self, exp, status):
        self.m.db.execute('UPDATE Experiments SET status=? WHERE id=?', (status, exp['id']))
        self.m.db.execute('UPDATE Goals SET status=? WHERE id=?', (status, exp['id']))

    def _result(self, s, result):
        rows = self.m.rows('SELECT * FROM Commands WHERE id=? AND world=? AND session=?',
                           (str(result.id), s.world, str(s.session)))
        if not rows or rows[0]['status'] != 'sent':
            return
        cmd = rows[0]
        exp = self.m.rows('SELECT * FROM Experiments WHERE id=?', (cmd['experiment'],))[0]
        payload = json.loads(cmd['payload'])
        ev = result.evidence
        action = payload['action']
        self.m.db.execute('UPDATE Commands SET status=?,result=? WHERE id=?',
                          (result.status, result.model_dump_json(), cmd['id']))
        if result.status != 'success':
            eid = self._event(s, 'attempt_failed',
                              f"Hoje minha tentativa de {action} não foi concluída. Ainda não tenho uma resposta para esse experimento.",
                              {'command': cmd['id'], 'status': result.status, 'reason': result.reason}, cmd['id'])
            self._finish(exp, 'failed')
            self.journal.write(s.world, s.day, 'reflection', eid)
            return
        target = json.loads(exp['target'])
        valid_target = ev.get('target') == {k: target[k] for k in ('x', 'y', 'z')}
        if action == 'approach':
            valid = valid_target and ev.get('in_reach') is True
            phase = 'break'
        elif action == 'break':
            valid = (valid_target and ev.get('server_verified') is True and
                     ev.get('before_block') == target['id'] and ev.get('after_block') == 'minecraft:air' and
                     ev.get('mined_delta', 0) >= 1 and isinstance(ev.get('inventory_before'), dict))
            phase = 'collect'
            if valid:
                eid = self._event(s, 'block_removed',
                                  f"Consegui quebrar um bloco de {target['id']}. A remoção foi confirmada no mundo; isso, sozinho, não confirma coleta de material.",
                                  ev, cmd['id'])
                self.m.db.execute("INSERT INTO Knowledge VALUES(?,?,'partial',?) ON CONFLICT(world,subject) "
                                  "DO UPDATE SET status=CASE WHEN status='confirmed' THEN status ELSE 'partial' END, evidence_ids=excluded.evidence_ids",
                                  (s.world, target['id'], json.dumps([eid])))
                self.journal.write(s.world, s.day, 'reflection', eid)
        else:
            before = payload.get('baseline', 0)
            after = ev.get('inventory_after', {}).get(target['id'], 0)
            valid = (valid_target and ev.get('server_verified') is True and
                     isinstance(after, int) and after > before)
            phase = 'done'
            if valid:
                eid = self._event(s, 'collected',
                                  f"Hoje aprendi que minha tentativa com {target['id']} foi seguida pela coleta de {after - before} unidade(s) desse material. Vi o bloco desaparecer e o inventário aumentar. Quero investigar o que posso construir com essa madeira.",
                                  {'break_command': payload['break_command'], 'collect_command': cmd['id'],
                                   'before_count': before, 'after_count': after, 'server': ev}, cmd['id'])
                self.m.db.execute("INSERT INTO Knowledge VALUES(?,?,'confirmed',?) ON CONFLICT(world,subject) "
                                  "DO UPDATE SET status='confirmed',evidence_ids=excluded.evidence_ids",
                                  (s.world, target['id'], json.dumps([eid])))
                self.m.db.execute("UPDATE Hypotheses SET status='confirmed',evidence_ids=? WHERE id=?",
                                  (json.dumps([eid]), exp['hypothesis']))
                self._finish(exp, 'completed')
                self.journal.write(s.world, s.day, 'reflection', eid)
        if not valid:
            self.m.db.execute("UPDATE Commands SET status='unverified' WHERE id=?", (cmd['id'],))
            self._finish(exp, 'unverified')
            self._event(s, 'unverified_result', 'Recebi um resultado sem evidência suficiente. Preciso repetir a observação antes de concluir algo.',
                        {'command': cmd['id']}, cmd['id'])
            return
        self.m.db.execute('UPDATE Experiments SET phase=? WHERE id=?', (phase, exp['id']))

    def step(self, s):
        sid = str(s.session)
        state = self.sessions.get(sid)
        if state and (state['world'] != s.world or s.seq <= state['seq']):
            raise ValueError('Sessão/mundo ou sequência inválida')
        if self.latest and sid != str(self.latest.session) and time.monotonic() - self.last_seen < 3:
            raise ValueError('Outro cliente está conectado')
        if state is None:
            self.m.db.execute("UPDATE Experiments SET status='interrupted' WHERE world=? AND status='running'", (s.world,))
            self.m.db.execute("UPDATE Goals SET status='interrupted' WHERE world=? AND status='running'", (s.world,))
            self.m.db.execute("UPDATE Commands SET status='interrupted' WHERE world=? AND status='sent'", (s.world,))
        self.sessions[sid] = dict(seq=s.seq, world=s.world)
        self.latest, self.last_seen = s, time.monotonic()
        self.m.db.execute('INSERT OR IGNORE INTO Worlds VALUES(?,?)', (s.world, now()))
        self.m.db.execute('INSERT OR IGNORE INTO Personality VALUES(?,?)', (s.world, json.dumps(PERSONALITY)))
        # Persistência a 1 Hz; ponte a 4 Hz. Nunca acumula indefinidamente observações detalhadas.
        if s.seq % 4 == 1 or s.results:
            self.m.db.execute('INSERT OR IGNORE INTO Observations VALUES(?,?,?,?,?,?,?)',
                              (str(uuid4()), s.world, sid, s.day, now(), s.seq, s.model_dump_json()))
            self.m.db.execute('DELETE FROM Observations WHERE world=? AND rowid NOT IN '
                              '(SELECT rowid FROM Observations WHERE world=? ORDER BY rowid DESC LIMIT 10000)',
                              (s.world, s.world))
        for result in s.results:
            self._result(s, result)
        self.journal.finalize_before(s.world, s.day)
        response = dict(protocol=1, session=sid, seq=s.seq, ack=[str(r.id) for r in s.results],
                        control=None, command=None)
        if self.control:
            response['control'] = self.control
            self.control = None
        unsafe = s.player.health <= 8 or s.player.food <= 6 or s.player.danger
        if unsafe:
            response['control'] = 'pause'
        if s.active and not unsafe and response['control'] not in ('pause', 'stop'):
            response['command'] = self.decide(s)
        elif not s.active:
            self.m.db.execute("UPDATE Commands SET status='interrupted' WHERE session=? AND status='sent'", (sid,))
            self.m.db.execute("UPDATE Experiments SET status='interrupted' WHERE session=? AND status='running'", (sid,))
        self.m.db.commit()
        return response

    def decide(self, s):
        pending = self.m.rows("SELECT * FROM Commands WHERE session=? AND status='sent' ORDER BY created DESC", (str(s.session),))
        if pending:
            return json.loads(pending[0]['payload'])
        experiments = self.m.rows("SELECT * FROM Experiments WHERE world=? AND session=? AND status='running'",
                                  (s.world, str(s.session)))
        if experiments:
            exp = experiments[0]
            if exp['phase'] == 'collect':
                prior = self.m.rows("SELECT * FROM Commands WHERE experiment=? AND status='success' ORDER BY created DESC", (exp['id'],))
                broken = next(c for c in prior if json.loads(c['payload'])['action'] == 'break')
                evidence = json.loads(broken['result'])['evidence']
                target = json.loads(exp['target'])
                return self._command(s, exp, 'collect', baseline=evidence['inventory_before'].get(target['id'], 0),
                                     break_command=broken['id'])
            return self._command(s, exp, exp['phase'])
        # Um primeiro aprendizado completo encerra esta etapa. Crafting é uma próxima habilidade.
        if self.m.rows("SELECT 1 FROM Knowledge WHERE world=? AND status='confirmed' LIMIT 1", (s.world,)):
            return None
        personality = json.loads(self.m.rows('SELECT values_json FROM Personality WHERE world=?', (s.world,))[0]['values_json'])
        if s.time >= 12000 or personality['curiosity'] < 30:
            return None
        tried = {e['target'] for e in self.m.rows('SELECT target FROM Experiments WHERE world=?', (s.world,))}
        candidates = []
        for b in s.blocks:
            target = b.model_dump(exclude={'log'})
            # Só troncos naturais não descascados, com folhas observadas pelo mod.
            if b.log and json.dumps(target, sort_keys=True) not in tried:
                distance = math.dist((s.player.x, s.player.y, s.player.z), (b.x, b.y, b.z))
                if distance <= 14:
                    candidates.append((distance, target))
        if not candidates:
            return None
        target = min(candidates, key=lambda c: c[0])[1]
        question = f"O que consigo obter de {target['id']}?"
        hypothesis = str(uuid4())
        self.m.db.execute("INSERT OR IGNORE INTO Hypotheses VALUES(?,?,?,?,'hypothesis','[]')",
                          (hypothesis, s.world, question, 'Talvez quebrar esse tronco permita coletar material.'))
        hypothesis = self.m.rows('SELECT id FROM Hypotheses WHERE world=? AND question=?', (s.world, question))[0]['id']
        eid = self._event(s, 'question', f"Fiquei curioso ao observar {target['id']}. Minha pergunta é: {question} Minha hipótese é que consigo coletar material ao quebrá-lo; ainda preciso testar.",
                          {'observation_seq': s.seq, 'target': target}, f'question:{hypothesis}')
        self.m.db.execute("INSERT OR IGNORE INTO Knowledge VALUES(?,?,'hypothesis',?)",
                          (s.world, target['id'], json.dumps([eid])))
        exp = dict(id=str(uuid4()), world=s.world, session=str(s.session), hypothesis=hypothesis,
                   target=json.dumps(target, sort_keys=True), phase='approach', status='running', evidence_ids=json.dumps([eid]))
        self.m.db.execute('INSERT INTO Experiments VALUES(:id,:world,:session,:hypothesis,:target,:phase,:status,:evidence_ids)', exp)
        self.m.db.execute("INSERT INTO Goals VALUES(?,?,?,?,?,'running')",
                          (exp['id'], s.world, question, 'Curiosidade por material ainda não confirmado, perto do personagem e durante o dia.', personality['curiosity']))
        return self._command(s, exp, 'approach')

    def snapshot(self):
        s = self.latest
        world = s.world if s else None
        tables = {}
        for table in ('Knowledge', 'Hypotheses', 'Experiments', 'Goals', 'JournalEntries', 'PublicationQueue'):
            tables[table] = self.m.rows(f'SELECT * FROM {table} WHERE world=? ORDER BY rowid DESC LIMIT 30', (world,)) if world else []
        return dict(connected=bool(s and time.monotonic() - self.last_seen < 3),
                    observation=s.model_dump(mode='json') if s else None,
                    personality=PERSONALITY, auto_publish=False, **tables)
