"""Social integration with real planner/SQLite and synthetic native server evidence."""
import copy
import unittest
from uuid import uuid4
import test_pipeline as base
from agent.engine import CognitiveEngine
from agent.social import SCREEN,MCA_VERSION


class SocialEngineTest(unittest.TestCase):
    setUp=base.PipelineTest.setUp
    tearDown=base.PipelineTest.tearDown
    step=base.PipelineTest.step
    success=base.PipelineTest.success
    person='11111111-1111-4111-8111-111111111111'
    player_uuid='22222222-2222-4222-8222-222222222222'

    def frame(self,results=None,**overrides):
        offer=dict(person_uuid=self.person,entity_type='mca:male_villager',name='Alex',x=2.,y=64.,z=0.,can_contact=True)
        payload=dict(blocks=[],social=[offer],capabilities=['social_observe','social_contact'],
                     player=dict(x=0.,y=64.,z=0.,health=20,food=20,danger=False,inventory={}))
        payload.update(overrides)
        self.engine.last_plan[payload.get('world',base.WORLD)]=-1e30
        return self.step(results,**payload)

    def proof(self,cmd):
        a=dict(person_uuid=self.person,entity_type='mca:male_villager',name='Alex',position=dict(x=2.,y=64.,z=0.),
               dimension='minecraft:overworld',alive=True,visible=True,distance=2.,player_uuid=self.player_uuid,
               inventory={},inventory_fingerprint='a'*64,main_hand='minecraft:air',off_hand='minecraft:air',interacting_player=None)
        b=copy.deepcopy(a)
        ev=dict(server_verified=True,person_uuid=self.person,entity_type='mca:male_villager',
                dimension='minecraft:overworld',before=a,after=b,
                target={k:cmd['target'][k] for k in ('x','y','z')})
        if cmd['action']=='social_contact':
            b['interacting_player']=self.player_uuid
            ev.update(interaction_accepted=True,mca_version=MCA_VERSION,
                      gui=dict(observed=True,screen_class=SCREEN,person_uuid=self.person))
        return ev

    def contacted_command(self):
        observe=self.frame()['command'];self.assertEqual(observe['action'],'social_observe')
        contact=self.frame([self.success(observe,self.proof(observe))])['command']
        self.assertEqual(contact['action'],'social_contact')
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'intent')
        return contact

    def test_real_pipeline_correlates_observation_contact_and_no_affinity(self):
        contact=self.contacted_command()
        response=self.frame([self.success(contact,self.proof(contact))])
        self.assertIsNone(response['command'])
        self.assertEqual(self.m.rows('SELECT relationship FROM SocialPeople')[0]['relationship'],'unknown')
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'confirmed')
        events=self.m.rows('SELECT e.type,c.command_id,e.dedup,e.world,e.session FROM SocialEncounters c JOIN Events e ON e.id=c.event_id')
        self.assertEqual({e['type'] for e in events},{'person_observed','social_contact'})
        self.assertTrue(all(e['dedup']==e['command_id'] and e['world']==base.WORLD and e['session']==self.session for e in events))
        for _ in range(100):self.assertIsNone(self.frame()['command'])
        self.assertEqual(len(self.m.rows('SELECT * FROM SocialEncounters')),2)

    def test_forged_gui_cannot_create_social_fact(self):
        contact=self.contacted_command();ev=self.proof(contact);ev['gui']['person_uuid']=str(uuid4())
        self.frame([self.success(contact,ev)])
        self.assertFalse(self.m.rows("SELECT * FROM Events WHERE type='social_contact'"))
        self.assertFalse(self.m.rows("SELECT * FROM SocialEncounters WHERE action='social_contact'"))
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'uncertain')

    def test_cancel_restart_and_fresh_observation_do_not_replay_contact(self):
        contact=self.contacted_command()
        self.frame([dict(id=contact['id'],status='cancelled',reason='emergency_stop',evidence={})],active=False,armed=False)
        self.engine=CognitiveEngine(self.m,self.writer);self.session=str(uuid4())
        observe=self.frame()['command'];self.assertEqual(observe['action'],'social_observe')
        self.assertIsNone(self.frame([self.success(observe,self.proof(observe))])['command'])
        self.assertEqual(len(self.m.rows('SELECT * FROM SocialAttempts')),1)
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'uncertain')

    def test_urgent_food_danger_f10_and_night_precede_social_work(self):
        response=self.frame(capabilities=['social_observe','social_contact','eat'],
                            player=dict(x=0.,y=64.,z=0.,health=20,food=4,danger=False,
                                        inventory={'minecraft:bread':1},foods=[dict(id='minecraft:bread',slot=0,count=1,nutrition=5)]))
        self.assertEqual(response['command']['action'],'eat')
        self.assertFalse(self.m.rows('SELECT * FROM SocialAttempts'))
        # Independent sessions after restart avoid a pending meal masking the safety gates.
        for overrides in (dict(active=False,armed=False),dict(time=13000),
                          dict(player=dict(x=0.,y=64.,z=0.,health=20,food=20,danger=True,inventory={}))):
            self.engine=CognitiveEngine(self.m,self.writer);self.session=str(uuid4())
            self.assertIsNone(self.frame(**overrides)['command'])
        self.assertFalse(self.m.rows('SELECT * FROM SocialEncounters'))

    def test_result_from_previous_world_cannot_be_attributed_to_new_world(self):
        observe=self.frame()['command']
        self.engine=CognitiveEngine(self.m,self.writer);self.session=str(uuid4())
        self.frame([self.success(observe,self.proof(observe))],world='b'*64,active=False,armed=False)
        self.assertFalse(self.m.rows('SELECT * FROM SocialPeople'))
