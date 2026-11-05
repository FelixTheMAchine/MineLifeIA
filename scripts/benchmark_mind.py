"""Small explicit synthetic Ollama benchmark. Never reads private memory or saves."""
import argparse
import asyncio
import hashlib
import inspect
import json
import time

from agent.contract_diagnostics import ensure_fresh_context, safe_public_error
from agent.local_model import LocalModelError, LocalModelProvider
from agent.resources import ResourceProbe
from scripts.mind_diagnostic import ROOT, minecraft_process_status, read_config, safe_name


def synthetic_context():
    """Fixture observations are examples, never evidence of real gameplay."""
    return {'mind_version': 1, 'world': 'f' * 64, 'session': 'synthetic-benchmark-session',
            'context_id': 'synthetic-benchmark-context', 'day': 1,
            'facts': [{'id': 'fixture-event', 'type': 'shelter_completed',
                       'description': 'SYNTHETIC FIXTURE: a shelter was completed in this invented scenario.',
                       'verified': True}],
            'source_manifest': {'fixture-event': '0' * 64},
            'goals': [{'subject': 'observe:stone', 'skill': 'observe_block', 'kind': 'observe'}],
            'questions': [], 'intents': {'study_material': {'executable': True}},
            'source_event_ids': ['fixture-event'],
            'source_memory_ids': [], 'recalled_memories': [],
            'skills': {'executable': ['observe_block']}, 'synthetic': True}


def evaluate_output(content, context):
    """Only structure and exact fixture reference validity are measurable here."""
    unavailable = {'json_valid': False, 'reference_measurement': 'unavailable',
                   'invented_references': None, 'invalid_evidence_references': None,
                   'invalid_memory_references': None, 'referenced_facts': None, 'referenced_memories': None}
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return unavailable
    if not isinstance(value, dict):
        return unavailable | {'json_valid': True}
    evidence, memories = [], []
    try:
        for field in ('thoughts', 'reconsiderations'):
            parts = value.get(field, [])
            if not isinstance(parts, list):
                raise TypeError()
            for part in parts:
                if not isinstance(part, dict):
                    raise TypeError()
                refs = part.get('evidence_ids', [])
                mids = part.get('memory_ids', []) if field == 'thoughts' else [part['memory_id']]
                if not isinstance(refs, list) or not isinstance(mids, list) or any(not isinstance(v, str) for v in refs+mids):
                    raise TypeError()
                evidence.extend(refs); memories.extend(mids)
        proposal = value.get('proposal')
        if proposal is not None:
            refs = proposal['evidence_ids']
            if not isinstance(refs, list) or any(not isinstance(v, str) for v in refs):
                raise TypeError()
            evidence.extend(refs)
    except (KeyError, TypeError):
        return unavailable | {'json_valid': True}
    invalid_events = sum(ref not in context.get('source_event_ids', []) for ref in evidence)
    invalid_memories = sum(ref not in context.get('source_memory_ids', []) for ref in memories)
    return {'json_valid': True, 'reference_measurement': 'measured',
            'invented_references': invalid_events+invalid_memories,
            'invalid_evidence_references': invalid_events, 'invalid_memory_references': invalid_memories,
            'referenced_facts': len(evidence), 'referenced_memories': len(memories)}


def generation_schema(generator, context):
    """Support existing diagnostic generators while passing context to Mind."""
    schema = generator.schema
    if not callable(schema):
        return schema
    try:
        inspect.signature(schema).bind(context)
    except TypeError:
        return schema()
    return schema(context)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--thinking', choices=('off', 'on', 'both'), default='off')
    result.add_argument('--samples', type=int, choices=range(1, 4), default=1)
    result.add_argument('--timeout', type=float, default=30)
    result.add_argument('--model', default='qwen3:1.7b')
    return result


