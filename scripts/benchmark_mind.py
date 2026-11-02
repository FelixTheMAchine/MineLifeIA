"""Small explicit synthetic Ollama benchmark. Never reads private memory or saves."""
import argparse
import asyncio
import json
import time

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
            'skills': {'executable': ['observe_block']}, 'synthetic': True}


def evaluate_output(content, context):
    """Only structure and exact fixture reference validity are measurable here."""
    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return {'json_valid': False, 'invented_references': 0, 'referenced_facts': 0}
    if not isinstance(value, dict):
        return {'json_valid': False, 'invented_references': 0, 'referenced_facts': 0}
    allowed = set(context['source_event_ids'])
    references = []

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key in ('event_id', 'source_event_id') and isinstance(child, str):
                    references.append(child)
                elif key in ('evidence_ids', 'source_event_ids', 'fact_ids') and isinstance(child, list):
                    references.extend(v for v in child if isinstance(v, str))
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return {'json_valid': True, 'invented_references': sum(v not in allowed for v in references),
            'referenced_facts': len(references)}


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
            item = {'thinking': mode, 'system_resources_before': before}
            try:
                schema = generator.schema() if callable(generator.schema) else generator.schema
                messages = generator.messages(context, 'cognitive')
                result = await provider.generate(messages, schema, thinking=mode)
                parsed = generator.parse(result.content, context, 'cognitive')
                quality = evaluate_output(result.content, context)
                quality['parser_accepted'] = parsed is not None
                quality['accepted_thoughts'] = len(parsed.get('thoughts', [])) if isinstance(parsed, dict) else 0
                item.update(status='completed', metrics=result.metrics, quality=quality)
            except LocalModelError as exc:
                item.update(status='failed', reason=exc.category)
            except (ValueError, TypeError, KeyError, AttributeError):
                item.update(status='failed', reason='thought_contract_or_parse_error')
            item['wall_seconds'] = time.monotonic() - started
            item['system_resources_after'] = resource.snapshot()
            report['samples'].append(item)
    completed = [v for v in report['samples'] if v['status'] == 'completed']
    report['status'] = 'completed' if completed else 'skipped'
    report['quality_totals'] = {
        'completed': len(completed), 'failed': sum(v['status'] == 'failed' for v in report['samples']),
        'parser_accepted': sum(v['quality']['parser_accepted'] for v in completed),
        'accepted_thoughts': sum(v['quality']['accepted_thoughts'] for v in completed),
        'invented_references': sum(v['quality']['invented_references'] for v in completed)}
    return report


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if not 0 < args.timeout <= 60:
        cli.error('--timeout must be greater than zero and at most 60 seconds')
    if not safe_name(args.model):
        cli.error('--model must be a local model name, without paths')
    print(json.dumps(asyncio.run(benchmark(**vars(args))), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
