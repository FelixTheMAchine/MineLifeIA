import json
import math
from agent.memory import now


def region(x, y, z):
    return math.floor(x / 8), math.floor(y / 16), math.floor(z / 8)


class ExplorationManager:
    def __init__(self, memory):
        self.m = memory
        self.last_region = {}

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
