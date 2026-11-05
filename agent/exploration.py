import json
import math
import time
from datetime import datetime
from agent.memory import now


def region(x, y, z):
    return math.floor(x / 8), math.floor(y / 16), math.floor(z / 8)


class ExplorationManager:
    ACTIVITY_THRESHOLD = 35
    RECOVERY_SECONDS = 90

    def __init__(self, memory, clock=time.time):
        self.m = memory
        self.clock = clock
        self.last_region = {}

    def yield_history(self, s):
        """Count verified travel since new knowledge, a new skill or a project outcome.

        Event order is durable across sessions. Repeated evidence for the same
        knowledge/skill does not renew curiosity, nor does visiting another cell.
        """
        # Aggregate inside SQLite: persistent lives must not copy every event or
        # command payload into the planner on every cycle. Gains are local to
        # the current dimension; partial removal evidence is not a discovery.
        row = self.m.rows("""
            WITH knowledge_gains AS (
              SELECT k.subject,min(e.rowid) ordinal FROM Knowledge k
              JOIN json_each(k.evidence_ids) proof JOIN Events e ON e.id=proof.value
              WHERE k.world=:world AND e.world=k.world AND k.status='confirmed'
                AND k.subject!='exploration' AND e.verified=1
                AND e.type NOT IN ('region_reached','block_removed','attempt_failed')
                AND json_extract(e.evidence,'$.dimension')=:dimension GROUP BY k.subject
            ), skill_gains AS (
              SELECT p.skill,min(e.rowid) ordinal FROM GoalPlans p
              JOIN ExperimentGoals x ON x.goal_id=p.goal_id
              JOIN Experiments exp ON exp.id=x.experiment AND exp.world=p.world
              JOIN json_each(exp.evidence_ids) proof JOIN Events e ON e.id=proof.value
              WHERE p.world=:world AND e.world=p.world AND exp.status='completed'
                AND p.skill!='explore_region' AND e.verified=1
                AND json_extract(e.evidence,'$.dimension')=:dimension GROUP BY p.skill
            ), project_gains AS (
              SELECT json_extract(e.evidence,'$.project') project,min(e.rowid) ordinal
              FROM Events e WHERE e.world=:world AND e.verified=1 AND e.type='shelter_completed'
                AND json_extract(e.evidence,'$.server_verified')=1
                AND json_extract(e.evidence,'$.dimension')=:dimension
                AND json_extract(e.evidence,'$.project') IS NOT NULL GROUP BY project
            ), gains AS (
              SELECT ordinal FROM knowledge_gains UNION ALL SELECT ordinal FROM skill_gains
              UNION ALL SELECT ordinal FROM project_gains
            ), last_gain AS (SELECT coalesce(max(ordinal),0) ordinal FROM gains), travel AS (
              SELECT e.rowid ordinal,e.timestamp FROM Events e JOIN Commands c
                ON c.id=e.dedup AND c.world=e.world AND c.session=e.session
              WHERE e.world=:world AND e.verified=1 AND e.type='region_reached'
                AND e.rowid>(SELECT ordinal FROM last_gain) AND c.status='success'
                AND json_extract(c.payload,'$.action')='explore'
                AND json_extract(c.payload,'$.route') IS NULL
                AND json_extract(e.evidence,'$.dimension')=:dimension
                AND json_extract(e.evidence,'$.server_verified')=1
                AND json_extract(c.result,'$.evidence.dimension')=:dimension
                AND json_extract(c.result,'$.evidence.server_verified')=1
            ) SELECT (SELECT count(*) FROM travel) unproductive_trips,
                (SELECT timestamp FROM travel ORDER BY ordinal DESC LIMIT 1) last_trip,
                (SELECT ordinal FROM last_gain) last_gain_ordinal,
                (SELECT count(*) FROM knowledge_gains) knowledge_gains,
                (SELECT count(*) FROM skill_gains) skill_gains,
                (SELECT count(*) FROM project_gains) project_gains
            """, dict(world=s.world,dimension=s.dimension))[0]
        stamp = row.pop('last_trip')
        row['seconds_since_trip'] = round(max(0., self.clock()-datetime.fromisoformat(stamp).timestamp()),2) if stamp else 0.
        return row

    def score(self, s, length, target, history=None):
        history = history if history is not None else self.yield_history(s)
        known = {r['subject'] for r in self.m.rows("SELECT subject FROM Knowledge WHERE world=? AND status='confirmed'", (s.world,))}
        # A nearby observed unknown is a concrete investigation opportunity.
        unknowns = {b.id for b in s.blocks if b.id not in known and 'observation:'+b.id not in known
                    and math.dist((b.x,b.y,b.z), (target['x'],target['y'],target['z'])) <= 6}
        components = dict(curiosity=80., utility=min(40., len(unknowns)*20.),
                          diminishing_returns=-min(80., history['unproductive_trips']*16.),
                          recovery=min(48., history['unproductive_trips']*16., history['seconds_since_trip']*48./self.RECOVERY_SECONDS),
                          distance_cost=-max(0., float(length))*.5,
                          risk_cost=-max(0., 20-s.player.health)*2.-max(0., 20-s.player.food))
        score = round(sum(components.values()), 2)
        return dict(score=score, threshold=self.ACTIVITY_THRESHOLD,
                    eligible=score >= self.ACTIVITY_THRESHOLD, components=components,
                    history=history, observed_opportunities=sorted(unknowns))

    def record(self, s):
        key = region(s.player.x, s.player.y, s.player.z)
        previous = self.last_region.get((s.world, s.dimension))
        visits = int(previous != key)
        resources = sorted({b.id for b in s.blocks})
        known = {r['subject'] for r in self.m.rows("SELECT subject FROM Knowledge WHERE world=? AND status='confirmed'", (s.world,))}
        unknown = [item for item in resources if item not in known and 'observation:' + item not in known]
        self.m.db.execute('INSERT INTO SpatialRegions VALUES(?,?,?,?,?,?,?,?,?,?,?,?) '
                          'ON CONFLICT(world,dimension,rx,ry,rz) DO UPDATE SET '
                          'visits=visits+excluded.visits,biome=excluded.biome,resources=excluded.resources,'
                          'dangers=excluded.dangers,unknowns=excluded.unknowns,interests=excluded.interests,last_visit=excluded.last_visit',
                          (s.world, s.dimension, *key, visits, s.biome, json.dumps(resources),
                           json.dumps(['danger'] if s.player.danger else []), json.dumps(unknown),
                           json.dumps(['discovery'] if unknown else ['exploration']), now()))
        self.last_region[(s.world, s.dimension)] = key

    def candidates(self, s):
        visited = {(r['rx'], r['ry'], r['rz']) for r in self.m.rows(
            'SELECT rx,ry,rz FROM SpatialRegions WHERE world=? AND dimension=?', (s.world, s.dimension))}
        current = region(s.player.x, s.player.y, s.player.z)
        result = []
        for f in s.frontiers:
            key = region(f.x + .5, f.y, f.z + .5)
            if not f.safe or key in visited or key == current:
                continue
            if math.dist((s.player.x, s.player.y, s.player.z), (f.x+.5, f.y, f.z+.5)) > 15:
                continue
            target = dict(x=f.x, y=f.y, z=f.z, id='minecraft:air')
            result.append((f.path_length, key, target))
        return sorted(result, key=lambda c: (c[0], c[1]))
