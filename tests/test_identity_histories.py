"""Different verified synthetic histories in real temporary databases; never gameplay evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from agent.engine import CognitiveEngine
from agent.memory import MemoryManager
from agent.journal.writer import JournalWriter
from agent.protocol import Step

WORLD='a'*64
DIMENSION='minecraft:overworld'
CAPS=['approach','observe','explore','eat']


class FixtureClock:
    def __init__(self):self.value=100.
    def __call__(self):return self.value
    def advance(self):self.value+=3


class HistoryAgent:
    """Drive public engine steps, with time supplied through its documented clock argument."""
    def __init__(self,root):
        self.root=root;self.clock=FixtureClock();self.session=str(uuid4());self.seq=0
        self.memory=MemoryManager(root/'memory.sqlite3');self.restart()

    def restart(self):
        if hasattr(self,'engine'):
            self.memory.close();self.memory=MemoryManager(self.root/'memory.sqlite3')
        self.engine=CognitiveEngine(self.memory,JournalWriter(self.memory,self.root/'journals'),clock=self.clock)

    def frame(self,results=(),position=(0,64,0),**overrides):
        self.seq+=1;self.clock.advance()
        payload=dict(protocol=1,session=self.session,world=WORLD,dimension=DIMENSION,seq=self.seq,day=1,time=1000,
                     active=True,armed=True,capabilities=CAPS,blocks=[],results=list(results),
                     player=dict(x=position[0],y=position[1],z=position[2],health=20,food=20,danger=False,inventory={}))
        payload.update(overrides)
        return self.engine.step(Step(**payload))

    def result(self,command,evidence,**frame):
        return self.frame([dict(id=command['id'],status='success',reason='synthetic_verified_fixture',evidence=evidence)],**frame)

    def explore_history(self,count=80):
        for index in range(count):
            start=(index*8,64,0);target=dict(x=start[0]+8,y=64,z=0)
            command=self.frame(position=start,frontiers=[target|dict(safe=True,path_length=8)])['command']
            if command is None or command['action']!='explore':raise AssertionError('History did not execute explore')
            self.result(command,dict(target=target,server_verified=True,dimension=DIMENSION,
                                     position=dict(x=target['x']+.5,y=64,z=.5)),position=(target['x']+.5,64,.5))

    def observe_history(self):
        for index,material in enumerate(('stone','cobblestone','deepslate','granite','diorite','andesite',
                                         'coal_ore','iron_ore','sandstone','smooth_stone','stone_bricks','end_stone')):
            target=dict(x=2,y=64,z=index%3,id='minecraft:'+material)
            block=target|dict(log=False)
            approach=self.frame(blocks=[block])['command']
            if approach is None or approach['action']!='approach':raise AssertionError('History did not execute approach')
            pos={k:target[k] for k in ('x','y','z')}
            observe=self.result(approach,dict(target=pos,in_reach=True),blocks=[block])['command']
            if observe is None or observe['action']!='observe':raise AssertionError('History did not execute observe')
            self.result(observe,dict(target=pos,server_verified=True,after_block=target['id']))

    def competition(self,**overrides):
        return self.frame(blocks=[dict(x=2,y=64,z=0,id='minecraft:end_stone_bricks',log=False)],
                          frontiers=[dict(x=-1,y=64,z=0,safe=True,path_length=1)],**overrides)


class IdentityHistoriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.traveler=HistoryAgent(root/'traveler');self.researcher=HistoryAgent(root/'researcher')
        self.traveler.explore_history();self.researcher.observe_history()

    def tearDown(self):
        self.traveler.memory.close();self.researcher.memory.close();self.tmp.cleanup()

    def test_verified_histories_change_choices_and_survive_restart(self):
        for agent,kind,count,activity in ((self.traveler,'region_reached',80,'exploration'),(self.researcher,'observed',12,'observation')):
            physical=agent.memory.rows('SELECT id FROM Events WHERE type=? AND verified=1',(kind,))
            self.assertEqual(len(physical),count)
            for event in physical:
                self.assertTrue(agent.memory.rows('SELECT 1 FROM LifeMemories WHERE source_event=?',(event['id'],)))
                self.assertTrue(agent.memory.rows('SELECT 1 FROM PreferenceUpdates WHERE source=?',(event['id'],)))
                self.assertEqual(len(agent.memory.rows("SELECT 1 FROM PreferenceUpdates WHERE source=? AND category='activity' AND subject=?",
                                                       (event['id'],activity))),1)
        # Both options are new for both agents. Acquired activity preferences,
        # rather than assigned traits or a mocked response, resolve this conflict.
        for agent in (self.traveler,self.researcher):
            self.assertFalse(agent.memory.rows("SELECT 1 FROM Knowledge WHERE subject='observation:minecraft:end_stone_bricks'"))
        choices=[a.competition()['command']['action'] for a in (self.traveler,self.researcher)]
        self.assertEqual(choices,['explore','approach'])
        goals={g['kind']:g for g in self.traveler.engine.goals.rows(WORLD)}
        self.assertGreater(goals['observe']['priority'],goals['explore']['priority'])
        scores={}
        for kind,goal in goals.items():
            params=json.loads(goal['params'])
            self.assertEqual(self.traveler.engine.language.bonus(WORLD,kind,params,goal['subject']),0)
            self.assertEqual(self.traveler.engine.projects.bonus(self.traveler.engine.latest,kind,params),0)
            scores[kind]=goal['priority']+self.traveler.engine.identity.bonus(WORLD,kind,params)
        self.assertGreater(scores['explore'],scores['observe'])
        saved=[a.memory.rows('SELECT category,subject,weight,sources FROM Preferences ORDER BY category,subject')
               for a in (self.traveler,self.researcher)]
        for agent in (self.traveler,self.researcher):agent.restart()
        self.assertEqual([a.memory.rows('SELECT category,subject,weight,sources FROM Preferences ORDER BY category,subject')
                          for a in (self.traveler,self.researcher)],saved)
        self.assertEqual([a.competition()['command']['action'] for a in (self.traveler,self.researcher)],choices)
        traveler_values={r['subject']:r['weight'] for r in self.traveler.memory.rows("SELECT * FROM Preferences WHERE category='value'")}
        researcher_values={r['subject']:r['weight'] for r in self.researcher.memory.rows("SELECT * FROM Preferences WHERE category='value'")}
        self.assertGreater(traveler_values['exploration'],0)
        self.assertNotIn('exploration',researcher_values)

    def test_histories_never_override_danger_emergency_or_hunger(self):
        for agent in (self.traveler,self.researcher):
            for changes in (dict(player=dict(x=0,y=64,z=0,health=20,food=20,danger=True,inventory={})),
                            dict(control_state='EMERGENCY_STOP'),dict(armed=False),
                            dict(player=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory={}))):
                with self.subTest(agent=agent.root.name,changes=changes):self.assertIsNone(agent.competition(**changes)['command'])
            hungry=dict(x=0,y=64,z=0,health=20,food=4,danger=False,inventory={'minecraft:bread':2},
                        foods=[dict(id='minecraft:bread',slot=0,count=2,nutrition=5)])
            meal=agent.competition(player=hungry)['command']
            self.assertIsNotNone(meal);self.assertEqual(meal['action'],'eat')
            self.assertEqual(meal['food']['id'],'minecraft:bread')


if __name__=='__main__':unittest.main()
