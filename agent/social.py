"""Observed people and bounded MCA contact; familiarity never implies affinity."""
import json
import math
import re
from uuid import UUID
from agent.memory import now

ACTIONS={'social_observe','social_contact'}
TYPES={'minecraft:villager','mca:male_villager','mca:female_villager'}
MCA_VERSION='7.7.19+1.21.1'
SCREEN='net.conczin.mca.client.gui.InteractScreen'
SCHEMA='''
CREATE TABLE IF NOT EXISTS SocialPeople(world TEXT NOT NULL,person_uuid TEXT NOT NULL,
 entity_type TEXT NOT NULL,name TEXT NOT NULL,dimension TEXT NOT NULL,last_position TEXT NOT NULL,
 first_day INTEGER NOT NULL,last_day INTEGER NOT NULL,observed_days TEXT NOT NULL,last_event TEXT NOT NULL,
 relationship TEXT NOT NULL DEFAULT 'unknown' CHECK(relationship='unknown'),last_session TEXT,last_seq INTEGER,
 updated TEXT NOT NULL,PRIMARY KEY(world,person_uuid));
CREATE TABLE IF NOT EXISTS SocialEncounters(event_id TEXT PRIMARY KEY REFERENCES Events(id),world TEXT NOT NULL,
 person_uuid TEXT NOT NULL,day INTEGER NOT NULL,action TEXT NOT NULL,command_id TEXT NOT NULL UNIQUE,
 snapshot TEXT NOT NULL,created TEXT NOT NULL,
 FOREIGN KEY(world,person_uuid) REFERENCES SocialPeople(world,person_uuid));
CREATE TABLE IF NOT EXISTS SocialAttempts(world TEXT NOT NULL,person_uuid TEXT NOT NULL,day INTEGER NOT NULL,
 command_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,session TEXT NOT NULL,dimension TEXT NOT NULL,
 created TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(world,person_uuid,day));
'''


def uid(value):
    try:return str(UUID(str(value)))
    except (ValueError,TypeError,AttributeError):return None


def valid_snapshot(value,person,entity_type,dimension):
    if not isinstance(value,dict):return False
    if (uid(value.get('person_uuid'))!=person or value.get('entity_type')!=entity_type
            or value.get('dimension')!=dimension or value.get('alive') is not True
            or value.get('visible') is not True or not uid(value.get('player_uuid'))):return False
    if (not isinstance(value.get('name'),str) or not 1<=len(value['name'])<=96
            or re.search(r'[\x00-\x1f\x7f]',value['name'])):return False
    position=value.get('position')
    if not isinstance(position,dict) or any(type(position.get(k)) not in (int,float) or
            not math.isfinite(position[k]) for k in ('x','y','z')):return False
    distance=value.get('distance')
    if type(distance) not in (int,float) or not math.isfinite(distance) or not 0<=distance<=3.5:return False
    inventory=value.get('inventory')
    if (not isinstance(inventory,dict) or len(inventory)>256 or
            any(not isinstance(k,str) or not re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+',k)
                or type(v) is not int or not 0<=v<=1000000 for k,v in inventory.items())):return False
    if not isinstance(value.get('inventory_fingerprint'),str) or not re.fullmatch('[a-f0-9]{64}',value['inventory_fingerprint']):return False
    if any(not isinstance(value.get(k),str) for k in ('main_hand','off_hand')):return False
    return ('interacting_player' in value and
            (value['interacting_player'] is None or uid(value['interacting_player']) is not None))


