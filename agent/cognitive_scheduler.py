"""One inference lane, bounded pending work and scope-bound untrusted outputs."""
import asyncio
from collections import deque
from copy import deepcopy
import hashlib
import json
import math
import time
import uuid

from agent.local_model import LocalModelProvider
from agent.resources import ResourceProbe


class CognitiveScheduler:
    SCOPE_FIELDS = ('world', 'dimension', 'session', 'control_epoch')
    VOLATILE_FIELDS = {'seq', 'sequence', 'tick', 'timestamp',
                       'context_id', 'generated_at', 'observed_at', 'captured_at', 'expires_at', 'prior_interpretations'}
    DEEP_TRIGGERS = {'project_completed', 'evidence_contradiction', 'significant_experience', 'project_choice'}

    def __init__(self, config=None, transport=None, *, provider=None, probe=None, clock=time.monotonic):
        self.config = dict(config or {})
        self.provider = provider or LocalModelProvider(self.config, transport)
        self.probe = probe or ResourceProbe()
        self.clock = clock
        self.task = None
        self.queue = deque()
        self.result = None
        self.scope = None
        self.generation = 0
        self.runtime_id = str(uuid.uuid4())
        self.allowed = True
        self.closed = False
        self.status = 'disabled' if self.config.get('provider', 'none') == 'none' else 'idle'
        self.error = None
        self.last_call = self.last_deep = -math.inf
        self.cooldown_until = -math.inf
        self.calls = deque()
        self.seen = deque(maxlen=64)
        self.deep_seen = deque(maxlen=64)
        self.active_key = None
        self.disabled_budget = False
        self.discarded = 0
        self.wake = asyncio.Event()
        self.defer_reason = None
        self.deep_reason = 'not_requested'
        self.thinking_mode = False
        self.resources = {'status': 'unknown', 'free_ram_mb': None, 'cpu_percent': None}

    def _number(self, name, default, low, high):
        value = self.config.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return default
        return min(high, max(low, value))

    @classmethod
    def _scope(cls, scope):
        if isinstance(scope, dict):
            scope = scope.get('scope', scope)
            return tuple(scope.get(k) for k in cls.SCOPE_FIELDS)
        if scope is not None and all(hasattr(scope, key) for key in cls.SCOPE_FIELDS):
            return tuple(getattr(scope, key) for key in cls.SCOPE_FIELDS)
        return tuple(scope)[:4] if scope is not None else None

    def bind_scope(self, scope, allowed=True):
        value = self._scope(scope)
        if value != self.scope or allowed != self.allowed:
            self.generation += 1
            self.scope = value
            self.allowed = bool(allowed)
            self.queue.clear()
            self.result = None
            self.seen.clear()
            self.wake.set()
            self.status = 'idle' if allowed else 'suspended'
        # An obsolete HTTP call keeps the single slot until it actually returns.

    def _prune(self):
        now = self.clock()
        while self.calls and now - self.calls[0] >= 3600:
            self.calls.popleft()
        return now

    def due(self):
        now = self._prune()
        if self.closed or not self.allowed or self.disabled_budget or self.config.get('provider', 'none') == 'none':
            return False
        return (len(self.queue) < int(self._number('queue_size', 2, 1, 16))
                and len(self.calls) < int(self._number('calls_per_hour', 12, 1, 60))
                and now >= self.cooldown_until
                and now - self.last_call >= self._number('interval_seconds', 60, 0, 3600))

    @classmethod
    def _stable(cls, value):
        if isinstance(value, dict):
            return {k: cls._stable(v) for k, v in value.items() if k not in cls.VOLATILE_FIELDS}
        if isinstance(value, list):
            return [cls._stable(v) for v in value]
        return value

    def schedule(self, context, purpose='integrated'):
        if not self.due():
            return False
        if not isinstance(context, dict):
            return False
        context = deepcopy(context)
        context_scope = self._scope(context)
        if self.scope is None:
            self.bind_scope(context_scope)
        if context_scope != self.scope:
            return False
        key = hashlib.sha256(json.dumps([self.runtime_id, self.generation, self.config.get('model'),
                                        1, purpose, self._stable(context)], sort_keys=True,
                                        ensure_ascii=False).encode()).hexdigest()
        if key == self.active_key or key in self.seen or any(job['key'] == key for job in self.queue):
            return False
        now = self.clock()
        meaningful = context.get('deep_trigger') in self.DEEP_TRIGGERS if isinstance(context.get('deep_trigger'), str) else False
        milestones=context.get('deep_event_ids',[])
        fresh_milestone=not milestones or any(eid not in self.deep_seen for eid in milestones)
        deep = meaningful and fresh_milestone and self.config.get('deep_thinking', False) is True
        if deep and now - self.last_deep < self._number('deep_cooldown_seconds', 600, 1, 86400):
            return False
        self.queue.append({'key': key, 'context': context, 'purpose': purpose, 'created': now,
                           'generation': self.generation, 'scope': self.scope, 'deep': deep})
        self.wake.set()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._worker())
        return True

    def _current(self, job):
        return not self.closed and self.allowed and job['generation'] == self.generation and job['scope'] == self.scope

    def _expired(self, job):
        expires = job['context'].get('expires_at')
        return (self.clock() - job['created'] > self._number('job_ttl_seconds', 120, 0.01, 3600)
                or isinstance(expires, (int, float)) and time.time() >= expires)

    def _resource_blocked(self):
        self.resources = self.probe.snapshot()
        ram, cpu = self.resources.get('free_ram_mb'), self.resources.get('cpu_percent')
        return ((ram is not None and ram < self._number('min_free_ram_mb', 2048, 0, 1048576))
                or (cpu is not None and cpu > self._number('max_cpu_percent', 85, 0, 100)))

    async def _defer(self, job, delay, reason):
        self.queue.appendleft(job)
        self.defer_reason = reason
        self.status = 'deferred'
        remaining = self._number('job_ttl_seconds', 120, 0.01, 3600) - (self.clock() - job['created'])
        expires = job['context'].get('expires_at')
        if isinstance(expires, (int, float)):
            remaining = min(remaining, expires - time.time())
        self.wake.clear()
        try:
            await asyncio.wait_for(self.wake.wait(), timeout=max(0.001, min(delay, remaining)))
        except asyncio.TimeoutError:
            pass

    async def _worker(self):
        while self.queue and not self.closed:
            job = self.queue.popleft()
            now = self._prune()
            if not self._current(job) or self._expired(job):
                self.discarded += 1
                continue
            if self.disabled_budget:
                self.status = 'budget_disabled'
                continue
            if len(self.calls) >= int(self._number('calls_per_hour', 12, 1, 60)):
                await self._defer(job, self.calls[0] + 3600 - now, 'hourly_budget')
                continue
            if now < self.cooldown_until:
                await self._defer(job, self.cooldown_until - now, 'cooldown')
                continue
            if self._resource_blocked():
                if self.config.get('disable_on_budget_overrun', False):
                    self.disabled_budget = True
                    self.status = 'budget_disabled'
                    self.defer_reason = 'resource_budget'
                    self.queue.clear()
                    continue
                await self._defer(job, self._number('resource_defer_seconds', 30, 0.01, 600), 'resource_budget')
                continue
            # Check the interval again on dequeue: work may have waited behind another request.
            if now - self.last_call < self._number('interval_seconds', 60, 0, 3600):
                await self._defer(job, self.last_call + self._number('interval_seconds', 60, 0, 3600) - now, 'interval')
                continue
            if job['deep'] and now - self.last_deep < self._number('deep_cooldown_seconds', 600, 1, 86400):
                await self._defer(job, self.last_deep + self._number('deep_cooldown_seconds', 600, 1, 86400) - now, 'deep_cooldown')
                continue
            self.active_key = job['key']
            self.last_call = now
            if job['deep']:
                self.last_deep = now
            self.status = 'thinking'
            self.defer_reason = None
            try:
                from agent.mind import ThoughtGenerator
                messages = ThoughtGenerator.messages(job['context'], job['purpose'])
                thinking = False
                self.deep_reason = 'opt_in_disabled' if job['context'].get('deep_trigger') else 'not_requested'
                if job['deep']:
                    health_check = getattr(self.provider, 'health_check', None)
                    health = await health_check() if health_check else self.provider.snapshot()
                    thinking = health.get('capabilities', {}).get('thinking') is True
                    self.deep_reason = 'enabled' if thinking else 'thinking_unsupported'
                self.thinking_mode = thinking
                attempts = 1 + int(self._number('max_retries', 1, 0, 1))
                for attempt in range(attempts):
                    if not self._current(job):
                        break
                    now = self._prune()
                    if len(self.calls) >= int(self._number('calls_per_hour', 12, 1, 60)):
                        raise RuntimeError('hourly_budget')
                    self.calls.append(now)
                    try:
                        try:
                            response = await self.provider.generate(messages, ThoughtGenerator.schema(), thinking=thinking)
                        except Exception as exc:
                            if not thinking or getattr(exc, 'category', None) != 'thinking_unsupported':
                                raise
                            thinking = self.thinking_mode = False
                            self.deep_reason = 'thinking_unsupported'
                            response = await self.provider.generate(messages, ThoughtGenerator.schema(), thinking=False)
                        output = ThoughtGenerator.parse(response.content, job['context'], job['purpose'])
                        if self._current(job) and not self._expired(job):
                            self.seen.append(job['key'])
                            if thinking:self.deep_seen.extend(job['context'].get('deep_event_ids',[]))
                            self.result = {'mind_version': 1, 'context': job['context'], 'output': output,
                                           'model': response.model, 'generated_at': response.generated_at,
                                           'metrics': response.metrics, 'generation': job['generation'],
                                           'runtime_id': self.runtime_id, 'created_at': time.time(),
                                           'expires_at': job['context'].get('expires_at')}
                            self.status, self.error = 'ready', None
                        else:
                            self.discarded += 1
                            self.status = 'stale'
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if not self._current(job):
                            self.discarded += 1
                            break
                        category = getattr(exc, 'category', type(exc).__name__)
                        self.error = category
                        # A timed-out exchange may still be draining remotely: never immediately retry it.
                        if attempt + 1 == attempts or category not in ('unavailable', 'server_error'):
                            raise
                        await asyncio.sleep(self._number('retry_backoff_seconds', 1, 0, 30))
            except asyncio.CancelledError:
                self.status = 'closed'
                raise
            except Exception as exc:
                if self._current(job):
                    self.error = getattr(exc, 'category', type(exc).__name__)
                    self.status = 'fallback'
                    self.cooldown_until = self.clock() + self._number('failure_cooldown_seconds', 30, 0, 600)
            finally:
                self.active_key = None
                self.thinking_mode = False
                elapsed = self.clock() - self.last_call
                if not self.closed and elapsed > self._number('inference_budget_seconds', 30, 0.01, 600):
                    self.cooldown_until = self.clock() + self._number('overrun_cooldown_seconds', 60, 0, 3600)
                    if self.config.get('disable_on_budget_overrun', False):
                        self.disabled_budget = True
                        self.status = 'budget_disabled'

    def take_result(self):
        value, self.result = self.result, None
        if value is not None:
            expires = value.get('expires_at')
            if isinstance(expires, (int, float)) and time.time() >= expires:
                self.discarded += 1
                return None
        return value

    async def close(self):
        self.closed = True
        self.generation += 1
        self.queue.clear()
        self.wake.set()
        self.result = None
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.status = 'closed'

    def snapshot(self):
        self._prune()
        return {'status': self.status, 'error': self.error, 'calls_last_hour': len(self.calls),
                'fallback': self.config.get('provider','none')=='none' or self.status in ('fallback', 'budget_disabled', 'disabled'),
                'queue_depth': len(self.queue), 'inference_active': self.active_key is not None,
                'generation': self.generation, 'discarded': self.discarded,
                'runtime_id': self.runtime_id,
                'resource': dict(self.resources), 'budget_disabled': self.disabled_budget,
                'defer_reason': self.defer_reason, 'deep_reason': self.deep_reason,
                'thinking': self.thinking_mode,
                'provider': self.provider.snapshot(), 'physical_commands': False,
                'suggestion_unverified': self.result}
