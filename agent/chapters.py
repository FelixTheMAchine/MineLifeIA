"""Derived factual indexes. No model prose, journal mutation, or physical commands."""
import hashlib
import json
import math
import re
from uuid import UUID
from agent.cognition import concepts

RENDERER = 1
PHYSICAL = frozenset({'collected','crafted','resource_mined','cooked','placed','slept','ate',
    'crop_harvested','planted','soil_tilled','shelter_completed','shelter_entered','shelter_left',
    'region_reached','observed','inventory_gained','furnace_recovered','storage_deposited','storage_withdrawn',
    'person_observed','social_contact'})
TITLES = {'shelter_completed':'Verificação de um abrigo','cooked':'Preparo de recursos',
          'crafted':'Fabricação de itens','region_reached':'Visita a uma região',
          'social_contact':'Contato com pessoa observada'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS MemoryContextIndex(world TEXT NOT NULL,source_event TEXT NOT NULL,
 kind TEXT NOT NULL,value TEXT NOT NULL,source_hash TEXT NOT NULL,PRIMARY KEY(world,source_event,kind,value));
CREATE INDEX IF NOT EXISTS memory_context_lookup ON MemoryContextIndex(world,kind,value,source_event);
CREATE TABLE IF NOT EXISTS MemoryIndexProgress(world TEXT PRIMARY KEY,last_rowid INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS MemoryChapters(world TEXT NOT NULL,anchor_event TEXT NOT NULL,renderer INTEGER NOT NULL,
 payload TEXT NOT NULL,manifest TEXT NOT NULL,manifest_hash TEXT NOT NULL,PRIMARY KEY(world,anchor_event));
CREATE INDEX IF NOT EXISTS memory_chapters_world ON MemoryChapters(world,anchor_event);
CREATE INDEX IF NOT EXISTS events_context_types ON Events(world,verified,type,timestamp,id);
CREATE INDEX IF NOT EXISTS life_memories_source ON LifeMemories(world,source_event,importance);
'''


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def evidence(event):
    try:
        value=json.loads(event['evidence'])
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}


def event_hash(event):
    return digest({key:event[key] for key in ('id','world','session','day','timestamp','type','description','verified','evidence','dedup')})


def terms(text):
    return {v for v in re.findall(r'[a-z0-9_:.]{3,}',str(text).lower())
            if v not in {'minecraft','minecraft:overworld','que','para','com','sobre','the','and'}}


def position(value,dimension):
    if not isinstance(value,dict) or not isinstance(dimension,str) or not 1<=len(dimension)<=128:return None
    coordinates=[]
    for key in ('x','y','z'):
        n=value.get(key)
        if type(n) not in (int,float) or not math.isfinite(n) or abs(n)>30000000:return None
        coordinates.append(math.floor(n))
    return dimension+':'+':'.join(map(str,coordinates))


def contexts(event):
    """Identity and places come from evidence fields, never from narrative or item entity ids."""
    ev=evidence(event);out=set()
    objects=[ev]+[ev[k] for k in ('before','after','shelter','server') if isinstance(ev.get(k),dict)]
    dimension=next((o['dimension'] for o in objects if isinstance(o.get('dimension'),str)),None)
    for obj in objects:
        for key in ('project','project_id'):
            value=obj.get(key)
            if isinstance(value,str) and 1<=len(value)<=128:out.add(('project',value))
        for key in ('station','anchor','target','position'):
            value=position(obj.get(key),obj.get('dimension',dimension))
            if value:out.add(('place',value))
        value=obj.get('person_uuid')
        if event['type'] in ('person_observed','social_contact') and isinstance(value,str):
            try:out.add(('person',str(UUID(value))))
            except ValueError:pass
    return set(sorted(out)[:12])


def query_context(value):
    if not isinstance(value,dict):return set()
    out=set()
    for key,kind in (('project','project'),('project_id','project'),('person_uuid','person')):
        item=value.get(key)
        if isinstance(item,str) and 1<=len(item)<=128:
            if kind=='person':
                try:item=str(UUID(item))
                except ValueError:continue
            out.add((kind,item))
    place=position(value.get('place') or value.get('position') or value.get('target'),value.get('dimension'))
    if place:out.add(('place',place))
    return out


def chapter_contexts(event):
    keys=contexts(event)
    # Contact chapters follow the durable person UUID, even if multiple NPCs share a place.
    return {pair for pair in keys if pair[0]=='person'} if event['type']=='social_contact' else keys


class ChapterIndex:
    def __init__(self,memory):self.m=memory

    def _event(self,world,event_id,cache=None):
        if cache is not None:
            event=cache.get(event_id)
            return event if event and event.get('world')==world and event.get('verified')==1 and event.get('type') in PHYSICAL else None
        rows=self.m.rows('SELECT * FROM Events WHERE world=? AND id=? AND verified=1',(world,event_id))
        return rows[0] if rows and rows[0]['type'] in PHYSICAL else None

    def index_event(self,world,event_id):
        event=self._event(world,event_id)
        if not event:return False
        previous=self.m.rows('SELECT source_hash FROM MemoryContextIndex WHERE world=? AND source_event=? LIMIT 1',(world,event_id))
        if previous and previous[0]['source_hash']!=event_hash(event):return False
        keys=contexts(event)|{('event',event_id)}
        keys|={('term',v) for v in sorted(terms(event['description']))[:48]}
        keys|={('concept',v) for v in sorted(concepts(event['description'],event['type']))[:16]}
        self.m.db.execute('DELETE FROM MemoryContextIndex WHERE world=? AND source_event=?',(world,event_id))
        self.m.db.executemany('INSERT INTO MemoryContextIndex VALUES(?,?,?,?,?)',
                             [(world,event_id,kind,value,event_hash(event)) for kind,value in sorted(keys)])
        if event['type'] in TITLES:
            events=self._related(event)
            payload,manifest=self._render(event,events)
            self.m.db.execute('INSERT INTO MemoryChapters VALUES(?,?,?,?,?,?) ON CONFLICT(world,anchor_event) DO UPDATE SET '
                              'renderer=excluded.renderer,payload=excluded.payload,manifest=excluded.manifest,manifest_hash=excluded.manifest_hash',
                              (world,event_id,RENDERER,json.dumps(payload,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),digest(manifest)))
        return True

    def _related(self,anchor):
        keys=sorted(chapter_contexts(anchor))
        if not keys:return [anchor]
        conditions=' OR '.join('(i.kind=? AND i.value=?)' for _ in keys)
        rows=self.m.rows('SELECT DISTINCT e.* FROM MemoryContextIndex i JOIN Events e ON e.id=i.source_event AND e.world=i.world '
                         'WHERE i.world=? AND ('+conditions+') AND e.verified=1 AND e.timestamp<=? '
                         'ORDER BY e.timestamp DESC,e.id DESC LIMIT 32',
                         (anchor['world'],*(v for pair in keys for v in pair),anchor['timestamp']))
        selected=[e for e in rows if e['type'] in PHYSICAL and e['id']!=anchor['id'] and contexts(e)&set(keys)][:7]
        return sorted(selected+[anchor],key=lambda e:(e['timestamp'],e['id']))

    @staticmethod
    def _render(anchor,events):
        highlights=[{key:e[key] for key in ('id','day','type','description')} for e in events]
        payload=dict(id=digest([anchor['world'],anchor['id'],RENDERER]),title=TITLES[anchor['type']],
                     period=anchor['day'],first_day=min(e['day'] for e in events),last_day=max(e['day'] for e in events),
                     episodes=len(events),highlights=highlights,anchor_event=anchor['id'])
        manifest=dict(renderer=RENDERER,world=anchor['world'],anchor_event=anchor['id'],
                      event_ids=[e['id'] for e in events],event_hashes={e['id']:event_hash(e) for e in events})
        return payload,manifest

    def validate(self,row,cache=None):
        try:
            manifest=json.loads(row['manifest']);payload=json.loads(row['payload'])
            if not isinstance(manifest,dict) or not isinstance(payload,dict):return False
            if (row['renderer']!=RENDERER or manifest.get('renderer')!=RENDERER or digest(manifest)!=row['manifest_hash']
                    or manifest.get('world')!=row['world'] or manifest.get('anchor_event')!=row['anchor_event']):return False
            ids=manifest.get('event_ids')
            if not isinstance(ids,list) or not 1<=len(ids)<=8 or len(set(ids))!=len(ids) or row['anchor_event'] not in ids:return False
            anchor=self._event(row['world'],row['anchor_event'],cache)
            if not anchor or anchor['type'] not in TITLES:return False
            events=[self._event(row['world'],eid,cache) for eid in ids]
            if any(not e for e in events):return False
            if any(e['id']!=anchor['id'] and (e['timestamp']>anchor['timestamp'] or not contexts(e)&chapter_contexts(anchor)) for e in events):return False
            if events!=sorted(events,key=lambda e:(e['timestamp'],e['id'])):return False
            expected,proof=self._render(anchor,events)
            return payload==expected and manifest==proof
        except (KeyError,TypeError,ValueError):return False

    def chapters(self,world):
        kinds=tuple(TITLES)
        anchors=self.m.rows('SELECT e.*,c.anchor_event AS chapter_anchor,c.renderer AS chapter_renderer,'
                            'c.payload AS chapter_payload,c.manifest AS chapter_manifest,c.manifest_hash AS chapter_hash,'
                            'f.source_hash AS indexed_hash FROM Events e '
                            'LEFT JOIN MemoryChapters c ON c.world=e.world AND c.anchor_event=e.id '
                            "LEFT JOIN MemoryContextIndex f ON f.world=e.world AND f.source_event=e.id AND f.kind='event' AND f.value=e.id "
                            'WHERE e.world=? AND e.verified=1 AND e.type IN ('+','.join('?' for _ in kinds)+') '
                            'ORDER BY e.timestamp DESC,e.id DESC LIMIT 40',(world,*kinds))
        if not anchors:return []
        source_ids={a['id'] for a in anchors}
        for anchor in anchors:
            if anchor['chapter_anchor'] is None:continue
            try:
                manifest=json.loads(anchor['chapter_manifest'])
                ids=manifest.get('event_ids') if isinstance(manifest,dict) else None
                if isinstance(ids,list) and 1<=len(ids)<=8 and all(isinstance(eid,str) for eid in ids):source_ids.update(ids)
            except (ValueError,TypeError):pass
        # Forty anchors plus at most eight manifest members each: never over 360 IDs.
        source_ids=sorted(source_ids)
        sources=self.m.rows('SELECT * FROM Events WHERE world=? AND verified=1 AND id IN ('+
                            ','.join('?' for _ in source_ids)+') LIMIT 360',(world,*source_ids))
        cache={event['id']:event for event in sources}
        result=[]
        for anchor in anchors:
            source=cache.get(anchor['id'])
            if not source or source['type'] not in TITLES or anchor['indexed_hash'] and anchor['indexed_hash']!=event_hash(source):continue
            if anchor['chapter_anchor'] is not None:
                row=dict(world=world,anchor_event=anchor['chapter_anchor'],renderer=anchor['chapter_renderer'],
                         payload=anchor['chapter_payload'],manifest=anchor['chapter_manifest'],manifest_hash=anchor['chapter_hash'])
                if self.validate(row,cache):result.append(json.loads(row['payload']))
            else:
                # Read-only compatibility for events not yet reached by explicit maintenance.
                result.append(self._render(source,[source])[0])
        return result

    def backfill(self,world,limit=128):
        limit=max(1,min(128,int(limit)))
        rows=self.m.rows('SELECT last_rowid FROM MemoryIndexProgress WHERE world=?',(world,))
        last=rows[0]['last_rowid'] if rows else 0
        events=self.m.rows('SELECT rowid AS event_rowid,id FROM Events WHERE world=? AND rowid>? ORDER BY rowid LIMIT ?',
                           (world,last,limit))
        for event in events:self.index_event(world,event['id'])
        if events:self.m.db.execute('INSERT INTO MemoryIndexProgress VALUES(?,?) ON CONFLICT(world) DO UPDATE SET last_rowid=excluded.last_rowid',
                                   (world,events[-1]['event_rowid']))
        return len(events)
