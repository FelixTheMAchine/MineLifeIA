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
        return dict(cycles=self.cycles,progress_cycles=self.progress_cycles,
                    progress_events=len(self.progress_events),command_statuses=grouped('Commands','status'),
                    goal_statuses=grouped('Goals','status'),event_types=grouped('Events','type'),
                    completed_goals=grouped('Goals','status').get('completed',0),
                    blocked_goals=grouped('Goals','status').get('blocked',0),
                    recovered_storage=self.recovery_transitions,repeated_commands=self.repeated_commands,
                    conservation_checks=self.conservation_checks,conservation_failures=self.conservation_failures,
                    inventory_conserved=(self.conservation_failures==0 if self.conservation_checks else None),
                    world_isolation_checks=self.isolation_checks,world_isolation_failures=self.isolation_failures,
                    observed_actions=dict(self.responses))
