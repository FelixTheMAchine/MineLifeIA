"""Deterministic planning against temporary memory and synthetic server evidence."""
import json
import time
import unittest
from uuid import uuid4

import test_pipeline as base
from life_metrics import LifeMetrics
from agent.engine import CognitiveEngine
from agent.journal.writer import JournalWriter
from agent.protocol import Step
from agent.memory import MemoryManager, now


class AdaptivePlanningTest(unittest.TestCase):
    setUp = base.PipelineTest.setUp
    tearDown = base.PipelineTest.tearDown
    step = base.PipelineTest.step
    success = base.PipelineTest.success

    def observation(self, **kwargs):
        payload = dict(protocol=1, session=self.session, world=base.WORLD,
                       dimension='minecraft:overworld', seq=1, day=1, time=1000,
                       active=True, armed=True, blocks=[], capabilities=['explore'], results=[],
                       player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={}))
        payload.update(kwargs)
        return Step(**payload)

    def trips(self, n, route=False, verified=True, correlated=True, dimension='minecraft:overworld'):
        for _ in range(n):
            cid = str(uuid4())
            command = dict(id=cid, action='explore', target=dict(x=9,y=64,z=0))
            if route:command['route'] = 'known-return'
            if correlated:
                result = json.dumps(dict(evidence=dict(dimension=dimension,server_verified=True)))
                self.m.db.execute('INSERT INTO Commands VALUES(?,?,?,?,?,?,?,?)',
                                  (cid,base.WORLD,self.session,'fixture',json.dumps(command),'success',result,now()))
            self.m.event(base.WORLD,self.session,1,'region_reached','Synthetic arrival',verified,
                         dict(dimension=dimension,server_verified=True),cid)

    def gain(self, subject, kind='observed'):
        eid = self.m.event(base.WORLD,self.session,1,kind,'Synthetic new knowledge',True,
                           dict(dimension='minecraft:overworld'),str(uuid4()))
        self.m.db.execute("INSERT INTO Knowledge VALUES(?,?,'confirmed',?) ON CONFLICT(world,subject) "
                          'DO UPDATE SET evidence_ids=excluded.evidence_ids', (base.WORLD,subject,json.dumps([eid])))
        return eid

    def test_three_verified_trips_reduce_activity_and_survive_restart(self):
        position = dict(x=0.,y=64.,z=0.)
        pending = []
        for cycle in range(4):
            self.engine.last_plan[base.WORLD] = -1e30
            response = self.step(pending,blocks=[],capabilities=['explore'],
                                 frontiers=[dict(x=int(position['x'])-12,y=64,z=0,safe=True,path_length=12)],
                                 player=dict(**position,health=20,food=20,danger=False,inventory={}))
            command = response['command']
            if cycle == 3:
                self.assertIsNone(command)
                break
            self.assertEqual(command['action'],'explore')
            target = {k:command['target'][k] for k in ('x','y','z')}
            position = dict(x=target['x']+.5,y=64.,z=.5)
            pending = [self.success(command,dict(target=target,position=position,
                                                 server_verified=True,dimension='minecraft:overworld'))]
        score = json.loads(self.m.rows("SELECT reason FROM Motivations WHERE name='EXPLORATION'")[0]['reason'])
        self.assertEqual(score['history']['unproductive_trips'],3)
        self.assertAlmostEqual(score['score'],sum(score['components'].values()),places=2)
        self.assertFalse(score['eligible'])
        self.engine = CognitiveEngine(self.m,self.writer)
        self.session = str(uuid4())
        response = self.step(blocks=[],capabilities=['explore'],
                             frontiers=[dict(x=int(position['x'])-12,y=64,z=0,safe=True,path_length=12)],
                             player=dict(**position,health=20,food=20,danger=False,inventory={}))
        self.assertIsNone(response['command'])
        self.assertIn('Baixa atividade',self.engine.reason)

    def test_only_correlated_free_exploration_counts(self):
        self.trips(2)
        self.trips(3,route=True)
        self.trips(3,verified=False)
        self.trips(3,correlated=False)
        self.trips(3,dimension='minecraft:the_nether')
        self.assertEqual(self.engine.exploration.yield_history(self.observation())['unproductive_trips'],2)

    def test_new_knowledge_renews_yield_but_repeated_evidence_does_not(self):
        first = self.gain('observation:minecraft:stone')
        self.trips(5)
        s = self.observation()
        target = dict(x=9,y=64,z=0)
        self.assertFalse(self.engine.exploration.score(s,9,target)['eligible'])
        repeated = self.m.event(base.WORLD,self.session,1,'observed','Repeated',True,
                                dict(dimension='minecraft:overworld'),str(uuid4()))
        self.m.db.execute('UPDATE Knowledge SET evidence_ids=?', (json.dumps([first,repeated]),))
        self.assertFalse(self.engine.exploration.score(s,9,target)['eligible'])
        self.gain('recipe:minecraft:torch','crafted')
        self.assertTrue(self.engine.exploration.score(s,9,target)['eligible'])

    def test_costs_opportunities_and_bounded_temporal_recovery_are_explicit(self):
        self.trips(5)
        s = self.observation()
        target = dict(x=9,y=64,z=0)
        recent = self.engine.exploration.score(s,9,target)
        self.assertFalse(recent['eligible'])
        history = self.engine.exploration.yield_history(s)
        self.engine.exploration.clock = lambda:time.time()+91
        recovered = self.engine.exploration.score(s,9,target)
        self.assertTrue(recovered['eligible'])
        self.assertEqual(recovered['history']['unproductive_trips'],history['unproductive_trips'])
        self.assertEqual(recovered['components']['recovery'],48)
        far = self.engine.exploration.score(s,14,target)
        self.assertLess(far['score'],recovered['score'])
        risky = self.observation(player=dict(x=0,y=64,z=0,health=10,food=10,danger=False,inventory={}))
        self.assertLess(self.engine.exploration.score(risky,9,target)['score'],recovered['score'])
        novel = self.observation(blocks=[dict(x=9,y=64,z=0,id='minecraft:diamond_ore',log=False)])
        self.assertGreater(self.engine.exploration.score(novel,9,target)['components']['utility'],0)

    def test_narrative_bonus_cannot_override_inactivity(self):
        self.trips(5)
        self.engine.language.bonus = lambda *args:1e9
        self.engine.mind.bonus = lambda *args:1e9
        response = self.step(blocks=[],capabilities=['explore'],
                             frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)])
        self.assertIsNone(response['command'])

    def test_competing_observed_goals_record_selection_without_claiming_outcome(self):
        response = self.step(blocks=[dict(x=2,y=64,z=0,id='minecraft:stone',log=False)],
                             capabilities=['approach','observe','explore'],
                             frontiers=[dict(x=9,y=64,z=0,safe=True,path_length=9)])
        command = response['command']
        self.assertIsNotNone(command)
        selections = self.m.rows("SELECT * FROM Events WHERE type='goal_selected'")
        self.assertEqual(len(selections),1)
        event = selections[0]
        evidence = json.loads(event['evidence'])
        self.assertEqual((event['world'],event['session']),(base.WORLD,self.session))
        self.assertEqual(evidence['command'],command['id'])
        self.assertEqual(evidence['observation_seq'],1)
        observed=self.m.rows('SELECT world,session,seq FROM Observations WHERE id=?',(evidence['observation_id'],))
        self.assertEqual(observed[0],dict(world=base.WORLD,session=self.session,seq=1))
        self.assertFalse(evidence['mind_influenced'])
        self.assertEqual(evidence['mode'],'ranked')
        self.assertGreaterEqual(len(evidence['alternatives']),2)
        self.assertEqual(evidence['alternatives'][0]['goal'],evidence['goal'])
        self.assertIn('prior_cognitive',evidence['alternatives'][0]['components'])
        self.assertIn('learned_preferences',evidence['alternatives'][0]['components'])
        self.assertNotIn('memory',evidence['alternatives'][0]['components'])
        self.assertEqual(evidence['alternatives'][0]['total'],
                         sum(evidence['alternatives'][0]['components'].values()))
        self.assertEqual(self.engine.snapshot()['goal_selection']['command'],command['id'])
        context=self.engine.language.context(self.engine.latest,self.engine.goals.rows(base.WORLD),{},[])
        self.assertNotIn(event['id'],{fact['id'] for fact in context['facts']})
        metrics=LifeMetrics(self.m,base.WORLD).report()
        self.assertEqual(metrics['goal_selections'],1)
        self.assertEqual(metrics['uncorrelated_goal_selections'],0)
        self.assertEqual(metrics['mind_changed_choices'],0)
        self.m.event(base.WORLD,self.session,1,'goal_selected','Uncorrelated synthetic decision',True,
                     dict(goal=evidence['goal'],command='missing-command',alternatives=[]),'invalid-selection-fixture')
        self.assertEqual(LifeMetrics(self.m,base.WORLD).report()['uncorrelated_goal_selections'],1)
        self.m.event(base.WORLD,self.session,1,'goal_selected','Missing synthetic observation',True,
                     dict(goal=evidence['goal'],command=command['id'],observation_id='missing-observation',
                          observation_seq=1,alternatives=[]),'missing-observation-fixture')
        self.assertEqual(LifeMetrics(self.m,base.WORLD).report()['uncorrelated_goal_selections'],2)
        older=self.m.event(base.WORLD,self.session,1,'goal_selected','Older synthetic observation',True,
                           dict(goal=evidence['goal'],command=command['id'],
                                observation_id='older-missing-observation',observation_seq=1,
                                alternatives=[]),'older-observation-fixture')
        self.m.db.execute("UPDATE Events SET timestamp='2000-01-01T00:00:00+00:00' WHERE id=?",(older,))
        measured=LifeMetrics(self.m,base.WORLD).report()
        self.assertEqual(measured['older_missing_goal_observations'],1)
        self.assertEqual(measured['uncorrelated_goal_selections'],2)
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='experiment_completed'"))

    def test_urgent_food_selection_is_direct_without_fabricated_comparison(self):
        food=dict(id='minecraft:bread',slot=0,count=1,nutrition=5)
        response=self.step(blocks=[],capabilities=['eat'],
                           player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,
                                       inventory={'minecraft:bread':1},foods=[food]))
        command=response['command']
        self.assertEqual(command['action'],'eat')
        selection=self.engine.snapshot()['goal_selection']
        self.assertEqual(selection['command'],command['id'])
        self.assertEqual(selection['mode'],'direct')
        self.assertIsNone(selection['baseline'])
        self.assertEqual(selection['alternatives'],[])
        self.assertFalse(selection['mind_influenced'])
        self.assertEqual(LifeMetrics(self.m,base.WORLD).report()['goal_selections'],1)

    def test_decision_on_unsampled_frame_persists_its_observation(self):
        self.assertIsNone(self.step(blocks=[],capabilities=[])['command'])
        self.engine.last_plan[base.WORLD]=-1e30
        command=self.step(blocks=[dict(x=2,y=64,z=0,id='minecraft:stone',log=False)],
                          capabilities=['approach','observe'])['command']
        self.assertIsNotNone(command)
        selection=self.engine.snapshot()['goal_selection']
        self.assertEqual(selection['observation_seq'],2)
        observation=self.m.rows('SELECT * FROM Observations WHERE id=?',(selection['observation_id'],))[0]
        self.assertEqual((observation['world'],observation['session'],observation['seq']),
                         (base.WORLD,self.session,2))
        self.assertEqual(LifeMetrics(self.m,base.WORLD).report()['uncorrelated_goal_selections'],0)
        self.m.db.commit();self.m.close()
        self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        self.assertEqual(self.m.rows('SELECT seq FROM Observations WHERE id=?',
                                     (selection['observation_id'],))[0]['seq'],2)
        self.assertEqual(LifeMetrics(self.m,base.WORLD).report()['goal_selections'],1)

    def test_restart_rejects_reusing_session_in_another_world(self):
        self.step(blocks=[],capabilities=[])
        self.m.db.commit();self.m.close()
        self.m=MemoryManager(self.root/'data'/'memory.sqlite3')
        self.writer=JournalWriter(self.m,self.root/'journals')
        self.engine=CognitiveEngine(self.m,self.writer)
        foreign=self.observation(world='b'*64,seq=2)
        with self.assertRaisesRegex(ValueError,'Sessão já vinculada'):
            self.engine.step(foreign)
        self.assertEqual(self.m.rows('SELECT DISTINCT world FROM Observations WHERE session=?',
                                     (self.session,)),[dict(world=base.WORLD)])

    def test_available_crafting_wins_during_quiet_and_learning_reopens_exploration(self):
        self.trips(5)
        recipe = dict(id='minecraft:birch_planks',input_id='minecraft:birch_log',input_count=1,
                      output_id='minecraft:birch_planks',output_count=4)
        frontier = dict(x=9,y=64,z=0,safe=True,path_length=9)
        command = self.step(blocks=[],capabilities=['craft','explore'],recipes=[recipe],frontiers=[frontier],
                            player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:birch_log':1}))['command']
        self.assertEqual(command['action'],'craft')
        proof = dict(target={k:command['target'][k] for k in ('x','y','z')},server_verified=True,
                     recipe=recipe['id'],crafted_delta=4,inventory_before={'minecraft:birch_log':1},
                     inventory_after={'minecraft:birch_planks':4})
        response = self.step([self.success(command,proof)],blocks=[],capabilities=['craft','explore'],frontiers=[frontier],
                             player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={'minecraft:birch_planks':4}))
        self.assertEqual(response['command']['action'],'explore')
        history = self.engine.exploration.yield_history(self.observation())
        self.assertEqual(history['unproductive_trips'],0)
        self.assertEqual(history['skill_gains'],1)

    def test_other_dimension_learning_and_partial_removal_do_not_reset_local_yield(self):
        self.trips(5)
        eid = self.m.event(base.WORLD,self.session,1,'observed','Other dimension',True,
                           dict(dimension='minecraft:the_nether'),str(uuid4()))
        self.m.db.execute("INSERT INTO Knowledge VALUES(?,?,'confirmed',?)",(base.WORLD,'other',json.dumps([eid])))
        self.gain('partial','block_removed')
        self.assertEqual(self.engine.exploration.yield_history(self.observation())['unproductive_trips'],5)

    def test_deferred_slots_preserve_parameters_and_equivalent_targets_share_goal(self):
        s = self.observation()
        self.engine.goals.max_active = 1
        gid = self.engine.goals.ensure(s,'stale','Old acquisition','Observed',100,'pickup',
                                       dict(acquisition_goal='durable-intent',target=dict(x=1,y=64,z=0)), 'pickup_item')
        self.engine.goals.begin_cycle(s.world)
        params = json.loads(self.m.rows('SELECT params FROM GoalPlans WHERE goal_id=?',(gid,))[0]['params'])
        self.assertEqual(params['acquisition_goal'],'durable-intent')
        first = self.engine.goals.ensure(s,'explore:'+s.dimension+':first','Explore','Observed',60,'explore',
                                         dict(target=dict(x=9,y=64,z=0)), 'explore_region')
        second = self.engine.goals.ensure(s,'explore:'+s.dimension+':second','Explore','Observed',60,'explore',
                                          dict(target=dict(x=10,y=64,z=0)), 'explore_region')
        self.assertIsNotNone(first)
        self.assertEqual(first,second)
        self.assertEqual(self.m.rows("SELECT count(*) n FROM Goals WHERE status='pending'")[0]['n'],1)


if __name__ == '__main__':
    unittest.main()
