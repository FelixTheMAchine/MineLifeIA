"""Measurements of synthetic backend runs; never evidence of Minecraft gameplay."""
from collections import Counter
import hashlib
import json


def world_fingerprint(memory, world):
    """Fingerprint persisted world-scoped rows, including their contents."""
    result={}
    tables=memory.rows("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    for entry in tables:
        name=entry['name']
        if not any(c['name']=='world' for c in memory.rows(f'PRAGMA table_info("{name}")')):
            continue
        rows=memory.rows(f'SELECT * FROM "{name}" WHERE world=?',(world,))
        result[name]=sorted(json.dumps(row,sort_keys=True) for row in rows)
    return hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()


def stock(snapshot):
    return Counter({item:sum(c['count'] for c in snapshot['slots']+snapshot['player_slots'] if c['id']==item)
                    for item in {c['id'] for c in snapshot['slots']+snapshot['player_slots'] if c['count']}})


class LifeMetrics:
    def __init__(self,memory,world):
        self.memory,self.world=memory,world
        self.cycles=0;self.progress_cycles=0;self.responses=Counter();self.seen=set()
        self.repeated_commands=0;self.conservation_checks=0;self.conservation_failures=0
        self.recovery_transitions=0;self.previous_storage={};self.progress_events=set()
        self.isolation_checks=0;self.isolation_failures=0

    def observe(self,response):
        self.cycles+=1
        rows=self.memory.rows("SELECT id FROM Events WHERE world=? AND verified=1 AND type IN "
                              "('crafted','ate','region_reached','storage_deposited','storage_withdrawn',"
                              "'shelter_built','cooked','planted','collected')",(self.world,))
        ids={r['id'] for r in rows}
        self.progress_cycles+=bool(ids-self.progress_events)
        self.progress_events=ids
        cmd=response.get('command')
        if cmd:
            self.repeated_commands+=cmd['id'] in self.seen
            self.seen.add(cmd['id']);self.responses[cmd['action']]+=1
        for row in self.memory.rows('SELECT id,status FROM StorageJobs WHERE world=?',(self.world,)):
            previous=self.previous_storage.get(row['id'])
            if previous in ('intent','uncertain') and row['status'] in ('resolved','retry','inspected'):
                self.recovery_transitions+=1
            self.previous_storage[row['id']]=row['status']

    def conserve(self,before,after,delta=None):
        expected=stock(before)
        expected.update(delta or {})
        # Counter equality ignores zero keys; explicit negatives still fail.
        valid=expected==stock(after) and all(n>=0 for n in expected.values())
        self.conservation_checks+=1;self.conservation_failures+=not valid
        return valid

    def isolated(self,world,fingerprint):
        valid=world_fingerprint(self.memory,world)==fingerprint
        self.isolation_checks+=1;self.isolation_failures+=not valid
        return valid

    def report(self):
        def grouped(table,column):
            return {r['state']:r['n'] for r in self.memory.rows(
                f'SELECT {column} state,count(*) n FROM {table} WHERE world=? GROUP BY {column}',(self.world,))}
        commands={row['id']:row for row in self.memory.rows(
            'SELECT id,session,experiment,payload FROM Commands WHERE world=?',(self.world,))}
        seen_errors=set();repeated_errors=0;uncorrelated_errors=0;categories=Counter()
        for row in self.memory.rows("SELECT session,evidence FROM Events WHERE world=? AND type='attempt_failed' AND verified=1 ORDER BY rowid",
                                    (self.world,)):
            evidence=json.loads(row['evidence']);command=commands.get(evidence.get('command'))
            if not command or command['session']!=row['session']:
                uncorrelated_errors+=1
                continue
            payload=json.loads(command['payload'])
            key=(payload.get('action'),json.dumps(payload.get('target'),sort_keys=True),evidence.get('reason'))
            repeated_errors+=key in seen_errors
            seen_errors.add(key)
            categories[evidence.get('failure_category','unclassified')]+=1
        selections=0;uncorrelated_selections=0;older_missing_observations=0
        mind_changed_choices=0;preference_weighted_choices=0
        oldest=self.memory.rows('SELECT min(timestamp) oldest FROM Observations WHERE world=?',
                                (self.world,))[0]['oldest']
        for row in self.memory.rows("SELECT session,timestamp,evidence FROM Events WHERE world=? AND type='goal_selected' AND verified=1",
                                    (self.world,)):
            evidence=json.loads(row['evidence']);command=commands.get(evidence.get('command'))
            linked=(self.memory.rows('SELECT goal_id FROM ExperimentGoals WHERE experiment=?',
                                     (command['experiment'],)) if command else [])
            observation=self.memory.rows('SELECT 1 FROM Observations WHERE id=? AND world=? AND session=? AND seq=?',
                                         (evidence.get('observation_id'),self.world,row['session'],
                                          evidence.get('observation_seq')))
            if (not command or command['session']!=row['session'] or not linked
                    or linked[0]['goal_id']!=evidence.get('goal')):
                uncorrelated_selections+=1
                continue
            if not observation:
                if oldest is not None and row['timestamp']<oldest:
                    older_missing_observations+=1
                else:
                    uncorrelated_selections+=1
                continue
            selections+=1
            chosen=next((candidate for candidate in evidence.get('alternatives',[])
                         if candidate.get('goal')==evidence['goal']),None)
            preference_weighted_choices+=bool(chosen and chosen.get('components',{}).get('learned_preferences',0))
            if evidence.get('mind_influenced') and evidence.get('baseline')!=evidence['goal']:
                mind_changed_choices+=bool(self.memory.rows(
                    "SELECT 1 FROM MindEvaluations WHERE world=? AND session=? AND goal_id=? "
                    "AND kind='selection' AND outcome='influenced' LIMIT 1",
                    (self.world,row['session'],evidence['goal'])))
        return dict(cycles=self.cycles,progress_cycles=self.progress_cycles,
                    progress_events=len(self.progress_events),command_statuses=grouped('Commands','status'),
                    goal_statuses=grouped('Goals','status'),event_types=grouped('Events','type'),
                    completed_goals=grouped('Goals','status').get('completed',0),
                    blocked_goals=grouped('Goals','status').get('blocked',0),
                    recovered_storage=self.recovery_transitions,repeated_commands=self.repeated_commands,
                    repeated_operational_errors=repeated_errors,uncorrelated_operational_errors=uncorrelated_errors,
                    operational_error_categories=dict(categories),
                    goal_selections=selections,uncorrelated_goal_selections=uncorrelated_selections,
                    older_missing_goal_observations=older_missing_observations,
                    mind_changed_choices=mind_changed_choices,preference_weighted_choices=preference_weighted_choices,
                    conservation_checks=self.conservation_checks,conservation_failures=self.conservation_failures,
                    inventory_conserved=(self.conservation_failures==0 if self.conservation_checks else None),
                    world_isolation_checks=self.isolation_checks,world_isolation_failures=self.isolation_failures,
                    observed_actions=dict(self.responses))
