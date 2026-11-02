"""Memória autobiográfica saliente, indexada por evidência do próprio mundo."""
import json
from uuid import uuid4
from agent.cognition import concepts
from agent.chapters import ChapterIndex, PHYSICAL, contexts, query_context, event_hash, terms


class Autobiography:
    def __init__(self, memory):
        self.m = memory
        self.index = ChapterIndex(memory)

    def record(self, world, event_id, theme, importance, novelty, context=None):
        rows = self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND verified=1', (event_id, world))
        if not rows:
            return None
        event = rows[0]
        self.index.index_event(world,event_id)
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
        return terms(text)

    def recall(self, world, cue, limit=4, context=None):
        """At most 200 indexed/salient candidates; contextual identity never comes from prose."""
        limit = max(1, min(12, int(limit)))
        query = self._terms(cue)
        meanings=concepts(cue)
        exact=query_context(context)
        semantic={('term',v) for v in sorted(query)[:24]}|{('concept',v) for v in sorted(meanings)[:12]}
        projection=('SELECT DISTINCT lm.*,e.day,e.type,e.description,e.evidence,e.session AS source_session,'
                    'e.timestamp AS source_timestamp,e.dedup AS source_dedup,e.verified,'
                    "COALESCE((SELECT source_hash FROM MemoryContextIndex fingerprint WHERE fingerprint.world=lm.world "
                    "AND fingerprint.source_event=lm.source_event LIMIT 1),'') AS source_hash")
        join=' FROM LifeMemories lm JOIN Events e ON e.id=lm.source_event AND e.world=lm.world '
        rows=[]
        # Fixed independent budgets keep even duplicate index matches bounded by 200.
        for keys,budget in ((exact,120),(semantic,50)):
            if not keys:continue
            pairs=sorted(keys)
            clause=' OR '.join('(i.kind=? AND i.value=?)' for _ in pairs)
            rows+=self.m.rows(projection+join+
                              'JOIN MemoryContextIndex i ON i.world=lm.world AND i.source_event=lm.source_event '
                              'WHERE lm.world=? AND e.verified=1 AND ('+clause+') '
                              'ORDER BY lm.importance DESC,e.day DESC,lm.created DESC LIMIT ?',
                              (world,*(v for pair in pairs for v in pair),budget))
        rows+=self.m.rows(projection+join+'WHERE lm.world=? AND e.verified=1 '
                          'ORDER BY lm.importance DESC,e.day DESC,lm.created DESC LIMIT 30',(world,))
        ranked = []
        for row in rows:
            if row['type'] not in PHYSICAL or row['summary']!=row['description']:continue
            event=dict(id=row['source_event'],world=row['world'],session=row['source_session'],day=row['day'],
                       timestamp=row['source_timestamp'],type=row['type'],description=row['description'],
                       verified=row['verified'],evidence=row['evidence'],dedup=row['source_dedup'])
            if row.get('source_hash') and row['source_hash']!=event_hash(event):continue
            terms = self._terms(row['theme'] + ' ' + row['summary'] + ' ' + row['context'])
            overlap = len(query & terms)
            association=len(meanings & concepts(row['summary']+' '+row['theme'],row['type']))
            contextual=len(exact & contexts(event))
            if not query and not exact or overlap or association or contextual:
                score = row['importance'] * .5 + row['novelty'] * .15 + min(.15, overlap * .05)+min(.2,association*.1)+min(1.2,contextual*.6)
                for key in ('source_session','source_timestamp','source_dedup','verified','source_hash'):row.pop(key,None)
                ranked.append((score, row['day'], row))
        ranked.sort(key=lambda v: (v[0], v[1],v[2]['source_event'],v[2]['theme']), reverse=True)
        result=[];seen=set()
        for score,_,row in ranked:
            if row['source_event'] in seen:continue
            seen.add(row['source_event']);result.append(dict(row,relevance=round(score,3)))
            if len(result)>=limit:break
        return result

    def chapters(self,world):
        return self.index.chapters(world)

    def backfill(self,world,limit=128):
        """Explicit maintenance only; recall/snapshot never perform migration or backfill."""
        return self.index.backfill(world,limit)
