import json
from agent.memory import now

PERSONALITY = dict(curiosity=95, creativity=90, persistence=90, prudence=60,
                   sociability=70, ambition=75, empathy=80, exploration=95, learning=95)


class MotivationEngine:
    def __init__(self, memory):
        self.m = memory

    def initialize(self, world, session, day):
        self.m.db.execute('INSERT OR IGNORE INTO Personality VALUES(?,?)', (world, json.dumps(PERSONALITY)))
        if not self.m.rows('SELECT 1 FROM AgentMigrations WHERE world=? AND version=2', (world,)):
            old = json.loads(self.m.rows('SELECT values_json FROM Personality WHERE world=?', (world,))[0]['values_json'])
            # Preserva personalidades customizadas. Atualiza só o preset original 0.1.
            if old == dict(curiosity=90, creativity=85, persistence=85, prudence=55, sociability=60, ambition=65):
                self.m.db.execute('UPDATE Personality SET values_json=? WHERE world=?', (json.dumps(PERSONALITY), world))
                self.m.event(world, session, day, 'personality',
                             'Minha configuração de motivação foi atualizada para a versão 0.2. Isso é uma mudança de parâmetros, não uma experiência no mundo.',
                             True, {'before': old, 'after': PERSONALITY, 'reason': 'user_requested_v0.2_preset'}, 'personality:v2')
            self.m.db.execute('INSERT INTO AgentMigrations VALUES(?,2)', (world,))

    def evaluate(self, s, novelty, frontier_count):
        p = self.values(s.world)
        danger = s.player.danger or s.player.health <= 8 or s.player.food <= 6
        values = {
            'DISCOVERY': (p['curiosity'] if novelty else 25, 'Novidade observada' if novelty else 'Nenhuma novidade executável próxima'),
            'UNDERSTANDING': (65, 'Relacionar perguntas com conhecimento confirmado'),
            'SURVIVAL': (100 if danger else 80 if s.time >= 12000 else max(10, 100-s.player.food*4), 'Vida, fome, perigos e horário observados'),
            'EXPLORATION': (85 if frontier_count and not novelty else 45, 'Fronteiras locais observadas'),
            'MASTERY': (p['persistence'] * .5, 'Reutilizar habilidades verificadas'),
            'CREATION': (p['creativity'] * .5, 'Interesse em aplicações; depende de habilidades futuras'),
            'AUTONOMY': (p['ambition'] * .6, 'Selecionar próximo passo executável'),
            'SOCIAL': (p['sociability'] * .3, 'Observação social; interação ainda indisponível'),
        }
        for name, (score, reason) in values.items():
            self.m.db.execute('INSERT INTO Motivations VALUES(?,?,?,?,?) ON CONFLICT(world,name) DO UPDATE '
                              'SET score=excluded.score,reason=excluded.reason,updated=excluded.updated',
                              (s.world, name, score, reason, now()))
        return max(values, key=lambda name: values[name][0]), p

    def values(self, world):
        stored = self.m.rows('SELECT values_json FROM Personality WHERE world=?', (world,))
        return {**PERSONALITY, **(json.loads(stored[0]['values_json']) if stored else {})}

    def safety_limits(self, world):
        # A prudência pode aumentar margens; nunca reduz a proteção física básica.
        margin = max(0, min(4, (self.values(world)['prudence'] - 60) / 10))
        return 8 + margin, 6 + margin

    def learn(self, s, evidence_id, success):
        events = self.m.rows('SELECT type,evidence FROM Events WHERE id=? AND world=? AND verified=1',
                             (evidence_id, s.world))
        if not events:
            return
        kind = events[0]['type']
        evidence = json.loads(events[0]['evidence'])
        changes = []
        if kind in ('collected', 'crafted', 'observed') and success:
            changes.append(('curiosity', .15, 'Uma investigação verificada ampliou o conjunto de experiências consultáveis'))
        if kind == 'crafted' and success:
            changes.extend([('creativity', .2, 'Uma transformação de receita foi comprovada no inventário'),
                            ('learning', .2, 'Uma receita foi confirmada por consumo, saída e estatística')])
        if kind == 'region_reached' and success:
            changes.append(('exploration', .2, 'Uma chegada a uma fronteira local foi confirmada'))
        if kind == 'attempt_failed':
            changes.append(('prudence', .2, 'Uma tentativa sem prova aumenta gradualmente a margem operacional de prudência'))
        prior_failure = self.m.rows("SELECT 1 FROM Events WHERE world=? AND type='attempt_failed' AND day<=? LIMIT 1",
                                    (s.world, s.day))
        if success and prior_failure and kind in ('collected', 'crafted', 'region_reached'):
            changes.append(('persistence', .15, 'Conclusão verificada após falhas anteriores'))
        if kind in ('collected', 'crafted') and success and s.player.health >= 16 and s.player.food >= 14:
            changes.append(('prudence', -.1, 'Uma ação concluída em contexto observado com margem segura'))
        if not changes:
            return
        p = self.values(s.world)
        from uuid import uuid4
        for trait, delta, reason in changes:
            if self.m.rows('SELECT 1 FROM PersonalityChanges WHERE world=? AND trait=? AND source_event=?',
                           (s.world, trait, evidence_id)):
                continue
            old = float(p.get(trait, PERSONALITY[trait]))
            new = max(5, min(95, round(old + delta, 2)))
            if new == old:
                continue
            p[trait] = new
            self.m.db.execute('INSERT INTO PersonalityChanges VALUES(?,?,?,?,?,?,?,?)',
                              (str(uuid4()), s.world, trait, old, new, reason, evidence_id, now()))
        self.m.db.execute('UPDATE Personality SET values_json=? WHERE world=?',
                          (json.dumps(p, sort_keys=True), s.world))
