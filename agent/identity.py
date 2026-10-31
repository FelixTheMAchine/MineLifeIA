"""Gradual preferences learned from verified episodes; never an instruction from model prose."""
import json
import math
from agent.memory import now
from agent.cognition import EVENT_DOMAINS, CognitiveLanguageEngine

class IdentityEngine:
    def __init__(self,memory):self.m=memory

    def observe(self,s,eid):
        rows=self.m.rows('SELECT * FROM Events WHERE id=? AND world=? AND verified=1',(eid,s.world))
        if not rows:return
        event=rows[0];kind=event['type'];evidence=json.loads(event['evidence'])
        changes=[('value',domain,1.) for domain in EVENT_DOMAINS.get(kind,()) if domain in ('safety','knowledge','creation','place','exploration','survival','engineering')]
        if kind=='region_reached':changes.append(('biome',s.biome,1.))
        if kind=='resource_mined':changes.append(('material',evidence.get('before_block','unknown'),1.))
        if kind=='attempt_failed':
            subject=evidence.get('subject','');changes=[('material',subject,-1.)] if subject else []
        for category,subject,signal in changes:
            if subject=='unknown':continue
            if self.m.rows('SELECT 1 FROM PreferenceUpdates WHERE world=? AND source=? AND category=? AND subject=?',(s.world,eid,category,subject)):continue
            stored=self.m.rows('SELECT * FROM Preferences WHERE world=? AND category=? AND subject=?',(s.world,category,subject))
            old=stored[0]['weight'] if stored else 0.;sources=json.loads(stored[0]['sources']) if stored else []
            # Diminishing influence of repeated events, gradual change towards a bounded tendency.
            target=.7*signal;rate=.08/math.sqrt(1+len(sources));new=round(old+(target-old)*rate,5)
            sources=(sources+[eid])[-128:]
            reason=f'Experiência {kind}; influência gradual, sem converter interpretação do modelo em fato.'
            self.m.db.execute('INSERT INTO Preferences VALUES(?,?,?,?,?,?) ON CONFLICT(world,category,subject) DO UPDATE SET weight=excluded.weight,sources=excluded.sources,updated=excluded.updated',
                              (s.world,category,subject,new,json.dumps(sources),now()))
            self.m.db.execute('INSERT INTO PreferenceUpdates VALUES(?,?,?,?,?,?,?,?)',(s.world,eid,category,subject,old,new,reason,now()))

    def bonus(self,world,kind,params):
        intent=CognitiveLanguageEngine.intent_for(kind,params)
        value={'explore_regions':'exploration','study_material':'knowledge','make_tools':'engineering','build_refuge':'creation','prepare_food':'survival','smelt_resources':'engineering'}[intent]
        rows=self.m.rows('SELECT category,subject,weight FROM Preferences WHERE world=? AND (category=? OR subject=?)',
                         (world,'value',params.get('target',{}).get('id','')))
        return max(-12,min(12,sum(r['weight']*10 for r in rows if r['subject']==value or r['category']=='material')))
