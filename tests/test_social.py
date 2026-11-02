"""Synthetic social proofs against persistent SQLite; no Minecraft gameplay."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from uuid import uuid4

from agent.memory import MemoryManager
from agent.social import SocialManager,SCHEMA,SCREEN,MCA_VERSION


class SocialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'memory.sqlite'
        self.m=MemoryManager(self.path);self.m.db.executescript(SCHEMA);self.manager=SocialManager(self.m)
        self.person=str(uuid4());self.player=str(uuid4())
        self.offer=dict(person_uuid=self.person,entity_type='mca:male_villager',name='Alex',
                        x=2.,y=64.,z=0.,can_contact=True)
        self.s=NS(world='a'*64,dimension='minecraft:overworld',day=1,time=1000,seq=1,
                  session=str(uuid4()),active=True,armed=True,capabilities=['social_observe','social_contact'],
                  player=NS(x=0.,y=64.,z=0.,health=20,food=20,danger=False,inventory={}),social=[self.offer])

    def tearDown(self):
        self.m.close();self.tmp.cleanup()

    def command(self,proposal=None):
        proposal=proposal or self.manager.propose(self.s,{'curiosity':80})[0]
        return dict(id=str(uuid4()),action=proposal['kind'],**proposal['params'])

    def snapshot(self):
        return dict(person_uuid=self.offer['person_uuid'],entity_type=self.offer['entity_type'],name=self.offer['name'],
                    position=dict(x=self.offer['x'],y=self.offer['y'],z=self.offer['z']),dimension=self.s.dimension,
                    alive=True,visible=True,distance=2.,player_uuid=self.player,inventory={},
                    inventory_fingerprint='a'*64,main_hand='minecraft:air',off_hand='minecraft:air',interacting_player=None)

    def proof(self,cmd):
        a=self.snapshot();b=copy.deepcopy(a)
        ev=dict(server_verified=True,person_uuid=self.offer['person_uuid'],entity_type=self.offer['entity_type'],
                dimension=self.s.dimension,before=a,after=b)
        if cmd['action']=='social_contact':
            b['interacting_player']=self.player
            ev.update(interaction_accepted=True,mca_version=MCA_VERSION,
                      gui=dict(observed=True,screen_class=SCREEN,person_uuid=self.offer['person_uuid']))
        return ev

    def accept(self,cmd,ev=None):
        ev=ev or self.proof(cmd)
        kind='person_observed' if cmd['action']=='social_observe' else 'social_contact'
        eid=self.m.event(self.s.world,self.s.session,self.s.day,kind,'Synthetic fixture',True,ev,cmd['id'])
        self.manager.accept(self.s,cmd,ev,eid)
        return eid

    def observed(self):
        cmd=self.command();self.assertEqual(cmd['action'],'social_observe');self.accept(cmd)
        self.s.seq+=1

    def contact(self):
        self.observed();cmd=self.command();self.assertEqual(cmd['action'],'social_contact')
        self.manager.prepare_command(self.s,cmd)
        return cmd

    def test_observed_identity_and_familiarity_have_no_affinity(self):
        self.observed()
        self.offer['can_contact']=False
        self.assertEqual(self.manager.propose(self.s,{}),[])
        self.s.day=2;self.accept(self.command())
        row=self.m.rows('SELECT * FROM SocialPeople')[0]
        self.assertEqual(json.loads(row['observed_days']),[1,2]);self.assertEqual(row['relationship'],'unknown')
        self.assertNotIn('affinity',row)

    def test_same_name_different_uuid_and_changed_name_same_uuid(self):
        self.observed();self.offer['person_uuid']=str(uuid4());self.observed()
        self.assertEqual(len(self.m.rows('SELECT * FROM SocialPeople')),2)
        self.offer['name']='Renamed';self.s.day=2;self.observed()
        rows=self.m.rows('SELECT * FROM SocialPeople WHERE person_uuid=?',(self.offer['person_uuid'],))
        self.assertEqual(rows[0]['name'],'Renamed');self.assertEqual(len(rows),1)

    def test_world_and_dimension_are_not_inferred_from_other_world(self):
        self.observed();self.s.world='b'*64
        self.assertEqual(self.command()['action'],'social_observe');self.observed()
        self.assertEqual(len(self.m.rows('SELECT * FROM SocialPeople')),2)
        self.s.dimension='minecraft:the_nether'
        self.assertEqual(self.command()['action'],'social_observe')

    def test_observation_requires_unchanged_matching_server_snapshots(self):
        cmd=self.command();ev=self.proof(cmd)
        self.assertTrue(self.manager.validate(self.s,cmd,ev))
        for change in ('server','uuid','dimension','distance','dead','hidden','fingerprint','missing_state','changed'):
            bad=copy.deepcopy(ev)
            if change=='server':bad['server_verified']=False
            elif change=='uuid':bad['after']['person_uuid']=str(uuid4())
            elif change=='dimension':bad['dimension']='minecraft:the_nether'
            elif change=='distance':bad['before']['distance']=bad['after']['distance']=4
            elif change=='dead':bad['before']['alive']=bad['after']['alive']=False
            elif change=='hidden':bad['before']['visible']=bad['after']['visible']=False
            elif change=='fingerprint':bad['before']['inventory_fingerprint']=bad['after']['inventory_fingerprint']='fake'
            elif change=='missing_state':bad['before'].pop('interacting_player');bad['after'].pop('interacting_player')
            else:bad['after']['name']='Changed during read'
            with self.subTest(change=change):self.assertFalse(self.manager.validate(self.s,cmd,bad))

    def test_contact_requires_gui_transition_and_unchanged_inventory_components(self):
        cmd=self.contact();ev=self.proof(cmd)
        self.assertTrue(self.manager.validate(self.s,cmd,ev))
        for change in ('no_gui','wrong_person','wrong_screen','version','not_accepted','no_transition',
                       'other_player','inventory','components','held_item'):
            bad=copy.deepcopy(ev)
            if change=='no_gui':bad.pop('gui')
            elif change=='wrong_person':bad['gui']['person_uuid']=str(uuid4())
            elif change=='wrong_screen':bad['gui']['screen_class']='UnknownScreen'
            elif change=='version':bad['mca_version']='unknown'
            elif change=='not_accepted':bad['interaction_accepted']=False
            elif change=='no_transition':bad['after']['interacting_player']=None
            elif change=='other_player':bad['after']['interacting_player']=str(uuid4())
            elif change=='inventory':bad['after']['inventory']={'minecraft:emerald':1}
            elif change=='components':bad['after']['inventory_fingerprint']='b'*64
            else:bad['before']['main_hand']='minecraft:emerald'
            with self.subTest(change=change):self.assertFalse(self.manager.validate(self.s,cmd,bad))

    def test_contact_allows_moving_person_without_attributing_affinity(self):
        cmd=self.contact();ev=self.proof(cmd);ev['after']['position']['x']=2.2
        self.accept(cmd,ev)
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'confirmed')
        self.assertEqual(self.m.rows('SELECT relationship FROM SocialPeople')[0]['relationship'],'unknown')
        self.s.seq+=100
        self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_one_attempt_per_day_including_lost_cancelled_and_restart(self):
        cmd=self.contact();self.manager.interrupt(self.s,cmd)
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd)))
        self.m.close();self.m=MemoryManager(self.path);self.manager=SocialManager(self.m)
        self.s.session=str(uuid4());self.s.seq=1
        self.observed()
        self.assertEqual(self.manager.propose(self.s,{}),[])
        self.assertEqual(self.m.rows('SELECT status FROM SocialAttempts')[0]['status'],'uncertain')
        self.assertEqual(len(self.m.rows("SELECT * FROM SocialEncounters WHERE action='social_contact'")),0)
        self.s.day=2;self.observed()
        self.assertEqual(self.command()['action'],'social_contact')

    def test_same_day_duplicate_prepare_is_rejected_and_transaction_can_rollback(self):
        self.observed();self.m.db.commit();cmd=self.command()
        self.manager.prepare_command(self.s,cmd)
        with self.assertRaises(ValueError):self.manager.prepare_command(self.s,cmd)
        self.m.db.rollback()
        self.assertFalse(self.m.rows('SELECT * FROM SocialAttempts'))

    def test_contact_requires_prior_server_observation_and_fresh_offer(self):
        cmd=self.command();cmd['action']='social_contact'
        with self.assertRaises(ValueError):self.manager.prepare_command(self.s,cmd)
        self.observed();cmd=self.command();self.s.social=[]
        with self.assertRaises(ValueError):self.manager.prepare_command(self.s,cmd)
        self.s.social=[self.offer];self.offer['can_contact']=False
        self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_daylight_safety_capabilities_and_priority_bounds(self):
        for attr,value in (('food',12),('health',12),('danger',True)):
            old=getattr(self.s.player,attr);setattr(self.s.player,attr,value)
            self.assertEqual(self.manager.propose(self.s,{}),[]);setattr(self.s.player,attr,old)
        self.s.time=13000;self.assertEqual(self.manager.propose(self.s,{}),[]);self.s.time=1000
        self.s.active=False;self.assertEqual(self.manager.propose(self.s,{}),[]);self.s.active=True
        self.assertLessEqual(self.manager.propose(self.s,{'curiosity':1e6,'social':1e6})[0]['priority'],93)
        self.s.capabilities=[];self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_vanilla_observation_does_not_enable_mca_contact(self):
        self.offer['entity_type']='minecraft:villager';self.observed()
        self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_accept_requires_correlated_event_and_rejects_wrong_world_event(self):
        cmd=self.command();ev=self.proof(cmd)
        with self.assertRaises(ValueError):self.manager.accept(self.s,cmd,ev,str(uuid4()))
        eid=self.m.event('b'*64,self.s.session,1,'person_observed','Fixture',True,ev,cmd['id'])
        with self.assertRaises(ValueError):self.manager.accept(self.s,cmd,ev,eid)
        self.assertFalse(self.m.rows('SELECT * FROM SocialPeople'))

    def test_stable_person_does_not_repeat_observations_over_100_frames(self):
        self.offer['can_contact']=False;self.observed()
        for seq in range(2,102):
            self.s.seq=seq;self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_observation_can_approach_but_contact_needs_reach_and_new_observation_token(self):
        self.offer['x']=10.
        first=self.manager.propose(self.s,{})[0]
        self.assertEqual(first['kind'],'social_observe')
        self.offer['x']=2.;self.observed()
        self.s.seq+=25
        refreshed=self.manager.propose(self.s,{})[0]
        self.assertEqual(refreshed['kind'],'social_observe');self.assertNotEqual(first['subject'],refreshed['subject'])
        self.offer['x']=13.;self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_interruption_reconciles_once_even_if_cancellation_is_delivered_twice(self):
        cmd=self.contact();self.manager.interrupt(self.s,cmd)
        self.observed();self.manager.interrupt(self.s,cmd)
        for seq in range(10,110):
            self.s.seq=seq;self.assertEqual(self.manager.propose(self.s,{}),[])

    def test_lost_intent_survives_restart_and_cannot_claim_contact(self):
        cmd=self.contact()
        self.m.close();self.m=MemoryManager(self.path);self.manager=SocialManager(self.m)
        self.s.session=str(uuid4());self.s.seq=1
        self.assertFalse(self.manager.validate(self.s,cmd,self.proof(cmd)))
        self.observed();self.assertEqual(self.manager.propose(self.s,{}),[])
        self.assertEqual(len(self.m.rows('SELECT * FROM SocialAttempts')),1)
        self.assertEqual(len(self.m.rows("SELECT * FROM SocialEncounters WHERE action='social_contact'")),0)

    def test_event_of_other_command_cannot_supply_provenance(self):
        cmd=self.command();ev=self.proof(cmd)
        eid=self.m.event(self.s.world,self.s.session,1,'person_observed','Fixture',True,ev,str(uuid4()))
        with self.assertRaises(ValueError):self.manager.accept(self.s,cmd,ev,eid)
