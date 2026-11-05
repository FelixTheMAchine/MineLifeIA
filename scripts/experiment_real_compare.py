"""Bounded Ollama A/B/C comparison on synthetic, disposable SQLite fixtures.

Run explicitly: python -m scripts.experiment_real_compare --seeds 19
No private configuration, memory, saves or generated prose enters the report.
"""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import tempfile
import time

from agent.contract_diagnostics import ensure_fresh_context, safe_public_error
from agent.local_model import LocalModelProvider
from agent.memory import MemoryManager
from agent.mind import ThoughtGenerator
from agent.resources import ResourceProbe
from scripts.experiment_compare import _NoRecall, _engine, _prepare, _run_arm, _step
from scripts.mind_diagnostic import minecraft_process_status, safe_name


OPTIONS = dict(provider='ollama', num_ctx=4096, max_output_tokens=384,
               temperature=.2, num_gpu=0, num_thread=2, keep_alive='2m')
RESOURCE_LIMITS = dict(min_free_ram_mb=4096, max_cpu_percent=85)


def _resources(probe):
    value = probe.snapshot()
    return {key: value.get(key) if type(value.get(key)) in (int, float)
            and math.isfinite(value[key]) else None for key in ('free_ram_mb', 'cpu_percent')}


def _resource_blocked(value):
    return (value['free_ram_mb'] is not None and value['free_ram_mb'] < RESOURCE_LIMITS['min_free_ram_mb']
            or value['cpu_percent'] is not None and value['cpu_percent'] > RESOURCE_LIMITS['max_cpu_percent'])


def _metrics(value):
    keys = ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration',
            'eval_count', 'eval_duration', 'tokens_per_second', 'wall_seconds')
    return {key: value[key] for key in keys if type(value.get(key)) in (int, float)
            and math.isfinite(value[key]) and value[key] >= 0}


def _conditions(seed):
    step = _step(seed, 3)
    return dict(capabilities=sorted(step.capabilities), active=step.active, armed=step.armed,
                health=step.player.health, food=step.player.food, danger=step.player.danger)


async def _real_arm(base, root, seed, scenario, arm, provider, process_check, probe,
                    *, context_tokens, max_output_tokens, skip_reason=None):
    path = root / f'{arm}.sqlite3'
    with closing(sqlite3.connect(path)) as destination:
        base.db.backup(destination)
    memory = MemoryManager(path)
    try:
        engine = _engine(memory, root / arm)
        engine.mind_context.config = dict(context_tokens=context_tokens, num_ctx=OPTIONS['num_ctx'],
                                          max_output_tokens=max_output_tokens)
        step = _step(seed, 3, blocks=[dict(x=scenario['block_x'], y=64, z=0,
                                          id='minecraft:stone', log=False)],
                     frontiers=[dict(x=scenario['frontier_x'], y=64, z=0, safe=True,
                                     path_length=scenario['frontier_x'])])
        engine.latest = step
        if arm == 'B':
            disabled = _NoRecall()
            engine.language.autobiography = disabled
            engine.mind_context.retriever.autobiography = disabled
        engine.mind.set_epoch(0, f'synthetic-real:{seed}:{arm}')
        context = engine.mind_context.build(step, engine.goals.rows(step.world), {}, [], generation=0)
        messages = ThoughtGenerator.messages(context, 'synthetic_comparison')
        schema = ThoughtGenerator.schema(context)
        before = memory.rows('SELECT * FROM Events ORDER BY id')
        result = dict(arm=arm, status='skipped', fallback=True, suggestion_accepted=False,
                      output_structurally_valid=None, proposal_present=None,
                      proposal_bound=False, intention_accepted=False, influenced=False,
                      recalled_memories=len(context['source_memory_ids']),
                      source_events=len(context['source_event_ids']), context_sha256=context['context_id'],
                      prompt_json_bytes=len(json.dumps(messages).encode('utf-8')),
                      schema_json_bytes=len(json.dumps(schema).encode('utf-8')),
                      inference_attempted=False, inference_seconds=None, metrics={}, diagnostic=None,
                      resources_before=_resources(probe), resources_after=None,
                      conditions=_conditions(seed), initial_event_count=len(before),
                      confirmed_action_outcomes=0)
        process = process_check() if skip_reason is None else None
        if skip_reason is not None:
            result['reason'] = skip_reason
        elif process != 'clear':
            result['reason'] = 'minecraft_running' if process == 'running' else 'minecraft_process_unknown'
        elif _resource_blocked(result['resources_before']):
            result['reason'] = 'resource_budget'
        else:
            started = time.monotonic()
            result['inference_attempted'] = True
            try:
                ensure_fresh_context(context)
                response = await provider.generate(messages, schema, thinking=False)
                result['metrics'] = _metrics(response.metrics)
                ensure_fresh_context(context)
                result['output_structurally_valid'] = False
                output = ThoughtGenerator.parse(response.content, context, 'synthetic_comparison')
                result['output_structurally_valid'] = True
                stamp = time.time()
                envelope = dict(mind_version=1, generation=0, runtime_id=engine.mind.validator.runtime_id,
                                context=context, output=output, model=response.model,
                                created_at=stamp, expires_at=min(context['expires_at'], stamp+120))
                valid, reason = engine.mind.validator.validate(step, envelope)
                engine.record_advice(envelope)
                result.update(status='completed', fallback=not valid, suggestion_accepted=valid,
                              proposal_present=output['proposal'] is not None,
                              validation_reason=reason, reason=None)
                result['proposal_bound'] = bool(memory.rows("SELECT 1 FROM MindBindings WHERE status='active'"))
                result['intention_accepted'] = result['proposal_bound']
            except Exception as error:
                result.update(status='fallback', reason=safe_public_error(error)['category'],
                              diagnostic=safe_public_error(error))
                if isinstance(getattr(error,'metrics',None),dict):
                    result['metrics'] = _metrics(error.metrics)
            finally:
                result['inference_seconds'] = time.monotonic()-started
                result['resources_after'] = _resources(probe)
        result['factual_mutations_from_suggestion'] = before != memory.rows('SELECT * FROM Events ORDER BY id')
        command = engine.step(step)['command']
        result.update(selected_action=command['action'] if command else None,
                      selected_target=command['target'] if command else None,
                      influenced=bool(memory.rows("SELECT 1 FROM MindEvaluations WHERE kind='selection' AND outcome='influenced'")))
        return result
    finally:
        memory.close()


