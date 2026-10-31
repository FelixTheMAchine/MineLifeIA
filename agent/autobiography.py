"""Memória autobiográfica saliente, indexada por evidência do próprio mundo."""
import json
import re
from uuid import uuid4
from agent.cognition import concepts


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
        """Recuperação por conceitos, tipos de episódio, termos e saliência; sem supor embeddings disponíveis."""
        limit = max(1, min(12, int(limit)))
        query = self._terms(cue)
        meanings=concepts(cue)
        rows = self.m.rows('SELECT lm.*,e.day,e.type,e.description,e.evidence FROM LifeMemories lm '
                           'JOIN Events e ON e.id=lm.source_event AND e.world=lm.world '
                           'WHERE lm.world=? AND e.verified=1 ORDER BY lm.importance DESC,e.day DESC,lm.created DESC LIMIT 200',
                           (world,))
        ranked = []
        for row in rows:
            terms = self._terms(row['theme'] + ' ' + row['summary'] + ' ' + row['context'])
            overlap = len(query & terms)
            association=len(meanings & concepts(row['summary']+' '+row['theme'],row['type']))
            if not query or overlap or association:
                score = row['importance'] * .5 + row['novelty'] * .15 + min(.15, overlap * .05)+min(.2,association*.1)
                ranked.append((score, row['day'], row))
        ranked.sort(key=lambda v: (v[0], v[1]), reverse=True)
        return [dict(item[2], relevance=round(item[0], 3)) for item in ranked[:limit]]

    def chapters(self,world):
        """Compact factual chapter index, rebuilt from evidence, not invented summaries."""
        periods=self.m.rows("SELECT CAST((day-1)/10 AS INTEGER) period,min(day) first_day,max(day) last_day,count(*) episodes "
                            "FROM Events WHERE world=? AND verified=1 AND type IN ('collected','crafted','resource_mined','cooked','shelter_completed','region_reached','slept') "
                            "GROUP BY period ORDER BY period DESC LIMIT 40",(world,))
        for p in periods:
            p['highlights']=self.m.rows("SELECT id,day,type,description FROM Events WHERE world=? AND verified=1 AND day BETWEEN ? AND ? "
                                       "AND type IN ('collected','crafted','resource_mined','cooked','shelter_completed','region_reached','slept') ORDER BY timestamp LIMIT 3",
                                       (world,p['first_day'],p['last_day']))
        return periods
