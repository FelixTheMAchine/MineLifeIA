"""Bounded context, structured language proposals and evidence-backed narrative composition.

Free prose remains an unverified draft. A model can select facts, questions and executable
interests; it cannot certify its own prose or send a physical command.
"""
import hashlib
import json
import time
from agent.memory import now

INTENTS={
    'meet_people':('observe_person','contact_person'),
    'explore_regions':('explore_region',), 'study_material':('observe_block','mine_resource'),
    'prepare_food':('eat_food','furnace_load','harvest_crop','plant_crop'), 'make_tools':('craft_table',),
    'smelt_resources':('furnace_load',), 'build_refuge':('build_shelter',),
}
EVENT_DOMAINS={
    'person_observed':{'social','place','knowledge'}, 'social_contact':{'social','place'},
    'collected':{'resources','knowledge'}, 'resource_mined':{'resources','tools','engineering'},
    'crafted':{'creation','tools','engineering'}, 'placed':{'place','creation','engineering'},
    'cooked':{'preparation','survival','engineering'}, 'ate':{'survival','preparation'},
    'crop_harvested':{'agriculture','survival','resources'}, 'slept':{'survival','safety','time'},
    'planted':{'agriculture','preparation','creation'},
    'shelter_completed':{'home','creation','safety','place'}, 'shelter_entered':{'home','safety','survival'},
    'shelter_left':{'home','place','exploration'}, 'region_reached':{'place','exploration','knowledge'},
    'attempt_failed':{'adaptation','uncertainty'}, 'observed':{'knowledge','uncertainty'},
}
MEANINGS={
    'social':('social','pessoa','person','npc','habitante','encontro','contato'),
    'home':('lar','abrigo','refug','casa','shelter','belong'),
    'survival':('fome','alimento','sobreviv','comida','food','survival','meal'),
    'engineering':('ferrament','fornalha','minera','metal','mecan','engenh','furnace','pickaxe','tool'),
    'exploration':('explor','viajar','regi','fronteira','viagem','bioma','frontier'),
    'place':('lugar','retorno','voltar','local','place','base'),
    'knowledge':('conhec','aprend','descobr','investig','knowledge'),
    'creation':('constru','criar','fabric','projeto','creation','craft'),
    'safety':('prud','segur','proteg','noite','safety'),
    'adaptation':('falha','erro','alternativ','fracass','failure'),
    'agriculture':('plant','cultiv','semente','farm','seed'),
}


def concepts(text,event_type=None):
    text=text.casefold()
    return set(EVENT_DOMAINS.get(event_type,()))|{concept for concept,terms in MEANINGS.items() if any(term in text for term in terms)}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