class SocialManager:
    def __init__(self,memory):
        self.m=memory
        self.reason='Conhecimento social limitado a observacoes verificadas.'

    def _person(self,s,person):
        rows=self.m.rows('SELECT * FROM SocialPeople WHERE world=? AND person_uuid=?',(s.world,person))
        return rows[0] if rows else None

    def _attempt(self,s,person):
        rows=self.m.rows('SELECT * FROM SocialAttempts WHERE world=? AND person_uuid=? AND day=?',(s.world,person,s.day))
        return rows[0] if rows else None

    def _offer(self,s,person,entity_type):
        for offer in getattr(s,'social',[]):
            data=offer.model_dump(mode='json') if hasattr(offer,'model_dump') else vars(offer) if not isinstance(offer,dict) else offer
            if uid(data.get('person_uuid'))==person and data.get('entity_type')==entity_type:return data
        return None

    def _safe(self,s):
        return (not s.player.danger and s.player.food>12 and s.player.health>12 and s.time<12000
                and getattr(s,'active',True) and getattr(s,'armed',True))

    def _fresh(self,s,row):
        return (row and row['last_session']==str(s.session) and row['last_day']==s.day
                and row['dimension']==s.dimension and row['last_seq'] is not None
                and 0<=s.seq-row['last_seq']<=20)

    def propose(self,s,personality):
        if not self._safe(s):return []
        result=[]
        curiosity=personality.get('curiosity',50) if isinstance(personality,dict) else 50
        social=personality.get('social',50) if isinstance(personality,dict) else 50
        curiosity=curiosity if type(curiosity) in (int,float) and math.isfinite(curiosity) else 50
        social=social if type(social) in (int,float) and math.isfinite(social) else 50
        priority=80+max(0,min(100,curiosity))*.05+max(0,min(100,social))*.08
        seen=set()
        for offer in getattr(s,'social',[]):
            data=offer.model_dump(mode='json') if hasattr(offer,'model_dump') else vars(offer) if not isinstance(offer,dict) else offer
            person=uid(data.get('person_uuid'));entity_type=data.get('entity_type')
            if not person or person in seen or entity_type not in TYPES:continue
            seen.add(person)
            coordinates=tuple(data.get(k) for k in ('x','y','z'))
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in coordinates):continue
            distance=math.dist(coordinates,(s.player.x,s.player.y,s.player.z))
            if distance>12:continue
            row=self._person(s,person);fresh=self._fresh(s,row)
            contact=(entity_type.startswith('mca:') and data.get('can_contact') is True
                     and 'social_contact' in s.capabilities and not self._attempt(s,person))
            observed=(row and row['last_session']==str(s.session) and row['last_day']==s.day
                      and row['dimension']==s.dimension and row['entity_type']==entity_type
                      and row['name']==data.get('name'))
            if not observed or contact and not fresh:
                action='social_observe';skill='observe_person'
            elif contact and distance<=3.5:
                action='social_contact';skill='contact_person'
            else:continue
            if action not in s.capabilities:continue
            token=(row['last_event'] if row else 'new') if action=='social_observe' else 'daily'
            result.append(dict(subject=f'{action}:{s.dimension}:{person}:{s.day}:{s.session}:{token}',
                               description='Observar pessoa proxima' if action=='social_observe' else 'Iniciar contato MCA observado',
                               reason='Pessoa identificada por UUID; familiaridade observada nao demonstra afinidade.',
                               priority=priority,kind=action,skill=skill,category='SHORT_TERM',
                               params=dict(target=dict(zip(('x','y','z'),map(math.floor,coordinates)),id=entity_type),
                                           social=dict(person_uuid=person,entity_type=entity_type))))
        return result

    def prepare_command(self,s,cmd):
        if cmd.get('action')!='social_contact':return
        request=cmd.get('social',{});person=uid(request.get('person_uuid'));entity_type=request.get('entity_type')
        row=self._person(s,person);offer=self._offer(s,person,entity_type)
        if (not self._safe(s) or 'social_contact' not in s.capabilities or entity_type not in TYPES
                or not entity_type.startswith('mca:') or not self._fresh(s,row) or row['entity_type']!=entity_type
                or not offer or offer.get('can_contact') is not True or self._attempt(s,person)):
            raise ValueError('social contact unavailable or already attempted today')
        if math.dist(tuple(offer[k] for k in ('x','y','z')),(s.player.x,s.player.y,s.player.z))>3.5:
            raise ValueError('social contact out of reach')
        stamp=now()
        self.m.db.execute('INSERT INTO SocialAttempts VALUES(?,?,?,?,?,?,?,?,?)',
                          (s.world,person,s.day,str(cmd['id']),'intent',str(s.session),s.dimension,stamp,stamp))

    def validate(self,s,cmd,ev):
        request=cmd.get('social',{});person=uid(request.get('person_uuid'));entity_type=request.get('entity_type')
        action=cmd.get('action')
        if (action not in ACTIONS or not person or entity_type not in TYPES or not isinstance(ev,dict)
                or ev.get('server_verified') is not True or uid(ev.get('person_uuid'))!=person
                or ev.get('entity_type')!=entity_type or ev.get('dimension')!=s.dimension):return False
        a,b=ev.get('before'),ev.get('after')
        if not all(valid_snapshot(x,person,entity_type,s.dimension) for x in (a,b)):return False
        target=cmd.get('target',{})
        if target.get('id')!=entity_type:return False
        if action=='social_observe':return a==b
        attempt=self._attempt(s,person)
        if (not attempt or attempt['command_id']!=str(cmd.get('id')) or attempt['status']!='intent'
                or attempt['session']!=str(s.session) or attempt['dimension']!=s.dimension
                or not entity_type.startswith('mca:') or ev.get('mca_version')!=MCA_VERSION
                or ev.get('interaction_accepted') is not True):return False
        gui=ev.get('gui')
        return (isinstance(gui,dict) and gui.get('observed') is True and gui.get('screen_class')==SCREEN
                and uid(gui.get('person_uuid'))==person and a['player_uuid']==b['player_uuid']
                and a.get('interacting_player') is None and uid(b.get('interacting_player'))==uid(b['player_uuid'])
                and all(x[k]=='minecraft:air' for x in (a,b) for k in ('main_hand','off_hand'))
                and a['inventory']==b['inventory'] and a['inventory_fingerprint']==b['inventory_fingerprint'])

    def accept(self,s,cmd,ev,event_id):
        if not self.validate(s,cmd,ev):raise ValueError('invalid social evidence')
        events=self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND session=? AND verified=1',
                           (event_id,s.world,str(s.session)))
        expected='person_observed' if cmd['action']=='social_observe' else 'social_contact'
        if (not events or events[0]['type']!=expected or events[0]['dedup']!=str(cmd['id'])
                or json.loads(events[0]['evidence'])!=ev):raise ValueError('social event provenance unavailable')
        person=uid(cmd['social']['person_uuid']);snap=ev['after'];row=self._person(s,person)
        days=set(json.loads(row['observed_days']) if row else []);days.add(s.day)
        stamp=now()
        self.m.db.execute('INSERT INTO SocialPeople VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                          'ON CONFLICT(world,person_uuid) DO UPDATE SET entity_type=excluded.entity_type,name=excluded.name,'
                          'dimension=excluded.dimension,last_position=excluded.last_position,last_day=excluded.last_day,'
                          'observed_days=excluded.observed_days,last_event=excluded.last_event,last_session=excluded.last_session,'
                          'last_seq=excluded.last_seq,updated=excluded.updated',
                          (s.world,person,snap['entity_type'],snap['name'],s.dimension,json.dumps(snap['position']),
                           row['first_day'] if row else s.day,s.day,json.dumps(sorted(days)),event_id,'unknown',
                           str(s.session),s.seq,stamp))
        self.m.db.execute('INSERT INTO SocialEncounters VALUES(?,?,?,?,?,?,?,?)',
                          (event_id,s.world,person,s.day,cmd['action'],str(cmd['id']),json.dumps(snap),stamp))
        if cmd['action']=='social_contact':
            self.m.db.execute("UPDATE SocialAttempts SET status='confirmed',updated=? WHERE command_id=?",(stamp,str(cmd['id'])))

    def interrupt(self,s,cmd):
        if cmd.get('action')!='social_contact':return
        person=uid(cmd.get('social',{}).get('person_uuid'))
        changed=self.m.db.execute("UPDATE SocialAttempts SET status='uncertain',updated=? WHERE world=? AND person_uuid=? "
                          "AND command_id=? AND status='intent'",(now(),s.world,person,str(cmd['id'])))
        if changed.rowcount:
            self.m.db.execute('UPDATE SocialPeople SET last_session=NULL WHERE world=? AND person_uuid=?',(s.world,person))