async def benchmark(*, samples=1, thinking='off', timeout=30, model='qwen3:1.7b',
                    root=ROOT, transport=None, generator=None, process_check=None, probe=None):
    if (samples not in (1, 2, 3) or isinstance(samples, bool) or thinking not in ('off', 'on', 'both')
            or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60
            or not safe_name(model)):
        raise ValueError('invalid_benchmark_options')
    report = {'status': 'skipped', 'scenario': 'SYNTHETIC FIXTURE ONLY', 'model': model,
              'samples': [], 'private_memory_read': False, 'gameplay_verified': False}
    process = (process_check or minecraft_process_status)()
    if process != 'clear':
        report['reason'] = 'minecraft_running' if process == 'running' else 'minecraft_process_unknown'
        return report
    if generator is None:
        try:
            from agent.mind import ThoughtGenerator
            generator = ThoughtGenerator()
        except (ImportError, TypeError):
            report['reason'] = 'thought_generator_unavailable'
            return report
    config, _ = read_config(root)
    llm = config.get('llm') if isinstance(config.get('llm'), dict) else {}
    provider = LocalModelProvider({**llm, 'provider': 'ollama', 'model': model,
                                   'timeout_seconds': timeout}, transport)
    health = await provider.health_check()
    if not health['available']:
        report['reason'] = health['error'] or 'model_unavailable'
        return report
    context = synthetic_context()
    resource = probe or ResourceProbe(interval=1)
    modes = (False, True) if thinking == 'both' else (thinking == 'on',)
    for mode in modes:
        if mode and health['capabilities']['thinking'] is not True:
            report['samples'].append({'status': 'skipped', 'thinking': True, 'reason': 'thinking_unsupported'})
            continue
        for _ in range(samples):
            # Recheck immediately before every inference; never override a running game.
            if (process_check or minecraft_process_status)() != 'clear':
                report['reason'] = 'minecraft_process_changed'
                return report
            before = resource.snapshot()
            started = time.monotonic()
            item = {'thinking': mode, 'system_resources_before': before,
                    'quality': {'json_valid': None, 'reference_measurement': 'unavailable',
                                'invented_references': None, 'invalid_evidence_references': None,
                                'invalid_memory_references': None, 'parser_accepted': False,
                                'accepted_thoughts': 0}}
            stage = 'context'
            try:
                ensure_fresh_context(context)
                schema = generation_schema(generator, context)
                item['schema_sha256'] = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
                messages = generator.messages(context, 'cognitive')
                stage = 'inference'
                result = await provider.generate(messages, schema, thinking=mode)
                item['metrics'] = result.metrics
                item['quality'].update(evaluate_output(result.content, context))
                stage = 'context'
                ensure_fresh_context(context)
                stage = 'parse'
                parsed = generator.parse(result.content, context, 'cognitive')
                item['quality']['parser_accepted'] = parsed is not None
                item['quality']['accepted_thoughts'] = len(parsed.get('thoughts', [])) if isinstance(parsed, dict) else 0
                item.update(status='completed')
            except Exception as exc:
                # Never serialize exception text, model output or Pydantic input.
                diagnostic = safe_public_error(exc)
                item.update(status='failed', reason=diagnostic['category'], stage=stage,
                            diagnostic=diagnostic)
                for flag in ('json_valid', 'pydantic_valid'):
                    if flag in diagnostic:
                        item['quality'][flag] = diagnostic[flag]
                counts = ('invalid_evidence_references', 'invalid_memory_references')
                if all(type(diagnostic.get(key)) is int for key in counts):
                    item['quality'].update({key: diagnostic[key] for key in counts})
                    item['quality']['reference_measurement'] = 'measured'
                    item['quality']['invented_references'] = sum(diagnostic[key] for key in counts)
                if isinstance(exc, LocalModelError) and exc.metrics is not None:
                    item['metrics'] = exc.metrics
            item['wall_seconds'] = time.monotonic() - started
            item['system_resources_after'] = resource.snapshot()
            report['samples'].append(item)
    completed = [v for v in report['samples'] if v['status'] == 'completed']
    report['status'] = 'completed' if completed else 'failed' if any(v['status'] == 'failed' for v in report['samples']) else 'skipped'
    attempted = [v for v in report['samples'] if v['status'] in ('completed', 'failed')]
    measured = [v for v in attempted if v['quality'].get('reference_measurement') == 'measured']
    report['quality_totals'] = {
        'completed': len(completed), 'failed': sum(v['status'] == 'failed' for v in report['samples']),
        'parser_accepted': sum(v['quality']['parser_accepted'] for v in completed),
        'accepted_thoughts': sum(v['quality']['accepted_thoughts'] for v in completed),
        'reference_samples_measured': len(measured),
        'reference_samples_unmeasured': len(attempted)-len(measured),
        **{key: sum(v['quality'][key] for v in measured) if measured else None
           for key in ('invented_references', 'invalid_evidence_references', 'invalid_memory_references')}}
    return report


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if not 0 < args.timeout <= 60:
        cli.error('--timeout must be greater than zero and at most 60 seconds')
    if not safe_name(args.model):
        cli.error('--model must be a local model name, without paths')
    try:
        report = asyncio.run(benchmark(**vars(args)))
        serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
    except Exception as exc:
        # Includes failures in setup/diagnostics, outside the per-sample boundary.
        diagnostic = safe_public_error(exc)
        serialized = json.dumps({'status': 'failed', 'reason': diagnostic['category'],
                                 'stage': 'benchmark', 'diagnostic': diagnostic,
                                 'private_memory_read': False, 'gameplay_verified': False})
    print(serialized)


if __name__ == '__main__':
    main()