async def run_real_experiment(seeds=(19,), *, model='qwen3.5:4b-q4_K_M', timeout=60,
                              context_tokens=1800, max_output_tokens=384,
                              provider=None, process_check=None, probe=None):
    seeds = tuple(seeds)
    if not seeds or len(seeds)>3 or any(type(seed) is not int or not 0<=seed<2**32 for seed in seeds):
        raise ValueError('seeds_must_be_1_to_3_unsigned_integers')
    if not safe_name(model) or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0<timeout<=60:
        raise ValueError('invalid_model_or_timeout')
    if type(context_tokens) is not int or not 400<=context_tokens<=1800:
        raise ValueError('invalid_context_tokens')
    if type(max_output_tokens) is not int or not 128<=max_output_tokens<=384:
        raise ValueError('invalid_max_output_tokens')
    options=OPTIONS | dict(max_output_tokens=max_output_tokens)
    process_check = process_check or minecraft_process_status
    probe = probe or ResourceProbe(interval=1)
    report = dict(protocol_version=1, status='skipped', synthetic=True, gameplay_verified=False,
                  model=model, model_inference=False, private_memory_read=False, runs=[],
                  database_isolation='independent_temporary_sqlite_backups',
                  options=options | dict(timeout_seconds=timeout,context_tokens=context_tokens), resource_limits=RESOURCE_LIMITS,
                  max_inference_calls=2*len(seeds), thinking=False,
                  limitations=['Synthetic contract decisions only; no gameplay or subsequent physical outcomes.',
                               'One bounded serial model call per B/C arm; no retries or model downloads.',
                               'Only model-context recall is ablated; planner facts and learning remain equal.',
                               'Source hashes identify selected files, not a complete archived code snapshot.',
                               'Model variability and call order prevent a causal efficacy conclusion from one run.'])
    code_root = Path(__file__).resolve().parents[1]
    report['source_hashes'] = {relative: hashlib.sha256((code_root / relative).read_bytes()).hexdigest()
                               for relative in ('scripts/experiment_real_compare.py','scripts/experiment_compare.py',
                                                'agent/engine.py','agent/mind.py','agent/local_model.py')}
    report['code_snapshot_complete'] = False
    process = process_check()
    if process != 'clear':
        report['reason'] = 'minecraft_running' if process == 'running' else 'minecraft_process_unknown'
        return report
    provider = provider or LocalModelProvider(options | dict(model=model, timeout_seconds=timeout))
    health = await provider.health_check()
    if not health.get('available'):
        report['reason'] = health.get('error') if health.get('error') in ('model_missing','unavailable','timeout') else 'model_unavailable'
        return report
    for seed in seeds:
        rng = random.Random(seed)
        scenario = dict(block_x=rng.choice((2, 3)), frontier_x=rng.choice((9, 10)))
        fingerprint = hashlib.sha256(json.dumps(dict(seed=seed, scenario=scenario), sort_keys=True).encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='minelife-real-synthetic-') as folder:
            root = Path(folder)
            base = MemoryManager(root / 'base.sqlite3')
            try:
                _prepare(base, root, seed, scenario)
                baseline = base.rows('SELECT * FROM Events ORDER BY id')
                arm_a = _run_arm(base, root, seed, scenario, 'A')
                arm_a.update(status='completed', fallback=False, inference_attempted=False,
                             conditions=_conditions(seed))
                order = ['B', 'C'] if seed % 2 else ['C', 'B']
                arms = [arm_a]
                pair_skip = None
                for arm in order:
                    measured = await _real_arm(base, root, seed, scenario, arm, provider, process_check, probe,
                                               context_tokens=context_tokens,max_output_tokens=max_output_tokens,
                                               skip_reason=pair_skip)
                    arms.append(measured)
                    if measured['status'] != 'completed':
                        pair_skip = 'paired_arm_unavailable'
                if baseline != base.rows('SELECT * FROM Events ORDER BY id'):
                    raise RuntimeError('experiment_baseline_modified')
            finally:
                base.close()
        report['runs'].append(dict(seed=seed, scenario=scenario, scenario_sha256=fingerprint,
                                   inference_order=order, arms=sorted(arms, key=lambda row: row['arm'])))
    model_arms = [arm for run in report['runs'] for arm in run['arms'] if arm['arm'] != 'A']
    report['model_inference'] = any(arm['inference_attempted'] for arm in model_arms)
    report['status'] = 'completed' if all(arm['status']=='completed' for arm in model_arms) else 'partial'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=(19,))
    parser.add_argument('--model', default='qwen3.5:4b-q4_K_M')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--context-tokens', type=int, default=1800)
    parser.add_argument('--max-output-tokens', type=int, default=384)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(run_real_experiment(**vars(args)))
    except ValueError:
        parser.error('invalid_experiment_options')
    except Exception as error:
        report = dict(status='failed', synthetic=True, gameplay_verified=False,
                      private_memory_read=False, diagnostic=safe_public_error(error))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
