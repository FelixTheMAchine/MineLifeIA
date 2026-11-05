"""Sensor availability and shared safety thresholds, without real game execution."""
import json
import unittest

import test_pipeline as base
import test_projects as projects_base
from agent.needs import project_needs


class NeedsTest(unittest.TestCase):
    setUp = base.PipelineTest.setUp
    tearDown = base.PipelineTest.tearDown
    step = base.PipelineTest.step
    state = projects_base.ProjectsTest.state
    adopt = projects_base.ProjectsTest.adopt

    def test_missing_sensors_stay_unavailable_with_explicit_scope(self):
        s = self.state()
        needs = project_needs(s)
        for name in ('thirst','temperature','fatigue','comfort'):
            reading = needs['physiology'][name]
            self.assertEqual(reading['status'],'unavailable')
            self.assertIsNone(reading['value'])
            self.assertIsNone(reading['source'])
            self.assertEqual(reading['scope']['session'],str(s.session))
        self.assertEqual(needs['physiology']['health']['status'],'observed')
        self.assertEqual(needs['physiology']['food']['value'],20)
        self.assertEqual(needs['risk']['health_critical']['status'],'derived')

    def test_night_is_rest_opportunity_and_never_measured_fatigue(self):
        needs = project_needs(self.state(time=13000))
        self.assertTrue(needs['rest']['night_rest_opportunity']['value'])
        self.assertTrue(needs['rest']['vanilla_sleep_window']['value'])
        self.assertIsNone(needs['physiology']['fatigue']['value'])
        other = project_needs(self.state(time=13000,dimension='minecraft:the_nether'))
        self.assertFalse(other['rest']['vanilla_sleep_window']['value'])

    def test_without_observation_no_sensor_value_is_invented(self):
        needs = project_needs(None)
        for section in ('physiology','risk','rest'):
            for reading in needs[section].values():
                self.assertEqual(reading['status'],'unavailable')
                self.assertIsNone(reading['value'])
                self.assertIsNone(reading['scope'])
        self.assertIsNone(self.engine.snapshot()['needs']['physiology']['health']['value'])

    def test_custom_prudence_uses_same_thresholds_in_projection_motivation_and_projects(self):
        s,p = self.adopt()
        self.engine.motivation.initialize(s.world,str(s.session),s.day)
        values = self.engine.motivation.values(s.world)|dict(prudence=95)
        self.m.db.execute('UPDATE Personality SET values_json=? WHERE world=?',(json.dumps(values),s.world))
        limits = self.engine.motivation.safety_limits(s.world)
        self.assertEqual(limits,(11.5,9.5))
        marginal = self.state(player=dict(x=0,y=64,z=2,health=11,food=10,danger=False,inventory={}))
        needs = project_needs(marginal,limits)
        self.assertTrue(needs['risk']['health_critical']['value'])
        self.assertFalse(needs['risk']['work_allowed']['value'])
        dominant,_ = self.engine.motivation.evaluate(marginal,False,1)
        self.assertEqual(dominant,'SURVIVAL')
        dominant,_ = self.engine.motivation.evaluate(marginal,False,1,dict(score=120,eligible=True))
        self.assertEqual(dominant,'SURVIVAL')
        self.assertEqual(self.engine.projects.bonus(marginal,'craft',dict(recipe=dict(output_id='minecraft:oak_planks'))),0)
        hungry = self.state(player=dict(x=0,y=64,z=2,health=20,food=9,danger=False,inventory={}))
        self.assertTrue(project_needs(hungry,limits)['risk']['food_urgent']['value'])
        self.assertEqual(self.engine.projects.bonus(hungry,'craft',dict(recipe=dict(output_id='minecraft:oak_planks'))),0)

    def test_snapshot_exposes_observed_values_and_danger_preempts_project(self):
        s,p = self.adopt()
        response = self.step(blocks=[],player=dict(x=0,y=64,z=2,health=8,food=20,danger=False,inventory={}))
        self.assertIsNone(response['command'])
        self.assertEqual(response['control'],'pause')
        snapshot = self.engine.snapshot()
        self.assertEqual(snapshot['needs']['physiology']['health']['value'],8)
        self.assertEqual(snapshot['needs']['physiology']['health']['scope']['seq'],self.seq)
        self.assertFalse(snapshot['needs']['risk']['work_allowed']['value'])
        self.assertEqual(self.m.rows('SELECT status FROM LongProjects WHERE id=?',(p['id'],))[0]['status'],'suspended')


if __name__ == '__main__':
    unittest.main()
