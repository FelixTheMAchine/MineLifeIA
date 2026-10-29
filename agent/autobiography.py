"""Memória autobiográfica saliente, indexada por evidência do próprio mundo."""
import json
import re
from uuid import uuid4


class Autobiography:
    def __init__(self, memory):
        self.m = memory

    def record(self, world, event_id, theme, importance, novelty, context=None):
        rows = self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND verified=1', (event_id, world))
        if not rows:
            return None
        event = rows[0]
        importance = max(0.0, min(1.0, float(importance)))
        novelty = max(0.0, min(1.0, float(novelty)))
        memory_id = str(uuid4())
        self.m.db.execute('INSERT OR IGNORE INTO LifeMemories VALUES(?,?,?,?,?,?,?,?,?)',
                          (memory_id, world, event_id, theme, event['description'], importance, novelty,
                           json.dumps(context or {}, ensure_ascii=False), event['timestamp']))
        row = self.m.rows('SELECT * FROM LifeMemories WHERE world=? AND source_event=? AND theme=?',
                          (world, event_id, theme))
        return row[0] if row else None

    @staticmethod
    def _terms(text):
        return {v for v in re.findall(r'[a-z0-9_:.]{3,}', text.lower())
                if v not in {'minecraft', 'minecraft:overworld', 'que', 'para', 'com', 'sobre', 'the', 'and'}}

    def recall(self, world, cue, limit=4):
        """Recupera episódios relacionados lexicalmente e ponderados por saliência/recência."""
        limit = max(1, min(12, int(limit)))
        query = self._terms(cue)
        rows = self.m.rows('SELECT lm.*,e.day,e.type,e.description,e.evidence FROM LifeMemories lm '
                           'JOIN Events e ON e.id=lm.source_event AND e.world=lm.world '
                           'WHERE lm.world=? AND e.verified=1 ORDER BY lm.importance DESC,e.day DESC,lm.created DESC LIMIT 200',
                           (world,))
        ranked = []
        for row in rows:
            terms = self._terms(row['theme'] + ' ' + row['summary'] + ' ' + row['context'])
            overlap = len(query & terms)
            if not query or overlap:
                score = row['importance'] * .65 + row['novelty'] * .2 + min(.15, overlap * .05)
                ranked.append((score, row['day'], row))
        ranked.sort(key=lambda v: (v[0], v[1]), reverse=True)
        return [dict(item[2], relevance=round(item[0], 3)) for item in ranked[:limit]]
