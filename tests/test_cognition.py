"""Cognitive proposals and provenance fixtures; no external model or gameplay is asserted."""
import copy
import json
import unittest
import time
import test_pipeline as base
from agent.protocol import Step
from agent.engine import CognitiveEngine


class CognitionTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step

    def event(self,kind='slept',text='Usei uma cama observada, com passagem para o dia verificada.',day=1,world=None,verified=True):
        return self.m.event(world or base.WORLD,self.session,day,kind,text,verified,{'fixture':True},kind+':'+str(day)+':'+text)

    def proposal(self,eid,**overrides):
        value=dict(world=base.WORLD,purpose='philosophy',preferred_subject=None,question='Como preparo e viagem mudam minhas escolhas?',
                   hypothesis='Preparar recursos pode ampliar opções futuras.',interpretation='Uma ideia provisória.',journal_draft='Texto livre continua não verificado.',
                   proposal=dict(intent='explore_regions',evidence_ids=[eid]),source_event_ids=[eid],claims=[dict(event_id=eid)])
        value.update(overrides);return value

    def ready(self):
        self.step(blocks=[],active=False,capabilities=['observe','approach','explore'])

    def test_valid_language_intent_changes_real_goal_selection(self):
        self.ready();eid=self.event()
        self.engine.record_advice(self.proposal(eid))
        self.engine.last_plan[base.WORLD]=-1e30
        result=self.step(blocks=[dict(x=2,y=64,z=0,id='minecraft:stone',log=False)],
                         frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)],capabilities=['observe','approach','explore'])
        self.assertEqual(result['command']['action'],'explore')
        self.assertFalse(self.m.rows("SELECT * FROM Knowledge WHERE subject LIKE '%viagem%'"))

    def test_proposal_never_bypasses_pause_emergency_or_hunger(self):
        self.ready();eid=self.event();self.engine.record_advice(self.proposal(eid))
        for flags in (dict(active=False),dict(armed=False),dict(control_state='EMERGENCY_STOP'),
                      dict(player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory={}))):
            result=self.step(blocks=[],frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)],capabilities=['explore'],**flags)
            self.assertIsNone(result['command'])

    def test_foreign_missing_evidence_and_physical_instructions_rejected(self):
        self.ready();eid=self.event(world='b'*64)
        self.engine.record_advice(self.proposal(eid));self.assertFalse(self.m.rows('SELECT * FROM CognitivePlans'))
        eid=self.event()
        for plan in (dict(intent='teleport',evidence_ids=[eid]),dict(intent='explore_regions',evidence_ids=['missing']),
                     dict(intent='explore_regions',evidence_ids=[eid],command='give diamonds')):
            self.engine.record_advice(self.proposal(eid,proposal=plan))
        self.assertFalse(self.m.rows('SELECT * FROM CognitivePlans'))

    def test_invented_claim_stays_draft_and_does_not_enter_journal(self):
        self.ready();eid=self.event()
        value=self.proposal(eid,claims=[dict(event_id=eid,text='Casei e construí uma cidade.')],journal_draft='Casei e construí uma cidade.')
        self.engine.record_advice(value)
        self.assertEqual(self.m.rows('SELECT claims_status FROM CognitivePlans')[0]['claims_status'],'claims_rejected')
        self.assertEqual(self.m.rows('SELECT status FROM NarrativeDrafts')[0]['status'],'unverified_prose')
        entry=self.writer.write(base.WORLD,1)
        self.assertNotIn('cidade',entry['text']);self.assertTrue(self.writer.validate_entry(entry))

    def test_exact_fact_references_can_choose_composition_without_free_prose(self):
        self.ready();first=self.event(text='Primeiro registro confirmado.');second=self.event('observed','Segundo registro confirmado.')
        self.engine.record_advice(self.proposal(second,source_event_ids=[first,second],proposal=dict(intent='explore_regions',evidence_ids=[first,second]),
                                               claims=[dict(event_id=second),dict(event_id=first)],journal_draft='Conheci um NPC inexistente.'))
        entry=self.writer.write(base.WORLD,1)
        self.assertLess(entry['text'].index('Segundo registro'),entry['text'].index('Primeiro registro'))
        self.assertNotIn('NPC',entry['text']);self.assertTrue(self.writer.validate_entry(entry))
        saved=entry['text']
        self.engine.record_advice(self.proposal(first,question='Outra pergunta.'))
        self.assertEqual(self.writer.write(base.WORLD,1)['text'],saved)

    def test_semantic_recall_links_different_words_by_episode_type(self):
        eid=self.event('cooked','Transformei tubérculos e retirei o resultado confirmado.',day=2)
        self.engine.autobiography.record(base.WORLD,eid,'preparation',.9,.8,{})
        memories=self.engine.autobiography.recall(base.WORLD,'sobreviver durante uma viagem sem fome')
        self.assertEqual(memories[0]['source_event'],eid)
        self.assertEqual(self.engine.autobiography.recall('b'*64,'fome'),[])

    def test_preferences_are_gradual_deduplicated_reversible_and_world_isolated(self):
        self.ready();eid=self.event('resource_mined','Remoção fixture verificada.')
        self.m.db.execute('UPDATE Events SET evidence=? WHERE id=?',(json.dumps({'before_block':'minecraft:stone'}),eid))
        self.engine.identity.observe(self.engine.latest,eid);self.engine.identity.observe(self.engine.latest,eid)
        before=self.m.rows("SELECT weight FROM Preferences WHERE category='material'")[0]['weight']
        self.assertGreater(before,0);self.assertLess(before,.1)
        failure=self.event('attempt_failed','Tentativa fixture sem sucesso.')
        self.m.db.execute('UPDATE Events SET evidence=? WHERE id=?',(json.dumps({'subject':'minecraft:stone'}),failure))
        self.engine.identity.observe(self.engine.latest,failure)
        after=self.m.rows("SELECT weight FROM Preferences WHERE category='material'")[0]['weight']
        self.assertLess(after,before)
        self.assertEqual(len(self.m.rows("SELECT * FROM PreferenceUpdates WHERE category='material'")),2)
        self.assertEqual(self.engine.identity.bonus('b'*64,'mine',dict(target={'id':'minecraft:stone'})),0)

    def test_context_is_bounded_and_separates_knowledge_interpretations_and_facts(self):
        self.ready();eid=self.event();self.engine.autobiography.record(base.WORLD,eid,'survival',.8,.8,{})
        context=self.engine.language.context(self.engine.latest,[],{},[])
        self.assertIn(eid,context['source_event_ids'])
        self.assertLess(len(json.dumps(context)),14000)
        self.assertNotIn('token',context);self.assertNotIn('evidence',context['facts'][0])
        self.assertIn('knowledge',context);self.assertIn('interpretations',context)

    def test_long_evidence_histories_are_not_copied_into_every_language_call(self):
        self.ready();eid=self.event();history=json.dumps([eid]*1500)
        for index in range(12):
            self.m.db.execute("INSERT INTO Knowledge VALUES(?,?,'confirmed',?)",(base.WORLD,'fixture:'+str(index),history))
        interests=[dict(topic='engineering',intensity=60,evidence_ids=history,origin='fixture')]
        context=self.engine.language.context(self.engine.latest,[],{},interests)
        self.assertLess(len(json.dumps(context,ensure_ascii=False)),10000)
        self.assertIn(eid,context['source_event_ids'])
        self.assertTrue(all(len(row['evidence_ids'])<=3 for row in context['knowledge']))
        self.assertNotIn('evidence_ids',context['interests'][0])
        self.assertTrue(all(row['evidence_ids']==history for row in self.m.rows('SELECT evidence_ids FROM Knowledge')))

    def test_philosophical_proposals_link_revisions_without_becoming_facts(self):
        self.ready();eid=self.event()
        self.engine.record_advice(self.proposal(eid))
        first=self.m.rows('SELECT id FROM CognitivePlans')[0]['id']
        second=self.event('cooked','Preparo posterior fixture.',2)
        self.engine.record_advice(self.proposal(second,question='Depois deste preparo, viajar continua tendo a mesma prioridade?'))
        latest=self.engine.philosophy.proposed_revisions(base.WORLD)[0]
        self.assertEqual(latest['revision_of'],first)
        self.assertEqual(latest['classification'],'narrative_proposal_unverified')
        self.assertFalse(self.m.rows('SELECT * FROM PhilosophicalQuestions'))
        self.assertFalse(self.m.rows('SELECT * FROM Knowledge'))

    def test_blocked_skills_and_expiry_do_not_give_priority(self):
        self.ready();eid=self.event()
        self.engine.record_advice(self.proposal(eid,proposal=dict(intent='build_refuge',evidence_ids=[eid])))
        self.assertEqual(self.m.rows('SELECT status FROM CognitivePlans')[0]['status'],'blocked_skill')
        self.assertEqual(self.engine.language.bonus(base.WORLD,'build_shelter',{},'x'),0)
        self.engine.record_advice(self.proposal(eid))
        self.assertGreater(self.engine.language.bonus(base.WORLD,'explore',{},'x'),0)
        self.m.db.execute('UPDATE CognitivePlans SET expires=?',(time.time()-1,))
        self.assertEqual(self.engine.language.bonus(base.WORLD,'explore',{},'x'),0)

    def test_verified_chapter_index_excludes_invented_episodes(self):
        valid=self.event('cooked','Preparo fixture.',1);self.event('cooked','Preparo inventado.',20,verified=False)
        chapters=self.engine.autobiography.chapters(base.WORLD)
        self.assertEqual(len(chapters),1);self.assertEqual(chapters[0]['highlights'][0]['id'],valid)
