import json
from contextlib import closing, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
import zipfile

import httpx

from scripts import benchmark_mind as bench
from scripts import mind_diagnostic as diag


class FixtureGenerator:
    schema = {'type': 'object', 'properties': {'thoughts': {'type': 'array'}}, 'required': ['thoughts']}

    def messages(self, context, purpose):
        return [{'role': 'user', 'content': json.dumps(context)}]

    def parse(self, content, context, purpose):
        return json.loads(content)


class MindToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_diagnostic_missing_files_never_creates_config_or_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(diag, 'runtime_report', return_value={}), \
                 patch.object(diag, 'minecraft_process_status', return_value='clear'), \
                 patch.object(diag, 'ollama_cli_report', return_value={'status': 'unavailable'}):
                report = await diag.diagnostic(root, root / 'absent-game',
                                               httpx.MockTransport(lambda r: httpx.Response(503)))
            self.assertTrue(report['read_only'])
            self.assertEqual(report['memory']['status'], 'missing')
            self.assertEqual(report['configuration']['status'], 'missing')
            self.assertEqual(list(root.iterdir()), [])

    async def test_config_output_omits_tokens_personal_paths_and_arbitrary_keys(self):
        config = {'token': 'secret-token', 'save': 'D:/private-fixture/saves',
                  'llm': {'provider': 'ollama', 'model': 'D:/private-fixture/model',
                          'base_url': 'http://secret-token@example.com', 'api_key': 'secret-token',
                          'num_thread': 2}}
        output = json.dumps(diag.config_report(config, 'present'))
        self.assertNotIn('secret-token', output)
        self.assertNotIn('private', output)
        self.assertIn('num_thread', output)

    async def test_memory_reads_counts_without_migration_or_private_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            path = root / 'data/memory.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.executescript("PRAGMA user_version=3; CREATE TABLE Events(description TEXT); INSERT INTO Events VALUES('private memory');")
                db.commit()
            before = path.read_bytes()
            report = diag.memory_report(root)
            self.assertEqual(report['user_version'], 3)
            self.assertEqual(report['row_counts']['Events'], 1)
            self.assertEqual(report['integrity'], 'ok')
            self.assertNotIn('private memory', json.dumps(report))
            self.assertEqual(path.read_bytes(), before)

    async def test_installed_jar_metadata_does_not_expose_file_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mods').mkdir()
            with zipfile.ZipFile(root / 'mods/minelife-ai-fixture.jar', 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps({'id': 'minelife_ai', 'version': '0.2.0',
                                                              'depends': {'minecraft': '1.21.1'}}))
            report = diag.mod_report(root, root)
            self.assertEqual(report['installed']['mods'][0]['version'], '0.2.0')
            self.assertNotIn(directory, json.dumps(report))

    async def test_bridge_reports_protocol_mismatch_and_filters_features(self):
        report = await diag.bridge_report(httpx.MockTransport(lambda r: httpx.Response(200, json={
            'protocol': 2, 'features': ['social-v1', 'D:/private-fixture'], 'token': 'secret'})))
        self.assertEqual(report['status'], 'mismatch')
        self.assertEqual(report['features'], ['social-v1'])
        self.assertNotIn('secret', json.dumps(report))

    async def test_benchmark_refuses_running_or_unknown_game_without_network(self):
        for process in ('running', 'unknown'):
            def fail(request):
                self.fail('network must not be used')
            report = await bench.benchmark(process_check=lambda: process,
                                           transport=httpx.MockTransport(fail), generator=FixtureGenerator())
            self.assertEqual(report['status'], 'skipped')
            self.assertFalse(report['samples'])

    async def test_benchmark_missing_model_is_skipped_without_inference(self):
        calls = []

        def respond(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={'models': []})

        with tempfile.TemporaryDirectory() as directory:
            report = await bench.benchmark(root=Path(directory), process_check=lambda: 'clear',
                                           transport=httpx.MockTransport(respond), generator=FixtureGenerator())
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(report['reason'], 'model_missing')
        self.assertEqual(calls, ['/api/tags'])

    async def test_benchmark_uses_synthetic_schema_and_real_api_metrics(self):
        calls = []

        def respond(request):
            calls.append(request)
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3:1.7b'}]})
            if request.url.path != '/api/chat':
                return httpx.Response(404)
            body = json.loads(request.content)
            self.assertEqual(body['format'], FixtureGenerator.schema)
            self.assertFalse(body['think'])
            self.assertIn('SYNTHETIC FIXTURE', body['messages'][0]['content'])
            return httpx.Response(200, json={'message': {'content': '{"thoughts":[{"evidence_ids":["invented-event"]}]}'},
                                             'eval_count': 20, 'eval_duration': 1000000000})

        with tempfile.TemporaryDirectory() as directory:
            report = await bench.benchmark(root=Path(directory), process_check=lambda: 'clear',
                                           transport=httpx.MockTransport(respond), generator=FixtureGenerator())
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['samples'][0]['metrics']['tokens_per_second'], 20)
        self.assertEqual(report['quality_totals']['invented_references'], 1)
        self.assertEqual(report['quality_totals']['accepted_thoughts'], 1)
        self.assertNotIn('invented-event', json.dumps(report))
        self.assertEqual(sum(r.url.path == '/api/chat' for r in calls), 1)

    async def test_benchmark_bounds(self):
        for options in ({'samples': 0}, {'samples': 4}, {'timeout': 61}, {'timeout': 0},
                        {'model': 'D:/private-fixture/model'}, {'thinking': 'maybe'}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    await bench.benchmark(**options)
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            bench.parser().parse_args(['--samples', '4'])

    async def test_cli_absent_or_timeout_is_nonfatal(self):
        with patch.object(diag.shutil, 'which', return_value=None):
            self.assertEqual(diag.ollama_cli_report()['status'], 'unavailable')
        with patch.object(diag.subprocess, 'run', side_effect=OSError('private path')):
            self.assertEqual(diag.run_readonly(['java', '-version']), (None, ''))


class BenchmarkCliTest(unittest.TestCase):
    def test_unexpected_setup_exception_is_reported_without_private_traceback(self):
        stream = io.StringIO()
        with patch.object(bench, 'benchmark', new=AsyncMock(side_effect=RuntimeError('synthetic-private-token'))), \
                redirect_stdout(stream):
            bench.main([])
        report = json.loads(stream.getvalue())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['reason'], 'internal_error')
        self.assertNotIn('synthetic-private-token', stream.getvalue())
        self.assertNotIn('Traceback', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
