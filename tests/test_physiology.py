"""Strict sensor contract over synthetic readings; no gameplay evidence."""
import copy
import unittest
from uuid import uuid4
from pydantic import ValidationError
from agent.physiology import Physiology
from agent.protocol import Step


def fixture():
    return dict(version=1,source='integrated_server',session=str(uuid4()),world='a'*64,
                dimension='minecraft:overworld',control_epoch=2,player_uuid=str(uuid4()),
                sample_age_ms=0,server_tick=100,
                thirst=dict(status='observed',mod_version='1.4.2',
                            api='dehydration:ThirstManagerAccess-v1.4.2',data=dict(level=8,has_thirst=True)),
                temperature=dict(status='observed',mod_version='2.2.0',api='environmentz:EnvironmentzApi-v2.2.0',
                                 data=dict(body=0,unit='internal',heat_affected=True,cold_affected=False,ambient=None,
                                           thresholds=dict(maxVeryCold=-30,maxCold=-20,minCold=-10,normal=0,
                                                           minHot=10,maxHot=20,maxVeryHot=30))))


class PhysiologyTest(unittest.TestCase):
    def step(self,p):
        return dict(protocol=1,session=p['session'],world=p['world'],dimension=p['dimension'],
                    control_epoch=2,seq=1,day=1,time=0,active=True,armed=True,
                    player=dict(x=0,y=64,z=0,health=20,food=20,danger=False,inventory={}),
                    blocks=[],results=[],physiology=p)

    def test_thirst_bounds_and_strict_types(self):
        for value in (0,20):
            p=fixture();p['thirst']['data']['level']=value;Physiology.model_validate(p)
        for key,value in (('level',-1),('level',21),('level',True),('level','8'),
                          ('level',float('nan')),('level',float('inf')),('has_thirst',1)):
            with self.subTest(key=key,value=value),self.assertRaises(ValidationError):
                p=fixture();p['thirst']['data'][key]=value;Physiology.model_validate(p)

    def test_status_requires_data_and_pinned_version(self):
        for status,version in (('not_installed',None),('unsupported','9.0'),('unknown','1.4.2')):
            p=fixture();p['thirst'].update(status=status,mod_version=version,data=None)
            Physiology.model_validate(p)
            p['thirst']['data']=dict(level=10,has_thirst=True)
            with self.assertRaises(ValidationError):Physiology.model_validate(p)
        p=fixture();p['thirst']['mod_version']='9.0'
        with self.assertRaises(ValidationError):Physiology.model_validate(p)

    def test_scope_age_source_and_vanilla_compatibility(self):
        p=fixture();Step.model_validate(self.step(p))
        vanilla=self.step(p);vanilla.pop('physiology');Step.model_validate(vanilla)
        for key,value in (('world','b'*64),('session',str(uuid4())),('dimension','minecraft:the_nether'),
                          ('control_epoch',3),('sample_age_ms',2001),('sample_age_ms',-1),
                          ('server_tick',True),('source','client'),('version',True)):
            data=self.step(p);data['physiology']=copy.deepcopy(p);data['physiology'][key]=value
            with self.subTest(key=key),self.assertRaises(ValidationError):Step.model_validate(data)

    def test_temperature_never_assumes_celsius_ambient_or_ordered_defaults(self):
        p=fixture();Physiology.model_validate(p)
        for key,value in (('body',1000001),('body',-1000001),('body',True),('body',float('inf')),
                          ('heat_affected',0),('ambient',20),('unit','celsius')):
            p=fixture();p['temperature']['data'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValidationError):Physiology.model_validate(p)
        for key,value in (('normal',10),('maxCold',-30),('maxVeryHot',1000001),('maxHot','20')):
            p=fixture();p['temperature']['data']['thresholds'][key]=value
            with self.subTest(key=key),self.assertRaises(ValidationError):Physiology.model_validate(p)

    def test_temperature_absent_unsupported_and_unknown_are_not_observations(self):
        for status,version in (('not_installed',None),('unsupported','9.0'),('unknown','2.2.0')):
            p=fixture();p['temperature'].update(status=status,mod_version=version,data=None)
            Physiology.model_validate(p)
        p=fixture();p['temperature']['mod_version']='9.0'
        with self.assertRaises(ValidationError):Physiology.model_validate(p)
