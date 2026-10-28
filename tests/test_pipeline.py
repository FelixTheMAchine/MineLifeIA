import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from agent.engine import CognitiveEngine
from agent.memory import MemoryManager
from agent.protocol import Step
from agent.main import create_app
from agent.journal.writer import JournalWriter
from agent.journal.github_publisher import GitHubPublisher, validate_content

WORLD = 'a' * 64
TARGET = dict(x=2, y=64, z=0, id='minecraft:oak_log')
POS = {k: TARGET[k] for k in ('x', 'y', 'z')}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.m = MemoryManager(self.root / 'data' / 'memory.sqlite3')
        self.writer = JournalWriter(self.m, self.root / 'journals')
        self.engine = CognitiveEngine(self.m, self.writer)
        self.session = str(uuid4())
        self.seq = 0

    def tearDown(self):
        self.m.close()
        self.tmp.cleanup()

    def step(self, results=None, **overrides):
        self.seq += 1
        payload = dict(protocol=1, session=self.session, world=WORLD, dimension='minecraft:overworld',
                       seq=self.seq, day=1, time=1000, active=True, armed=True,
                       player=dict(x=0, y=64, z=0, health=20, food=20, danger=False, inventory={}),
                       blocks=[dict(**TARGET, log=True)], results=results or [])
        payload.update(overrides)
        return self.engine.step(Step(**payload))

    def success(self, cmd, evidence):
        return dict(id=cmd['id'], status='success', reason='test_fixture', evidence=evidence)

    def break_result(self, command):
        return self.success(command, dict(target=POS, server_verified=True, before_block='minecraft:oak_log',
                                         after_block='minecraft:air', mined_delta=1, inventory_before={}))

    def complete(self):
        approach = self.step()['command']
        breaking = self.step([self.success(approach, dict(target=POS, in_reach=True))])['command']
        collect = self.step([self.break_result(breaking)])['command']
        result = self.success(collect, dict(target=POS, server_verified=True, inventory_after={'minecraft:oak_log': 1}))
        self.step([result])
        return result

    def test_confirmed_only_after_verified_break_and_inventory_increase(self):
        approach = self.step()['command']
        breaking = self.step([self.success(approach, dict(target=POS, in_reach=True))])['command']
        collect = self.step([self.break_result(breaking)])['command']
        self.assertEqual(self.m.rows('SELECT status FROM Knowledge')[0]['status'], 'partial')
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))
        self.step([self.success(collect, dict(target=POS, server_verified=True, inventory_after={'minecraft:oak_log': 2}))])
        self.assertEqual(self.m.rows('SELECT status FROM Knowledge')[0]['status'], 'confirmed')

    def test_client_prediction_without_server_evidence_is_not_learning(self):
        c = self.step()['command']
        b = self.step([self.success(c, dict(target=POS, in_reach=True))])['command']
        forged = self.break_result(b)
        forged['evidence']['server_verified'] = False
        self.step([forged])
        self.assertFalse(self.m.rows("SELECT * FROM Knowledge WHERE status='confirmed'"))
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='block_removed'"))

    def test_wrong_target_and_unissued_results_are_rejected(self):
        self.step([dict(id=str(uuid4()), status='success', reason='fake', evidence={})])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='collected'"))
        pending = json.loads(self.m.rows('SELECT payload FROM Commands')[0]['payload'])
        self.step([self.success(pending, dict(target=dict(x=999, y=64, z=0), in_reach=True))])
        self.assertEqual(self.m.rows('SELECT status FROM Experiments')[0]['status'], 'unverified')

    def test_persistence_world_isolation_and_no_duplicate_results(self):
        result = self.complete()
        self.step([result])
        self.assertEqual(len(self.m.rows("SELECT * FROM Events WHERE type='collected'")), 1)
        self.m.close()
        self.m = MemoryManager(self.root / 'data' / 'memory.sqlite3')
        self.writer = JournalWriter(self.m, self.root / 'journals')
        self.engine = CognitiveEngine(self.m, self.writer)
        self.session = str(uuid4())
        self.assertIsNone(self.step()['command'])
        self.engine.last_seen = 0
        self.session = str(uuid4())
        self.assertIsNotNone(self.step(world='b' * 64)['command'])

    def test_only_completed_days_are_queued_and_exports_are_immutable(self):
        self.complete()
        self.assertEqual(self.m.rows('SELECT * FROM PublicationQueue'), [])
        self.step(day=2)
        first = self.writer.directory(WORLD) / 'day_001.md'
        self.assertTrue(first.exists())
        contents = first.read_bytes()
        self.step(day=2)
        self.assertEqual(len(self.m.rows("SELECT * FROM JournalEntries WHERE kind='daily'")), 1)
        self.assertEqual(first.read_bytes(), contents)
        self.assertFalse((first.parent / 'day_002.md').exists())
        self.assertEqual(len(self.m.rows('SELECT * FROM PublicationQueue')), 1)

    def test_low_health_pauses_before_experiment(self):
        response = self.step(player=dict(x=0, y=64, z=0, health=6, food=20, danger=False, inventory={}))
        self.assertEqual(response['control'], 'pause')
        self.assertIsNone(response['command'])

    def test_session_sequence_replay_rejected(self):
        self.step()
        self.seq = 0
        with self.assertRaises(ValueError):
            self.step()

    def test_publisher_dry_run_no_git_or_push_and_queue_retained(self):
        self.complete()
        self.step(day=2)
        publisher = GitHubPublisher(self.m, self.root)
        with patch.object(publisher, 'run', side_effect=AssertionError('dry-run must not run Git')):
            report = publisher.publish()
            self.assertEqual(report, publisher.publish())
        self.assertEqual(report['mode'], 'dry-run')
        self.assertTrue(all(p.startswith('journals/') for p in report['files']))
        self.assertEqual(self.m.rows('SELECT status FROM PublicationQueue')[0]['status'], 'pending')

    def test_offline_preserves_queue(self):
        self.complete()
        self.step(day=2)
        with patch('agent.journal.github_publisher.shutil.which', return_value=None):
            with self.assertRaises(RuntimeError):
                GitHubPublisher(self.m, self.root).publish(approved=True)
        self.assertEqual(self.m.rows('SELECT status FROM PublicationQueue')[0]['status'], 'pending')

    def test_sensitive_content_and_arbitrary_paths_blocked(self):
        safe = 'journals/' + WORLD + '/day_001.md'
        # Dados artificiais construídos em execução: nenhum caminho pessoal é versionado.
        for text in ('C:' + '\\Users\\player\\secret', 'ghp_' + 'a' * 32, 'api_key=secret', '/' + 'home/person/data'):
            with self.assertRaises(ValueError):
                validate_content(safe, text)
        with self.assertRaises(ValueError):
            validate_content('saves/ia/level.dat', 'anything')

    def test_publisher_rejects_invented_narrative(self):
        self.complete()
        self.step(day=2)
        self.m.db.execute("UPDATE JournalEntries SET text=text || ' Construí uma cidade.' WHERE kind='daily'")
        with self.assertRaises(ValueError):
            GitHubPublisher(self.m, self.root).prepare()

    def test_no_data_means_no_fictitious_journals(self):
        self.assertIsNone(self.writer.write(WORLD, 1))
        self.assertFalse((self.root / 'journals').exists())
        self.assertEqual(GitHubPublisher(self.m, self.root).publish()['entries'], 0)

    def test_public_repo_requires_separate_explicit_permission(self):
        self.complete()
        self.step(day=2)
        publisher = GitHubPublisher(self.m, self.root)
        with patch('agent.journal.github_publisher.shutil.which', return_value='gh'), \
             patch.object(publisher, 'run', return_value=json.dumps({'full_name': 'FelixTheMAchine/MineLifeIA', 'private': False})) as run:
            with self.assertRaises(RuntimeError):
                publisher.publish(approved=True)
            self.assertEqual(run.call_count, 1)  # Apenas leitura de metadados, nunca clone/commit/push.
        self.assertEqual(self.m.rows('SELECT status FROM PublicationQueue')[0]['status'], 'pending')

    def test_existing_export_cannot_be_overwritten(self):
        self.complete()
        self.step(day=2)
        daily = self.writer.directory(WORLD) / 'day_001.md'
        daily.write_text('Alteração externa deliberada do teste', encoding='utf-8')
        with self.assertRaises(ValueError):
            GitHubPublisher(self.m, self.root).prepare()
        self.assertEqual(daily.read_text(encoding='utf-8'), 'Alteração externa deliberada do teste')

    def test_queue_is_chronological_and_survives_restart(self):
        self.complete()
        self.step(day=2)
        self.m.event(WORLD, self.session, 2, 'question', 'Quero estudar outra pergunta.', True, {}, 'fixture-day-2')
        self.m.db.commit()
        self.step(day=3)
        entries, _ = GitHubPublisher(self.m, self.root).prepare()
        self.assertEqual([entry['day'] for entry in entries], [1, 2])
        self.m.close()
        self.m = MemoryManager(self.root / 'data' / 'memory.sqlite3')
        entries, _ = GitHubPublisher(self.m, self.root).prepare()
        self.assertEqual([entry['day'] for entry in entries], [1, 2])


class APITest(unittest.TestCase):
    def test_local_api_auth_origins_and_arming(self):
        with tempfile.TemporaryDirectory() as td:
            app = create_app(Path(td), {'token': 't' * 40})
            with TestClient(app) as client:
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.get('/api/state').status_code, 401)
                headers = {'Authorization': 'Bearer ' + 't' * 40}
                self.assertEqual(client.get('/api/state', headers=headers).status_code, 200)
                self.assertEqual(client.post('/api/control/start', headers=headers).status_code, 409)
                self.assertEqual(client.get('/api/state', headers={**headers, 'Origin': 'https://evil.invalid'}).status_code, 403)
                self.assertEqual(client.get('/api/state', headers={**headers, 'Host': 'evil.invalid'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