class CognitiveLanguageEngine:
    def __init__(self,memory,autobiography,skills):
        self.m,self.autobiography,self.skills=memory,autobiography,skills
        self.last_context=None
        # Persisted narrative proposals require fresh validation in this runtime.
        self.accepted_in_runtime=set()

    def context(self,s,goals,personality,interests):
        available=[dict(subject=g['subject'],description=g['description'],skill=g['skill']) for g in goals if g['status'] in ('pending','running')][:8]
        recent=self.m.rows("SELECT id,type,day,description FROM Events WHERE world=? AND verified=1 AND type NOT IN "
                           "('goal','question','interest','furnace_inspected','construction_step','shelter_inspected') ORDER BY timestamp DESC LIMIT 6",(s.world,))
        cue=' '.join(g['description'] for g in available)+' '+' '.join(e['type']+' '+e['description'] for e in recent[:2])
        recalled=self.autobiography.recall(s.world,cue,3)
        facts={e['id']:e for e in recent}
        for e in recalled:facts.setdefault(e['source_event'],dict(id=e['source_event'],type=e['type'],day=e['day'],description=e['description']))
        # Do not truncate JSON mid-string: discard lower-ranked records until the payload fits.
        facts=list(facts.values())[:9]
        knowledge=self.m.rows("SELECT subject,status,evidence_ids FROM Knowledge WHERE world=? AND status='confirmed' ORDER BY rowid DESC LIMIT 12",(s.world,))
        for k in knowledge:k['evidence_ids']=json.loads(k['evidence_ids'])[-3:]
        context=dict(world=s.world,day=s.day,observation=dict(health=s.player.health,food=s.player.food,biome=s.biome,
                     inventory=dict(list(s.player.inventory.items())[:20]),blocks=[b.id for b in s.blocks[:12]]),
                     goals=available,personality=personality,
                     interests=[{k:r[k] for k in ('topic','intensity','positive','negative') if k in r} for r in interests[:8]],facts=facts,
                     knowledge=knowledge,
                     hypotheses=self.m.rows("SELECT question,statement,status FROM Hypotheses WHERE world=? AND status='hypothesis' ORDER BY rowid DESC LIMIT 4",(s.world,)),
                     recalled_memories=[dict(event_id=r['source_event'],day=r['day'],theme=r['theme'],relevance=r['relevance']) for r in recalled],
                     intents={key:dict(skills=list(value),executable=any(self.skills.available(v,s.capabilities) for v in value)) for key,value in INTENTS.items()},
                     interpretations=self.m.rows('SELECT theme,question,interpretation,origin_event FROM PhilosophicalQuestions WHERE world=? ORDER BY created DESC LIMIT 3',(s.world,)))
        for field in ('knowledge','hypotheses','interpretations','recalled_memories','goals','facts'):
            while len(json.dumps(context,ensure_ascii=False))>9300 and context[field]:context[field].pop()
        context['source_event_ids']=[e['id'] for e in facts]
        context['context_id']=digest(context)
        self.last_context=context
        return context

    def accept(self,s,value):
        proposal=value.get('proposal')
        if not isinstance(proposal,dict) or set(proposal)-{'intent','evidence_ids'} or value.get('world')!=s.world:return None
        intent=proposal.get('intent')
        if intent not in INTENTS:return None
        sources=proposal.get('evidence_ids')
        offered=set(value.get('source_event_ids',[]))
        if not isinstance(sources,list) or not 1<=len(sources)<=8 or not all(isinstance(e,str) and e in offered for e in sources):return None
        facts=[]
        for eid in dict.fromkeys(sources):
            rows=self.m.rows('SELECT id,type,day,description FROM Events WHERE id=? AND world=? AND verified=1',(eid,s.world))
            if not rows:return None
            facts+=rows
        preferred=value.get('preferred_subject')
        if preferred and not self.m.rows('SELECT 1 FROM GoalPlans WHERE world=? AND subject=?',(s.world,preferred)):preferred=None
        fields={k:str(value.get(k,''))[:1800] for k in ('question','hypothesis','interpretation','reflection','journal_draft')}
        identity=dict(world=s.world,intent=intent,subject=preferred,sources=sources,fields=fields,context=value.get('context_id'))
        key=digest(identity)
        if self.m.rows('SELECT id FROM CognitivePlans WHERE id=?',(key,)):
            self.accepted_in_runtime.add(key)
            return key
        executable=any(self.skills.available(skill,s.capabilities) for skill in INTENTS[intent])
        previous=self.m.rows('SELECT id FROM CognitivePlans WHERE world=? AND intent=? ORDER BY created DESC,rowid DESC LIMIT 1',(s.world,intent))
        claims=value.get('claims',[]);authorized={e['id']:e['description'] for e in facts}
        # A structured factual claim is accepted only as an exact authorized statement or a reference.
        valid_claims=isinstance(claims,list) and 0<len(claims)<=9 and all(isinstance(c,dict) and set(c)<={'event_id','text'}
              and c.get('event_id') in authorized and ('text' not in c or c['text']==authorized[c['event_id']]) for c in claims)
        selected=list(dict.fromkeys(c['event_id'] for c in claims)) if valid_claims else []
        self.m.db.execute('INSERT INTO CognitivePlans VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (key,s.world,s.day,value.get('purpose','integrated'),intent,preferred,json.dumps(fields,ensure_ascii=False),
                           json.dumps(sources),json.dumps(selected),digest(facts),'actionable_proposal' if executable else 'blocked_skill',
                           previous[0]['id'] if previous else None,now(),time.time()+600,'claims_verified' if valid_claims else 'claims_rejected'))
        self.m.db.execute('INSERT INTO NarrativeDrafts VALUES(?,?,?,?,?,?,?,?)',
                          (key,s.world,s.day,fields['journal_draft'],json.dumps(claims,ensure_ascii=False),'unverified_prose',json.dumps(sources),now()))
        # No text from the LLM is inserted into factual Events, Knowledge or verified interpretations.
        self.accepted_in_runtime.add(key)
        return key

    @staticmethod
    def intent_for(kind,params):
        if kind in ('social_observe','social_contact'):return 'meet_people'
        output=params.get('recipe',{}).get('output_id','')
        if kind=='explore':return 'explore_regions'
        if kind in ('mine','observe'):return 'study_material'
        if kind in ('eat','harvest','plant') or output in ('minecraft:bread',):return 'prepare_food'
        if kind.startswith('furnace_') or output=='minecraft:furnace' or params.get('placement',{}).get('item_id')=='minecraft:furnace':return 'smelt_resources'
        if kind.endswith('_shelter'):return 'build_refuge'
        return 'make_tools'

    def bonus(self,world,kind,params,subject):
        intent=self.intent_for(kind,params)
        rows=self.m.rows("SELECT id,intent,preferred_subject FROM CognitivePlans WHERE world=? AND status='actionable_proposal' AND expires>? "
                         "AND NOT EXISTS (SELECT 1 FROM MindBindings b WHERE b.plan_id=CognitivePlans.id) "
                         "ORDER BY created DESC,rowid DESC LIMIT 4",(world,time.time()))
        rows=[p for p in rows if p['id'] in self.accepted_in_runtime]
        return max((24 if p['preferred_subject']==subject else 16 if p['intent']==intent else 0 for p in rows),default=0)
