"""Synthetic provenance and bounded recall fixtures, never gameplay evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from agent.autobiography import Autobiography
from agent.chapters import ChapterIndex, SCHEMA, contexts, digest
from agent.memory import MemoryManager

WORLD='a'*64
OTHER='b'*64
DIM='minecraft:overworld'
POS=dict(x=10,y=64,z=2)


class ChaptersTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.m=MemoryManager(Path(self.tmp.name)/'memory.sqlite3')
        self.m.db.executescript(SCHEMA)
        self.auto=Autobiography(self.m);self.index=ChapterIndex(self.m)
        self.serial=0

    def tearDown(self):
        self.m.close();self.tmp.cleanup()

    def event(self,kind='crafted',text='Fabriquei um item observado.',day=1,world=WORLD,verified=True,ev=None,record=True,importance=.6,theme='creation'):
        self.serial+=1
        eid=self.m.event(world,'fixture-session',day,kind,text,verified,ev or {},str(self.serial))
        if record:self.auto.record(world,eid,theme,importance,.5,{})
        return eid

    def chapter(self,eid):
        return self.m.rows('SELECT * FROM MemoryChapters WHERE world=? AND anchor_event=?',(WORLD,eid))[0]

    def test_same_day_distinct_milestones_have_distinct_chapters(self):
        ids=[self.event(kind,text='Resultado '+kind) for kind in ('shelter_completed','crafted','cooked','region_reached')]
        result=self.auto.chapters(WORLD)
        self.assertEqual(len(result),4)
        self.assertEqual({c['anchor_event'] for c in result},set(ids))
        self.assertEqual(len({c['id'] for c in result}),4)
        self.assertTrue(all(c['first_day']==c['last_day']==1 for c in result))
        self.assertTrue(all('primeiro' not in c['title'].lower() and 'seguro' not in c['title'].lower() for c in result))

    def test_exact_descriptions_bounded_context_and_world_isolation(self):
        self.event('observed','Outro mundo.',world=OTHER,ev=dict(project='p'))
        self.event('observed','Projeto diferente.',ev=dict(project='q'))
        for n in range(12):self.event('observed','Episodio confirmado '+str(n),ev=dict(project='p'))
        anchor=self.event('shelter_completed','Verifiquei este abrigo.',ev=dict(project='p'))
        row=self.chapter(anchor);self.assertTrue(self.index.validate(row))
        result=json.loads(row['payload'])
        self.assertEqual(result['episodes'],8)
        self.assertEqual(len(result['highlights']),8)
        self.assertNotIn('Outro mundo.',str(result));self.assertNotIn('Projeto diferente.',str(result))
        for entry in result['highlights']:
            source=self.m.rows('SELECT description FROM Events WHERE id=?',(entry['id'],))[0]
            self.assertEqual(entry['description'],source['description'])

    def test_proposals_questions_and_unverified_events_never_become_chapters(self):
        for kind in ('question','goal','philosophy','cognitive_plan','social_contact_suggestion'):
            self.event(kind,'Construí uma cidade por sugestao.',ev=dict(project='p'))
        self.event('cooked','Preparo sem verificacao.',verified=False)
        self.assertEqual(self.auto.chapters(WORLD),[])
        self.assertFalse(self.m.rows('SELECT * FROM MemoryContextIndex'))

    def test_tampered_payload_manifest_and_renderer_are_rejected(self):
        eid=self.event(ev=dict(project='p'));row=self.chapter(eid)
        self.assertTrue(self.index.validate(row))
        for field,value in (('payload','{}'),('manifest','[]'),('renderer',99),('manifest_hash','bad'),('world',OTHER),('anchor_event','missing')):
            bad=dict(row);bad[field]=value;self.assertFalse(self.index.validate(bad),field)
        bad=dict(row);payload=json.loads(row['payload']);payload['title']='Meu primeiro abrigo seguro'
        bad['payload']=json.dumps(payload);self.assertFalse(self.index.validate(bad))

    def test_mutated_source_is_not_presented_by_chapter_or_recall(self):
        eid=self.event(ev=dict(project='p'))
        self.m.db.execute('UPDATE Events SET evidence=? WHERE id=?',(json.dumps(dict(project='forged')),eid))
        self.assertFalse(self.index.validate(self.chapter(eid)))
        self.assertEqual(self.auto.chapters(WORLD),[])
        self.assertEqual(self.auto.recall(WORLD,'fabriquei',context=dict(project='p')),[])
        original=self.chapter(eid)
        self.assertFalse(self.index.index_event(WORLD,eid))
        self.auto.backfill(WORLD)
        self.assertEqual(self.chapter(eid),original)
        self.assertFalse(self.index.validate(original))

    def test_hash_recomputed_for_unrelated_source_still_fails_context_proof(self):
        anchor=self.event(ev=dict(project='p'));foreign=self.event('observed','Sem vinculo.',ev=dict(project='q'))
        row=self.chapter(anchor);bad=dict(row);manifest=json.loads(row['manifest'])
        manifest['event_ids'].append(foreign);manifest['event_hashes'][foreign]='arbitrary'
        bad['manifest']=json.dumps(manifest);bad['manifest_hash']=digest(manifest)
        self.assertFalse(self.index.validate(bad))

    def test_old_project_memory_beyond_200_recent_events_is_indexed_and_recalled(self):
        old=self.event('observed','Retornei ao projeto observado.',day=1,ev=dict(project='ancient'),importance=.05,theme='place')
        for n in range(215):
            self.event('observed','Inspecionei material comum '+str(n),day=n+2,ev=dict(project='new'),importance=.99,theme='resources')
        result=self.auto.recall(WORLD,'retornar',12,context=dict(project='ancient'))
        self.assertEqual(result[0]['source_event'],old)
        self.assertLessEqual(len(result),12)
        self.assertIn('summary',result[0]);self.assertIn('created',result[0]);self.assertIn('relevance',result[0])
        self.assertEqual(self.auto.recall(OTHER,'retornar',context=dict(project='ancient')),[])

    def test_context_place_and_person_uuid_are_taken_from_evidence_only(self):
        person=str(uuid4())
        place=self.event('observed','Inspecionei um lugar.',ev=dict(dimension=DIM,station=POS))
        # Explicit person_uuid is supported for verified producers; an item entity UUID is unrelated.
        item=self.event('collected','Recolhi um item.',ev=dict(entity_id=person))
        social=self.event('person_observed','Observei uma pessoa identificada.',ev=dict(person_uuid=person))
        self.assertEqual(self.auto.recall(WORLD,'',context=dict(person_uuid=person))[0]['source_event'],social)
        result=self.auto.recall(WORLD,'',context=dict(place=POS,dimension=DIM))
        self.assertEqual([r['source_event'] for r in result],[place])
        keys=self.m.rows('SELECT * FROM MemoryContextIndex WHERE source_event=? AND kind=?',(item,'person'))
        self.assertEqual(keys,[])
        rows=self.m.rows('SELECT * FROM Events WHERE id=?',(item,))
        self.assertNotIn(('person',person),contexts(rows[0]))

    def test_caller_context_cannot_invent_project_or_person_identity(self):
        eid=self.event('observed','Observei material.',ev={})
        self.auto.record(WORLD,eid,'second-theme',.9,.9,dict(project='invented',person_uuid=str(uuid4())))
        self.assertEqual(self.auto.recall(WORLD,'',context=dict(project='invented')),[])
        self.assertFalse(self.m.rows("SELECT * FROM MemoryContextIndex WHERE kind='project'"))

    def test_recall_deduplicates_same_event_across_themes(self):
        eid=self.event('cooked','Preparei alimento observado.',theme='survival')
        self.auto.record(WORLD,eid,'engineering',.8,.8,{})
        result=self.auto.recall(WORLD,'alimento preparo',12)
        self.assertEqual([r['source_event'] for r in result],[eid])

    def test_recall_has_fixed_candidate_budget_and_does_not_backfill(self):
        self.event('observed','Registro de projeto.',ev=dict(project='p'))
        calls=[];original=self.m.rows
        def rows(sql,args=()):
            if 'SELECT DISTINCT lm.*' in sql:calls.append(args[-1] if sql.rstrip().endswith('LIMIT ?') else 30)
            return original(sql,args)
        self.m.rows=rows
        before=self.m.db.total_changes
        self.auto.recall(WORLD,'projeto',99,context=dict(project='p'))
        self.assertLessEqual(sum(calls),200)
        self.assertEqual(self.m.db.total_changes,before)
        self.assertEqual(self.m.rows('SELECT * FROM MemoryIndexProgress'),[])

    def test_backfill_is_explicit_bounded_and_idempotent(self):
        for n in range(130):self.event('observed','Historico '+str(n),record=False)
        self.assertEqual(self.auto.backfill(WORLD,10000),128)
        first=self.m.rows('SELECT * FROM MemoryContextIndex')
        self.assertTrue(first)
        self.assertEqual(self.auto.backfill(WORLD,128),2)
        self.assertEqual(self.auto.backfill(WORLD),0)
        count=len(self.m.rows('SELECT * FROM MemoryContextIndex'))
        self.assertEqual(self.auto.backfill(WORLD),0)
        self.assertEqual(len(self.m.rows('SELECT * FROM MemoryContextIndex')),count)

    def test_read_only_legacy_anchor_fallback_and_chapter_limit(self):
        for n in range(45):self.event('cooked','Preparo '+str(n),record=False)
        before=self.m.db.total_changes
        result=self.auto.chapters(WORLD)
        self.assertEqual(len(result),40)
        self.assertEqual(self.m.db.total_changes,before)
        self.assertTrue(all(len(c['highlights'])==1 for c in result))
        self.assertFalse(self.m.rows('SELECT * FROM MemoryIndexProgress'))

    def test_chapters_do_not_mutate_immutable_journals(self):
        self.m.db.execute('INSERT INTO JournalEntries VALUES(?,?,?,?,?,?,?,?)',
                          ('journal',WORLD,1,'daily','fixture','Texto historico imutavel.','[]','past'))
        self.m.db.execute('INSERT INTO JournalProvenance VALUES(?,?,?,?,?)',('journal',3,'{}','original-hash','text-hash'))
        before=(self.m.rows('SELECT * FROM JournalEntries'),self.m.rows('SELECT * FROM JournalProvenance'))
        self.event('cooked','Preparo observado.',ev=dict(project='p'))
        self.auto.backfill(WORLD);self.auto.chapters(WORLD);self.auto.recall(WORLD,'preparo')
        after=(self.m.rows('SELECT * FROM JournalEntries'),self.m.rows('SELECT * FROM JournalProvenance'))
        self.assertEqual(before,after)

    def test_forty_full_chapters_use_at_most_two_queries(self):
        for n in range(40):
            for episode in range(7):
                self.event('observed','Episodio '+str(episode),ev=dict(project='p'+str(n)))
            self.event('crafted','Marco '+str(n),ev=dict(project='p'+str(n)))
        calls=[];original=self.m.rows
        def rows(sql,args=()):
            calls.append((sql,args));return original(sql,args)
        self.m.rows=rows
        result=self.auto.chapters(WORLD)
        self.assertEqual(len(result),40)
        self.assertTrue(all(len(c['highlights'])==8 for c in result))
        self.assertLessEqual(len(calls),2)
        self.assertLessEqual(len(calls[1][1])-1,360)

    def test_deleted_chapter_cannot_bypass_changed_source_sentinel(self):
        eid=self.event('cooked','Preparo original.',ev=dict(project='p'))
        self.m.db.execute('DELETE FROM MemoryChapters WHERE anchor_event=?',(eid,))
        self.m.db.execute('UPDATE Events SET description=? WHERE id=?',('Preparo adulterado.',eid))
        self.assertEqual(self.auto.chapters(WORLD),[])

    def test_contact_chapter_follows_same_person_uuid_across_name_or_place_changes(self):
        person,other=str(uuid4()),str(uuid4())
        first=self.event('person_observed','Observei Ana.',ev=dict(person_uuid=person,entity_type='mca:female_villager',dimension=DIM,position=POS))
        self.event('person_observed','Observei outro NPC no mesmo lugar.',ev=dict(person_uuid=other,entity_type='mca:male_villager',dimension=DIM,position=POS))
        contact=self.event('social_contact','Abri a interface nativa para contato.',ev=dict(person_uuid=person,
                           entity_type='mca:female_villager',dimension=DIM,position=POS,server_verified=True))
        payload=json.loads(self.chapter(contact)['payload'])
        self.assertEqual(payload['title'],'Contato com pessoa observada')
        self.assertEqual({e['id'] for e in payload['highlights']},{first,contact})
        self.assertTrue(self.index.validate(self.chapter(contact)))
        later=self.event('person_observed','Observei o mesmo UUID com nome novo.',day=2,ev=dict(person_uuid=person,
                         entity_type='mca:female_villager',dimension=DIM,position=dict(x=20,y=64,z=3)))
        result=self.auto.recall(WORLD,'',12,context=dict(person_uuid=person))
        self.assertEqual({r['source_event'] for r in result},{first,contact,later})

    def test_validate_optional_cache_never_queries_database(self):
        eid=self.event('crafted','Marco verificado.',ev=dict(project='p'))
        row=self.chapter(eid);event=self.m.rows('SELECT * FROM Events WHERE id=?',(eid,))[0]
        def forbidden(*args,**kwargs):raise AssertionError('cache validation must be query-free')
        self.m.rows=forbidden
        self.assertTrue(self.index.validate(row,{eid:event}))


if __name__=='__main__':unittest.main()
