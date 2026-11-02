"""Bounded, optional Ollama inference. Outputs are untrusted narrative suggestions.

Cancelling a request closes the HTTP exchange; it does not prove that Ollama has
stopped work on its CPU/GPU. This client never downloads or unloads models.
"""
import asyncio
from dataclasses import dataclass
import ipaddress
import json
import math
import time
from urllib.parse import urlsplit

import httpx


class LocalModelError(Exception):
    """A public error code, deliberately excluding response bodies and prompts."""

    def __init__(self, category):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class LocalModelResponse:
    content: str
    model: str
    generated_at: str | None
    metrics: dict


class LocalModelProvider:
    MAX_RESPONSE_BYTES = 65536
    AVAILABILITY_TTL = 5.0

    def __init__(self, config=None, transport=None):
        self.config = dict(config or {})
        self.transport = transport
        self.model = self.config.get('model', 'qwen3:1.7b')
        base = self.config.get('base_url', 'http://127.0.0.1:11434')
        self.base_url = base.rstrip('/') if isinstance(base, str) else ''
        self._lock = asyncio.Lock()
        self._checked = -math.inf
        self._available = False
        self._models = []
        self._thinking = None
        self._status = 'disabled' if self.config.get('provider', 'none') == 'none' else 'unchecked'
        self._error = None
        self._version = None
        self._loaded = []
        self._requests = self._errors = self._cancelled = 0
        self._metrics = None

    def _validate(self):
        if self.config.get('provider', 'none') == 'none':
            raise LocalModelError('disabled')
        if self.config.get('provider') != 'ollama':
            raise LocalModelError('invalid_provider')
        try:
            url = urlsplit(self.base_url)
            # Literal loopback avoids DNS rebinding, proxy settings and remote hosts.
            address = ipaddress.ip_address(url.hostname or '')
            if (url.scheme != 'http' or str(address) not in ('127.0.0.1', '::1') or url.username is not None
                    or url.password is not None or url.path or url.query or url.fragment
                    or url.port == 0):
                raise ValueError()
            if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
                raise ValueError()
        except (ValueError, TypeError):
            raise LocalModelError('invalid_config') from None

    def _number(self, key, default, lower, upper, *, integer=False):
        value = self.config.get(key, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper
                or integer and not isinstance(value, int)):
            raise LocalModelError('invalid_config')
        return value

    def _client(self):
        timeout = self._number('timeout_seconds', 30, .01, 600)
        return httpx.AsyncClient(transport=self.transport, timeout=timeout,
                                 follow_redirects=False, trust_env=False)

    async def _json(self, client, method, path, payload=None):
        try:
            async with client.stream(method, self.base_url + path, json=payload) as response:
                if response.status_code == 404:
                    raise LocalModelError('model_missing' if path in ('/api/chat', '/api/show') else 'unavailable')
                if response.status_code >= 400 or 300 <= response.status_code < 400:
                    raise LocalModelError('server_error')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > self.MAX_RESPONSE_BYTES:
                        raise LocalModelError('response_too_large')
                    body.extend(chunk)
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeError, RecursionError):
                    raise LocalModelError('malformed_response') from None
                if not isinstance(data, dict):
                    raise LocalModelError('malformed_response')
                return data
        except httpx.TimeoutException:
            raise LocalModelError('timeout') from None
        except httpx.ConnectError:
            raise LocalModelError('unavailable') from None
        except httpx.HTTPError:
            raise LocalModelError('network_error') from None

    def _failure(self, exc):
        self._errors += 1
        self._status, self._error = 'fallback', exc.category
        self._available = False
        self._checked = -math.inf

    async def _health(self, client, force=False):
        if not force and time.monotonic() - self._checked < self.AVAILABILITY_TTL:
            if not self._available:
                raise LocalModelError('model_missing')
            return
        tags = await self._json(client, 'GET', '/api/tags')
        models = tags.get('models')
        if not isinstance(models, list):
            raise LocalModelError('malformed_response')
        self._models = [m['name'] for m in models if isinstance(m, dict) and isinstance(m.get('name'), str)]
        self._available = self.model in self._models or self.model + ':latest' in self._models
        self._checked = time.monotonic()
        if not self._available:
            self._thinking = None
            raise LocalModelError('model_missing')
        self._thinking = None
        # Diagnostic endpoints are optional on older Ollama versions.
        for path in ('/api/version', '/api/ps', '/api/show'):
            try:
                data = await self._json(client, 'POST' if path == '/api/show' else 'GET', path,
                                        {'model': self.model} if path == '/api/show' else None)
            except LocalModelError as exc:
                if exc.category not in ('unavailable', 'model_missing', 'server_error'):
                    raise
                continue
            if path == '/api/version':
                self._version = data.get('version') if isinstance(data.get('version'), str) else None
            elif path == '/api/ps':
                self._loaded = [m['name'] for m in data.get('models', [])
                                if isinstance(m, dict) and isinstance(m.get('name'), str)] if isinstance(data.get('models', []), list) else []
            else:
                caps = data.get('capabilities')
                self._thinking = 'thinking' in caps if isinstance(caps, list) else None
                thinking_metadata = data.get('thinking')
                if isinstance(thinking_metadata, dict) and isinstance(thinking_metadata.get('values'), list):
                    self._thinking = True in thinking_metadata['values']

    async def health_check(self, force=False):
        try:
            self._validate()
            async with asyncio.timeout(self._number('timeout_seconds', 30, .01, 600)):
                async with self._lock:
                    async with self._client() as client:
                        await self._health(client, force)
                    self._status, self._error = 'available', None
        except TimeoutError:
            self._failure(LocalModelError('timeout'))
        except LocalModelError as exc:
            self._failure(exc)
            if exc.category == 'disabled':
                self._status = 'disabled'
        return self.snapshot()

    async def generate(self, messages, schema, *, thinking=False):
        # A total deadline also bounds slow trickle responses and lock contention.
        try:
            async with asyncio.timeout(self._number('timeout_seconds', 30, .01, 600)):
                return await self._generate(messages, schema, thinking=thinking)
        except TimeoutError:
            exc = LocalModelError('timeout')
            self._failure(exc)
            raise exc from None
        except asyncio.CancelledError:
            self._cancelled += 1
            self._status, self._error = 'cancelled', 'cancelled'
            raise

    async def _generate(self, messages, schema, *, thinking=False):
        started = time.monotonic()
        try:
            self._validate()
            if (not isinstance(schema, dict) or not isinstance(messages, list) or not messages
                    or any(not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant')
                           or not isinstance(m.get('content'), str) or set(m) - {'role', 'content'} for m in messages)):
                raise LocalModelError('invalid_request')
            if len(json.dumps(messages)) > 65536:
                raise LocalModelError('context_too_large')
            options = {'num_ctx': self._number('num_ctx', 4096, 512, 32768, integer=True),
                       'num_predict': self._number('max_output_tokens', 384, 1, 4096, integer=True),
                       'temperature': self._number('temperature', .2, 0, 2),
                       'num_gpu': self._number('num_gpu', 0, 0, 128, integer=True),
                       'num_thread': self._number('num_thread', 2, 1, 64, integer=True)}
            keep_alive = self.config.get('keep_alive', '2m')
            if not isinstance(keep_alive, str) or len(keep_alive) > 16:
                raise LocalModelError('invalid_config')
            async with self._lock:
                async with self._client() as client:
                    await self._health(client)
                    if thinking and self._thinking is not True:
                        raise LocalModelError('thinking_unsupported')
                    self._status = 'generating'
                    self._requests += 1
                    data = await self._json(client, 'POST', '/api/chat', {
                        'model': self.model, 'messages': messages, 'stream': False,
                        'format': schema, 'think': bool(thinking), 'options': options,
                        'keep_alive': keep_alive})
            message = data.get('message')
            if not isinstance(message, dict) or message.get('tool_calls'):
                raise LocalModelError('malformed_response')
            content = message.get('content')
            if not isinstance(content, str) or not content.strip():
                raise LocalModelError('empty_response')
            try:
                parsed = json.loads(content)
            except (ValueError, RecursionError):
                raise LocalModelError('malformed_response') from None
            if not self._matches(parsed, schema):
                raise LocalModelError('schema_mismatch')
            metrics = {key: value for key in ('total_duration', 'load_duration', 'prompt_eval_count',
                       'prompt_eval_duration', 'eval_count', 'eval_duration')
                       if isinstance((value := data.get(key)), (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and value >= 0}
            duration = metrics.get('eval_duration', 0)
            metrics['tokens_per_second'] = metrics['eval_count'] * 1e9 / duration if duration and 'eval_count' in metrics else None
            metrics['wall_seconds'] = time.monotonic() - started
            self._metrics = metrics
            self._status, self._error = 'ready', None
            return LocalModelResponse(content, str(data.get('model', self.model)),
                                      data.get('created_at') if isinstance(data.get('created_at'), str) else None, metrics)
        except LocalModelError as exc:
            self._failure(exc)
            raise

    @classmethod
    def _matches(cls, value, schema):
        """Check the small JSON-schema subset used by the advisor, without coercion."""
        kinds = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
                 'integer': int, 'number': (int, float), 'null': type(None)}
        kind = schema.get('type')
        if isinstance(kind, list):
            if not any(cls._matches(value, {**schema, 'type': k}) for k in kind):
                return False
        elif kind in kinds:
            if not isinstance(value, kinds[kind]) or kind in ('integer', 'number') and isinstance(value, bool):
                return False
        if 'enum' in schema and value not in schema['enum']:
            return False
        if isinstance(value, dict):
            if any(key not in value for key in schema.get('required', [])):
                return False
            props = schema.get('properties', {})
            if schema.get('additionalProperties') is False and set(value) - set(props):
                return False
            if any(not cls._matches(v, props[k]) for k, v in value.items() if k in props):
                return False
        if isinstance(value, list) and isinstance(schema.get('items'), dict):
            return all(cls._matches(v, schema['items']) for v in value)
        return True

    def snapshot(self):
        return {'provider': self.config.get('provider', 'none'), 'model': self.model,
                'status': self._status, 'error': self._error, 'available': self._available,
                'available_models': list(self._models), 'version': self._version,
                'loaded_models': list(self._loaded), 'capabilities': {'thinking': self._thinking},
                'requests': self._requests, 'errors': self._errors, 'cancelled': self._cancelled,
                'metrics': dict(self._metrics) if self._metrics else None,
                'physical_commands': False, 'remote_cancellation_confirmed': False}
