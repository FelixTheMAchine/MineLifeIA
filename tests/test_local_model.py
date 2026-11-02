import asyncio
import json
import unittest

import httpx

from agent.local_model import LocalModelError, LocalModelProvider


SCHEMA = {'type': 'object', 'properties': {'question': {'type': 'string'}},
          'required': ['question'], 'additionalProperties': False}
MESSAGES = [{'role': 'user', 'content': 'A private prompt'}]


class LocalModelTest(unittest.IsolatedAsyncioTestCase):
    def provider(self, chat=None, **config):
        self.calls = []

        def respond(request):
            self.calls.append(request)
            path = request.url.path
            if path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3:1.7b'}]})
            if path == '/api/version':
                return httpx.Response(200, json={'version': 'fixture'})
            if path == '/api/ps':
                return httpx.Response(200, json={'models': []})
            if path == '/api/show':
                return httpx.Response(200, json={'capabilities': ['completion', 'thinking']})
            if chat:
                return chat(request)
            return httpx.Response(200, json={
                'model': 'qwen3:1.7b', 'created_at': 'fixture-time',
                'message': {'content': '{"question":"Why?"}'}, 'eval_count': 12,
                'eval_duration': 2000000000, 'prompt_eval_count': 18, 'load_duration': 100})

        return LocalModelProvider({'provider': 'ollama', **config}, httpx.MockTransport(respond))

    async def assert_category(self, provider, category):
        with self.assertRaises(LocalModelError) as caught:
            await provider.generate(MESSAGES, SCHEMA)
        self.assertEqual(caught.exception.category, category)
        self.assertEqual(str(caught.exception), category)

    async def test_native_schema_cpu_options_and_real_metrics(self):
        provider = self.provider()
        result = await provider.generate(MESSAGES, SCHEMA)
        body = json.loads(self.calls[-1].content)
        self.assertEqual(body['format'], SCHEMA)
        self.assertFalse(body['think'])
        self.assertFalse(body['stream'])
        self.assertNotIn('tools', body)
        self.assertEqual(body['options'], {'num_ctx': 4096, 'num_predict': 384,
                         'temperature': .2, 'num_gpu': 0, 'num_thread': 2})
        self.assertEqual(body['keep_alive'], '2m')
        self.assertEqual(result.metrics['tokens_per_second'], 6)
        self.assertEqual(result.metrics['prompt_eval_count'], 18)
        self.assertGreaterEqual(result.metrics['wall_seconds'], 0)
        self.assertEqual(result.generated_at, 'fixture-time')
        self.assertNotIn('private', str(provider.snapshot()))
        self.assertEqual(provider.snapshot()['requests'], 1)

    async def test_health_cache_and_capabilities(self):
        provider = self.provider()
        health = await provider.health_check()
        self.assertTrue(health['available'])
        self.assertTrue(health['capabilities']['thinking'])
        self.assertEqual(health['version'], 'fixture')
        await provider.generate(MESSAGES, SCHEMA, thinking=True)
        await provider.generate(MESSAGES, SCHEMA)
        self.assertEqual(len([r for r in self.calls if r.url.path == '/api/tags']), 1)

    async def test_disabled_never_connects(self):
        provider = self.provider(provider='none')
        self.assertEqual((await provider.health_check())['status'], 'disabled')
        self.assertEqual(self.calls, [])

    async def test_rejects_remote_dns_credentials_paths_and_redirects(self):
        for base in ('https://127.0.0.1:11434', 'http://localhost:11434',
                     'http://127.0.0.2:11434',
                     'http://example.com', 'http://127.0.0.1.evil', 'http://user@127.0.0.1',
                     'http://127.0.0.1/path', 'http://127.0.0.1?x=1'):
            with self.subTest(base=base):
                provider = self.provider(base_url=base)
                await self.assert_category(provider, 'invalid_config')
                self.assertFalse(self.calls)
        provider = LocalModelProvider({'provider': 'ollama'}, httpx.MockTransport(
            lambda r: httpx.Response(302, headers={'location': 'http://example.com/secret'})))
        await self.assert_category(provider, 'server_error')

    async def test_ipv6_literal_supported(self):
        provider = self.provider(base_url='http://[::1]:11434')
        await provider.generate(MESSAGES, SCHEMA)
        self.assertTrue(all(r.url.host == '::1' for r in self.calls))

    async def test_missing_model_never_infers_or_downloads(self):
        provider = self.provider(model='absent')
        await self.assert_category(provider, 'model_missing')
        self.assertEqual([r.url.path for r in self.calls], ['/api/tags'])

    async def test_network_errors_sanitized(self):
        for exception, category in ((httpx.ConnectError('secret path'), 'unavailable'),
                                    (httpx.ReadError('secret token'), 'network_error'),
                                    (httpx.ReadTimeout('secret prompt'), 'timeout')):
            with self.subTest(category=category):
                def fail(request):
                    raise exception
                provider = LocalModelProvider({'provider': 'ollama'}, httpx.MockTransport(fail))
                await self.assert_category(provider, category)
                self.assertNotIn('secret', str(provider.snapshot()))

    async def test_empty_malformed_schema_and_oversize(self):
        cases = [({'message': {'content': ''}}, 'empty_response'),
                 ({'message': {'content': 'not json'}}, 'malformed_response'),
                 ({'message': {'content': '{"question":3}'}}, 'schema_mismatch'),
                 ({'message': {'content': '{}'}}, 'schema_mismatch'),
                 ({'message': {'content': '{}', 'tool_calls': [{}]}}, 'malformed_response'),
                 ({'message': {'content': 'x' * 70000}}, 'response_too_large')]
        for data, category in cases:
            with self.subTest(category=category):
                provider = self.provider(lambda r: httpx.Response(200, json=data))
                await self.assert_category(provider, category)
        provider = self.provider(lambda r: httpx.Response(200, content=b'broken'))
        await self.assert_category(provider, 'malformed_response')

    async def test_error_invalidates_availability_and_recovers(self):
        count = 0

        def response(request):
            nonlocal count
            count += 1
            if count == 1:
                return httpx.Response(404, json={'error': 'sensitive error text'})
            return httpx.Response(200, json={'message': {'content': '{"question":"ok"}'}})

        provider = self.provider(response)
        await self.assert_category(provider, 'model_missing')
        self.assertFalse(provider.snapshot()['available'])
        await provider.generate(MESSAGES, SCHEMA)
        self.assertEqual(provider.snapshot()['status'], 'ready')
        self.assertEqual(provider.snapshot()['errors'], 1)
        self.assertEqual(len([r for r in self.calls if r.url.path == '/api/tags']), 2)

    async def test_thinking_requires_declared_capability(self):
        async def respond(request):
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3:1.7b'}]})
            return httpx.Response(404)
        provider = LocalModelProvider({'provider': 'ollama'}, httpx.MockTransport(respond))
        with self.assertRaises(LocalModelError) as caught:
            await provider.generate(MESSAGES, SCHEMA, thinking=True)
        self.assertEqual(caught.exception.category, 'thinking_unsupported')

    async def test_cancellation_releases_single_inference_lock(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0
        peak = 0

        async def respond(request):
            nonlocal active, peak
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3:1.7b'}]})
            if request.url.path != '/api/chat':
                return httpx.Response(404)
            active += 1
            peak = max(active, peak)
            entered.set()
            try:
                await release.wait()
                return httpx.Response(200, json={'message': {'content': '{"question":"ok"}'}})
            finally:
                active -= 1

        provider = LocalModelProvider({'provider': 'ollama'}, httpx.MockTransport(respond))
        first = asyncio.create_task(provider.generate(MESSAGES, SCHEMA))
        await entered.wait()
        second = asyncio.create_task(provider.generate(MESSAGES, SCHEMA))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        await second
        self.assertEqual(peak, 1)
        self.assertEqual(provider.snapshot()['cancelled'], 1)
        self.assertFalse(provider.snapshot()['remote_cancellation_confirmed'])

    async def test_total_timeout_covers_mock_and_trickle(self):
        async def respond(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={})
        provider = LocalModelProvider({'provider': 'ollama', 'timeout_seconds': .01},
                                      httpx.MockTransport(respond))
        await self.assert_category(provider, 'timeout')

    async def test_stream_is_closed_without_reading_unbounded_body(self):
        class OversizeStream(httpx.AsyncByteStream):
            closed = False
            chunks_read = 0

            async def __aiter__(self):
                for _ in range(100):
                    self.chunks_read += 1
                    yield b'x' * 32768

            async def aclose(self):
                self.closed = True

        stream = OversizeStream()
        provider = self.provider(lambda r: httpx.Response(200, stream=stream))
        await self.assert_category(provider, 'response_too_large')
        self.assertTrue(stream.closed)
        self.assertEqual(stream.chunks_read, 3)

    async def test_thinking_values_metadata_is_explicit(self):
        async def respond(request):
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3:1.7b'}]})
            if request.url.path == '/api/show':
                return httpx.Response(200, json={'thinking': {'values': [True, False]}})
            if request.url.path == '/api/chat':
                self.assertTrue(json.loads(request.content)['think'])
                return httpx.Response(200, json={'message': {'content': '{"question":"ok"}'}})
            return httpx.Response(404)

        provider = LocalModelProvider({'provider': 'ollama'}, httpx.MockTransport(respond))
        await provider.generate(MESSAGES, SCHEMA, thinking=True)

    async def test_invalid_options_and_tool_messages_do_not_connect(self):
        provider = self.provider(num_thread=0)
        await self.assert_category(provider, 'invalid_config')
        self.assertFalse(self.calls)
        provider = self.provider()
        with self.assertRaises(LocalModelError):
            await provider.generate([{'role': 'tool', 'content': 'run'}], SCHEMA)
        self.assertFalse(self.calls)
