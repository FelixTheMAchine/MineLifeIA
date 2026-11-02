"""Production provider/parser/planner over synthetic HTTP and game evidence, never gameplay."""
import asyncio
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

import httpx

from agent.cognitive_scheduler import CognitiveScheduler
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.main import create_app
from agent.memory import MemoryManager
from agent.mind import scope
from agent.protocol import Step


class IdleProbe:
    def snapshot(self):
        return dict(status='fixture',free_ram_mb=4096,cpu_percent=10)


class MindIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.m=MemoryManager(self.root/'memory.sqlite3')
        self.writer=JournalWriter(self.m,self.root/'journals')
        self.engine=CognitiveEngine(self.m,self.writer)
        self.session=str(uuid4());self.world='a'*64;self.seq=0;self.schedulers=[]

    async def asyncTearDown(self):
        for scheduler in self.schedulers:await scheduler.close()
        self.m.close();self.tmp.cleanup()

    def payload(self,**changes):
        self.seq+=1
        data=dict(protocol=1,world=self.world,session=self.session,dimension='minecraft:overworld',
                  seq=self.seq,control_epoch=1,day=1,time=1000,active=True,armed=True,
                  player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={}),
                  blocks=[],results=[],capabilities=['craft','explore','observe','approach'])
        data.update(changes)
        return Step(**data)

    def experience(self):
        recipe=dict(id='minecraft:oak_planks',input_id='minecraft:oak_log',input_count=1,output_id='minecraft:oak_planks',output_count=4)
        s=self.payload(recipes=[recipe],player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:oak_log':1}))
        cmd=self.engine.step(s)['command'];self.assertEqual(cmd['action'],'craft')
        ev=dict(target={k:cmd['target'][k] for k in ('x','y','z')},server_verified=True,recipe=recipe['id'],
                crafted_delta=4,inventory_before={'minecraft:oak_log':1},inventory_after={'minecraft:oak_planks':4})
        self.engine.step(self.payload(results=[dict(id=cmd['id'],status='success',reason='synthetic_fixture',evidence=ev)]))
        eid=self.m.rows("SELECT id FROM Events WHERE type='crafted'")[0]['id']
        self.engine.goals.ensure(self.engine.latest,'explore:minecraft:overworld:(1, 4, 0)',
            'Explorar uma região ainda não visitada','Fronteira sintética observada',78,'explore',
            dict(target=dict(x=9,y=64,z=0,id='minecraft:air')),'explore_region')
        return eid

    async def infer(self,eid,mutate=None):
        output=dict(version=1,thoughts=[dict(category='REFLECTION',text='Talvez explorar amplie as possibilidades desses materiais.',
                    evidence_ids=[eid],memory_ids=[],uncertainty=.65)],proposal=dict(intent='explore_regions',
                    preferred_subject=None,motivation='Relacionar fabricação e lugares observados',evidence_ids=[eid],
                    constraints=['safe_only','preserve_resources','require_capability'],priority=1.,ttl_seconds=120),reconsiderations=[])
        if mutate:mutate(output)
        def response(request):
            if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'fixture'}]})
            if request.url.path=='/api/chat':
                self.assertIsInstance(json.loads(request.content)['format'],dict)
                return httpx.Response(200,json={'model':'fixture','message':{'content':json.dumps(output)}})
            return httpx.Response(200,json={})
        scheduler=CognitiveScheduler({'provider':'ollama','model':'fixture','max_retries':0},httpx.MockTransport(response),probe=IdleProbe())
        self.schedulers.append(scheduler);scheduler.bind_scope(scope(self.engine.latest))
        self.engine.mind.set_epoch(scheduler.generation,scheduler.runtime_id)
        context=self.engine.mind_context.build(self.engine.latest,self.engine.goals.rows(self.world),{},[],generation=scheduler.generation)
        self.assertIn(eid,context['source_event_ids'])
        scheduler.schedule(context);await scheduler.task
        return scheduler.take_result()

    def opportunities(self):
        return self.payload(blocks=[dict(x=2,y=64,z=0,id='minecraft:stone',log=False)],
                            frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)])

    async def test_native_provider_schema_to_real_planner_and_correlated_outcome(self):
        eid=self.experience();envelope=await self.infer(eid)
        self.assertIsNotNone(envelope)
        path=self.root/'baseline.sqlite3'
        self.m.db.commit()
        with closing(sqlite3.connect(path)) as destination:self.m.db.backup(destination)
        baseline=MemoryManager(path)
        try:
            engine=CognitiveEngine(baseline,JournalWriter(baseline,self.root/'baseline-journals'))
            self.assertEqual(engine.step(self.opportunities())['command']['action'],'approach')
        finally:baseline.close()
        before=self.m.rows('SELECT * FROM Events')
        self.engine.record_advice(envelope)
        self.assertEqual(before,self.m.rows('SELECT * FROM Events'))
        self.assertTrue(self.m.rows('SELECT * FROM MindBindings'))
        self.engine.last_plan[self.world]=-1e30
        cmd=self.engine.step(self.opportunities())['command']
        self.assertEqual(cmd['action'],'explore')
        self.assertTrue(self.m.rows("SELECT * FROM MindEvaluations WHERE kind='selection'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='region_reached'"))
        proof=dict(target={k:cmd['target'][k] for k in ('x','y','z')},server_verified=True,
                   position=dict(x=9.5,y=64,z=.5),dimension='minecraft:overworld')
        self.engine.step(self.payload(results=[dict(id=cmd['id'],status='success',reason='synthetic_fixture',evidence=proof)]))
        self.assertEqual(len(self.m.rows("SELECT * FROM MindEvaluations WHERE kind='outcome' AND outcome='confirmed'")),1)
        self.assertTrue(all(self.writer.validate_entry(e) for e in self.m.rows('SELECT * FROM JournalEntries')))

    async def test_model_cannot_invent_evidence_or_executable_actions(self):
        eid=self.experience()
        for change in (lambda o:o['proposal'].update(intent='teleport'),
                       lambda o:o['proposal'].update(evidence_ids=['invented']),
                       lambda o:o.update(command={'action':'give'})):
            self.assertIsNone(await self.infer(eid,change))
        self.assertFalse(self.m.rows('SELECT * FROM MindBindings'))

    async def test_stale_pause_restart_and_source_changes_cannot_influence(self):
        eid=self.experience();env=await self.infer(eid)
        paused=self.engine.latest.model_copy(update={'active':False})
        self.engine.latest=paused;self.engine.record_advice(env)
        self.assertFalse(self.m.rows('SELECT * FROM MindBindings'))
        self.engine.latest=paused.model_copy(update={'active':True});self.engine.record_advice(env)
        self.assertTrue(self.m.rows('SELECT * FROM MindBindings'))
        self.assertGreater(self.engine.mind.bonus(self.engine.latest,'explore',{},'any'),0)
        self.m.db.execute('UPDATE Events SET evidence=? WHERE id=?',('{"changed":true}',eid))
        self.assertEqual(self.engine.mind.bonus(self.engine.latest,'explore',{},'any'),0)
        restarted=CognitiveEngine(self.m,self.writer);restarted.latest=self.engine.latest
        self.assertEqual(restarted.mind.bonus(restarted.latest,'explore',{},'any'),0)
        self.assertEqual(restarted.language.bonus(self.world,'explore',{},'any'),0)

    async def test_slow_model_does_not_block_bridge_health_or_stop(self):
        app=create_app(self.root/'app',dict(token='fixture-token-which-is-at-least-32-characters',llm={'provider':'ollama','model':'fixture','max_retries':0}))
        advisor=app.state.advisor;engine=app.state.engine
        started,release=asyncio.Event(),asyncio.Event()
        async def respond(request):
            if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'fixture'}]})
            if request.url.path=='/api/chat':
                started.set();await release.wait()
                return httpx.Response(200,json={'message':{'content':json.dumps(dict(version=1,thoughts=[dict(category='QUESTION',text='O que mudou?',evidence_ids=[],memory_ids=[],uncertainty=1.)],proposal=None,reconsiderations=[]))}})
            return httpx.Response(200,json={})
        advisor._scheduler.provider.transport=httpx.MockTransport(respond);advisor._scheduler.probe=IdleProbe()
        engine.m.event(self.world,self.session,1,'observed','Fixture para controle assíncrono.',True,{'fixture':True},'async-fixture')
        headers={'Authorization':'Bearer fixture-token-which-is-at-least-32-characters'}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765',headers=headers) as client:
                first=await client.post('/bridge/step',json=self.payload().model_dump(mode='json'))
                self.assertEqual(first.status_code,200)
                await asyncio.wait_for(started.wait(),1)
                self.assertEqual((await asyncio.wait_for(client.get('/health'),.5)).status_code,200)
                self.assertEqual((await asyncio.wait_for(client.post('/bridge/step',json=self.payload().model_dump(mode='json')),.5)).status_code,200)
                self.assertEqual((await asyncio.wait_for(client.post('/api/control/stop'),.5)).status_code,200)
                release.set();await advisor.task
                self.assertIsNone(advisor.take_result())
                self.assertFalse(engine.m.rows('SELECT * FROM MindThoughts'))
        finally:
            release.set();await advisor.close();engine.m.close()
