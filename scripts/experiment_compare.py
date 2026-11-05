"""Reproducible synthetic A/B/C plumbing experiment; no Minecraft or model calls.

B and C use the same scripted typed suggestion, not measured LLM reasoning.
Only episodic recall into model context is ablated; factual/learned planner state
is identical. No survival, action outcomes or efficacy are inferred from choices.
Run with: python -m scripts.experiment_compare --seeds 7 19 41
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import tempfile
from uuid import NAMESPACE_URL, uuid5

from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.memory import MemoryManager
from agent.mind import ThoughtGenerator
from agent.protocol import Step


DEFAULT_SEEDS = (7, 19, 41)
ARMS = ('A', 'B', 'C')


class _NoRecall:
    """Local experiment adapter for both existing context retrieval entrypoints."""
    def recall(self, *args, **kwargs):
        return []


def _step(seed, seq, **changes):
    data = dict(protocol=1, world=hashlib.sha256(f'synthetic:{seed}'.encode()).hexdigest(),
                session=str(uuid5(NAMESPACE_URL, f'minelife-synthetic:{seed}')),
                dimension='minecraft:overworld', seq=seq, control_epoch=1,
                day=1, time=1000, active=True, armed=True,
                player=dict(x=0, y=64, z=0, health=20, food=20, danger=False, inventory={}),
                blocks=[], results=[], capabilities=['craft', 'explore', 'observe', 'approach'])
    data.update(changes)
    return Step(**data)


def _engine(memory, root):
    return CognitiveEngine(memory, JournalWriter(memory, root / 'journals'), clock=lambda: 100.,
                           mind_config=dict(context_tokens=6000, num_ctx=8192))


def _prepare(memory, root, seed, scenario):
    engine = _engine(memory, root)
    recipe = dict(id='minecraft:oak_planks', input_id='minecraft:oak_log', input_count=1,
                  output_id='minecraft:oak_planks', output_count=4)
    step = _step(seed, 1, recipes=[recipe],
                 player=dict(x=0, y=64, z=0, health=20, food=20, danger=False,
                             inventory={'minecraft:oak_log': 1}))
    command = engine.step(step)['command']
    if not command or command['action'] != 'craft':
        raise RuntimeError('synthetic_fixture_craft_not_selected')
    evidence = dict(target={k: command['target'][k] for k in ('x', 'y', 'z')},
                    server_verified=True, recipe=recipe['id'], crafted_delta=4,
                    inventory_before={'minecraft:oak_log': 1}, inventory_after={'minecraft:oak_planks': 4})
    latest = _step(seed, 2, results=[dict(id=command['id'], status='success',
                                        reason='SYNTHETIC_FIXTURE_ONLY', evidence=evidence)])
    engine.step(latest)
    engine.goals.ensure(latest, 'explore:minecraft:overworld:(1, 4, 0)',
                        'Explorar materiais e lugares desconhecidos', 'SYNTHETIC FIXTURE ONLY',
                        78, 'explore', dict(target=dict(x=scenario['frontier_x'], y=64, z=0, id='minecraft:air')),
                        'explore_region')
    memory.db.commit()


def _suggestion(context):
    """Same bounded policy in B/C; recall never artificially boosts priority."""
    evidence = next(f['id'] for f in context['facts'] if f['type'] == 'crafted')
    return dict(version=1, thoughts=[dict(category='REFLECTION',
                text='SYNTHETIC FIXTURE: talvez explorar ofereça novas possibilidades.',
                evidence_ids=[evidence], memory_ids=context['source_memory_ids'][:1], uncertainty=.8)],
                proposal=dict(intent='explore_regions', preferred_subject=None,
                              motivation='SYNTHETIC FIXTURE: comparar a mesma proposta tipada.',
                              evidence_ids=[evidence], constraints=['safe_only', 'require_capability'],
                              priority=1., ttl_seconds=120), reconsiderations=[])


def _run_arm(base, root, seed, scenario, arm):
    path = root / f'{arm}.sqlite3'
    with closing(sqlite3.connect(path)) as destination:
        base.db.backup(destination)
    memory = MemoryManager(path)
    try:
        engine = _engine(memory, root / arm)
        step = _step(seed, 3,
                     blocks=[dict(x=scenario['block_x'], y=64, z=0, id='minecraft:stone', log=False)],
                     frontiers=[dict(x=scenario['frontier_x'], y=64, z=0, safe=True,
                                     path_length=scenario['frontier_x'])])
        engine.latest = step
        accepted = None
        recalled = source_events = 0
        before = memory.rows('SELECT * FROM Events ORDER BY id')
        if arm != 'A':
            if arm == 'B':
                # CognitiveLanguageEngine and ContextBuilder independently retrieve.
                disabled = _NoRecall()
                engine.language.autobiography = disabled
                engine.mind_context.retriever.autobiography = disabled
            engine.mind.set_epoch(0, f'synthetic-runtime:{seed}:{arm}')
            context = engine.mind_context.build(step, engine.goals.rows(step.world), {}, [], generation=0)
            recalled, source_events = len(context['source_memory_ids']), len(context['source_event_ids'])
            output = ThoughtGenerator.parse(_suggestion(context), context, 'synthetic_experiment')
            stamp = context['captured_at']
            envelope = dict(mind_version=1, generation=0, runtime_id=engine.mind.validator.runtime_id,
                            context=context, output=output, created_at=stamp, expires_at=stamp+120,
                            model='SCRIPTED_TYPED_FIXTURE_NO_LLM')
            engine.record_advice(envelope)
            accepted = bool(memory.rows("SELECT 1 FROM MindEvaluations WHERE kind='validation' AND outcome='accepted'"))
        factual_mutations = before != memory.rows('SELECT * FROM Events ORDER BY id')
        command = engine.step(step)['command']
        return dict(arm=arm, suggestion_accepted=accepted, recalled_memories=recalled,
                    source_events=source_events, factual_mutations_from_suggestion=factual_mutations,
                    selected_action=command['action'] if command else None,
                    selected_target=command['target'] if command else None,
                    influenced=bool(memory.rows("SELECT 1 FROM MindEvaluations WHERE kind='selection' AND outcome='influenced'")),
                    initial_event_count=len(before), confirmed_action_outcomes=0)
    finally:
        memory.close()


def run_experiment(seeds=DEFAULT_SEEDS):
    seeds = tuple(seeds)
    if not seeds or len(seeds)>32 or any(type(seed) is not int or not 0<=seed<2**32 for seed in seeds):
        raise ValueError('seeds_must_be_1_to_32_unsigned_integers')
    runs = []
    for seed in seeds:
        rng = random.Random(seed)
        scenario = dict(block_x=rng.choice((2, 3)), frontier_x=rng.choice((9, 10)))
        fingerprint = hashlib.sha256(json.dumps(dict(seed=seed, scenario=scenario), sort_keys=True).encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='minelife-synthetic-') as folder:
            root = Path(folder)
            base = MemoryManager(root / 'base.sqlite3')
            try:
                _prepare(base, root, seed, scenario)
                baseline_events = base.rows('SELECT * FROM Events ORDER BY id')
                arms = [_run_arm(base, root, seed, scenario, arm) for arm in ARMS]
                if baseline_events != base.rows('SELECT * FROM Events ORDER BY id'):
                    raise RuntimeError('experiment_baseline_modified')
            finally:
                base.close()
        runs.append(dict(seed=seed, scenario=scenario, scenario_sha256=fingerprint, arms=arms))
    return dict(protocol_version=1, status='completed', synthetic=True, gameplay_verified=False,
                model_inference=False, database_isolation='independent_temporary_sqlite_backups',
                configurations=dict(A='deterministic_planner', B='typed_fixture_without_episodic_recall',
                                    C='typed_fixture_with_verified_episodic_recall'),
                limitations=['Scripted suggestions test integration, not LLM quality or memory efficacy.',
                             'Only model-context recall is ablated; all planner facts and learning stay equal.',
                             'No physical outcome is simulated after the compared decision.'],
                unmeasured_metrics=['survival', 'goal_completion', 'repeated_errors', 'recovery',
                                    'project_completion', 'model_latency', 'cpu', 'ram'], runs=runs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=DEFAULT_SEEDS)
    args = parser.parse_args(argv)
    try:
        report = run_experiment(args.seeds)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
