"""Bounded local return detours using synthetic frontier observations only."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.memory import MemoryManager
from agent.protocol import Frontier
from agent.routes import RouteManager


class RouteDetoursTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'memory.sqlite3'
        self.m=MemoryManager(self.path)
        self.routes=RouteManager(self.m)
        self.s=SimpleNamespace(world='a'*64,dimension='minecraft:overworld',capabilities=['explore'],
                               player=SimpleNamespace(x=0.,y=64.,z=0.,danger=False,food=20),frontiers=[])
        self.destination=dict(x=40,y=64,z=0)

    def tearDown(self):
        self.m.close()
        self.tmp.cleanup()

    def request(self,*points):
        self.s.frontiers=[Frontier(x=x,y=64,z=z,safe=safe,path_length=length)
                          for x,z,safe,length in points]
        return self.routes.request(self.s,self.destination,'remembered-site','Retornar')

    def arrive(self,plan):
        # record is called by the engine only after verified arrival (covered in pipeline tests).
        self.routes.record(self.s,plan['params'],f'arrival-{len(self.m.rows("SELECT * FROM ReturnRoutes"))}')
        target=plan['params']['target']
        self.s.player.x=target['x']+.5
        self.s.player.z=target['z']+.5

    def restart(self):
        self.m.close()
        self.m=MemoryManager(self.path)
        self.routes=RouteManager(self.m)

    def test_lateral_then_forward_segments_are_reobserved(self):
        lateral=self.request((0,6,True,7))
        self.assertIsNotNone(lateral)
        self.assertFalse(json.loads(self.m.rows('SELECT history FROM ReturnRoutes')[0]['history']))
        self.arrive(lateral)
        forward=self.request((8,6,True,8))
        self.assertEqual(forward['params']['target']['x'],8)
        self.arrive(forward)
        # A known earlier segment is not a substitute for a current frontier.
        self.assertIsNone(self.request())

    def test_progress_is_preferred_to_a_safe_detour(self):
        plan=self.request((0,6,True,7),(8,0,True,8))
        self.assertEqual(plan['params']['target']['x'],8)

    def test_unsafe_far_away_and_long_paths_do_not_authorize_detours(self):
        self.assertIsNone(self.request((0,6,False,7),(-8,0,True,8),(0,8,True,16),(0,16,True,16)))
        self.assertEqual(self.m.rows('SELECT status FROM ReturnRoutes')[0]['status'],'blocked')

    def test_history_and_origin_prevent_loops_after_database_restart(self):
        self.arrive(self.request((0,6,True,7)))
        self.arrive(self.request((0,12,True,6)))
        self.restart()
        self.assertIsNone(self.request((0,6,True,6),(0,0,True,12)))

    def test_detour_budget_and_cooldown_persist_after_restart(self):
        with patch('agent.routes.time.time',return_value=100):
            for point in [(0,6,True,7),(0,12,True,6),(-1,15,True,4)]:
                self.arrive(self.request(point))
            self.assertIsNone(self.request((0,18,True,4)))
        self.restart()
        with patch('agent.routes.time.time',return_value=120):
            # Even an improving observation waits for the existing cooldown.
            self.assertIsNone(self.request((8,15,True,9)))
        with patch('agent.routes.time.time',return_value=161):
            self.assertIsNone(self.request((0,18,True,4)))
        with patch('agent.routes.time.time',return_value=222):
            self.assertIsNotNone(self.request((8,15,True,9)))

    def test_real_progress_resets_local_detour_budget(self):
        for point in [(0,6,True,7),(0,12,True,6),(-1,15,True,4),(8,15,True,9)]:
            self.arrive(self.request(point))
        self.assertIsNotNone(self.request((8,19,True,4)))

    def test_world_and_dimension_have_independent_routes_and_history(self):
        first=self.request((0,6,True,7))
        self.arrive(first)
        self.s.player.x=0.;self.s.player.z=0.
        self.s.dimension='minecraft:the_nether'
        other_dimension=self.request((0,6,True,7))
        self.assertNotEqual(first['params']['route'],other_dimension['params']['route'])
        self.s.world='b'*64
        other_world=self.request((0,6,True,7))
        self.assertNotEqual(other_dimension['params']['route'],other_world['params']['route'])

    def test_total_segment_bound_retains_all_visited_points(self):
        self.destination['x']=2000
        for i in range(1,65):
            self.arrive(self.request((i*8,0,True,8)))
        self.assertIsNone(self.request((520,0,True,8)))
        self.assertEqual(len(json.loads(self.m.rows('SELECT history FROM ReturnRoutes')[0]['history'])),64)

    def test_failed_frontier_is_not_reoffered_as_a_detour(self):
        plan=self.request((0,6,True,7))
        self.m.db.execute('INSERT INTO GoalPlans(goal_id,world,subject,category,kind,params,skill,attempts,created) '
                          'VALUES(?,?,?,?,?,?,?,?,?)',
                          ('failed-goal',self.s.world,plan['subject'],'return','explore','{}','explore_region',2,'fixture'))
        self.assertIsNone(self.request((0,6,True,7)))
