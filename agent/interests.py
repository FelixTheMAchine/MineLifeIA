import json


class InterestManager:
    def __init__(self, memory):
        self.m = memory

    @staticmethod
    def topic(subject):
        value = subject.lower()
        if any(item in value for item in ('redstone', 'piston', 'observer', 'hopper', 'repeater', 'comparator')):
            return 'engineering'
        if any(item in value for item in ('wheat', 'carrot', 'potato', 'beetroot', 'seed', 'farmland')):
            return 'agriculture'
        if any(item in value for item in ('log', 'planks', 'crafting_table', 'stick', 'door', 'stairs', 'fence')):
            return 'architecture'
        if any(item in value for item in ('stone', 'ore', 'deepslate', 'cobblestone')):
            return 'mining'
        if any(item in value for item in ('village', 'villager', 'mca')):
            return 'community'
        return 'exploration'

    def update(self, s, topic, evidence_id, positive=True):
        inserted = self.m.db.execute('INSERT OR IGNORE INTO InterestUpdates VALUES(?,?,?)',
                                     (s.world, topic, evidence_id)).rowcount
        if not inserted:
            return
        self.m.db.execute("INSERT OR IGNORE INTO Interests VALUES(?,?,40,?,'[]',0,0,'[]')",
                          (s.world, topic, 'Experiência registrada: ' + evidence_id))
        row = self.m.rows('SELECT * FROM Interests WHERE world=? AND topic=?', (s.world, topic))[0]
        intensity = min(95, max(5, row['intensity'] + (3 if positive else -2)))
        ids = (json.loads(row['evidence_ids']) + [evidence_id])[-50:]
        self.m.db.execute('UPDATE Interests SET intensity=?,evidence_ids=?,positive=positive+?,negative=negative+? '
                          'WHERE world=? AND topic=?',
                          (intensity, json.dumps(ids), int(positive), int(not positive), s.world, topic))
        self.m.event(s.world, str(s.session), s.day, 'interest',
                     f"Meu interesse simulado em {topic} passou de {row['intensity']:g} para {intensity:g}, após revisar uma experiência {'bem-sucedida' if positive else 'sem sucesso'}. Esse ajuste vai influenciar minhas próximas escolhas.",
                     True, {'source_event': evidence_id, 'before': row['intensity'], 'after': intensity},
                     f'interest:{topic}:{evidence_id}')

    def score(self, world, topic):
        rows = self.m.rows('SELECT intensity FROM Interests WHERE world=? AND topic=?', (world, topic))
        return rows[0]['intensity'] if rows else 40
