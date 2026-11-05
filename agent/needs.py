"""Observed physiology and derived risk, separate from preferences and narrative.

The provider interface describes a future sensor adapter. No provider is enabled
here, and no missing sensor is inferred from a personality or language output.
"""
from typing import Mapping, Protocol, TypedDict, Literal


class NeedReading(TypedDict):
    status: Literal['observed','derived','unavailable']
    value: float | int | bool | None
    source: str | None
    unit: str | None
    scope: dict | None


class NeedsProvider(Protocol):
    name: str

    def readings(self, observation) -> Mapping[str, NeedReading]:
        """Supply measurements with explicit provenance and observation scope."""
        ...


def project_needs(observation, limits=(8,6)):
    s = observation
    scope = dict(world=s.world,dimension=s.dimension,session=str(s.session),seq=s.seq) if s else None

    def reading(value=None, status='unavailable', source=None, unit=None):
        return dict(status=status,value=value,source=source,unit=unit,scope=scope)

    physiology = {name:reading() for name in ('health','food','thirst','temperature','fatigue','comfort')}
    risk = {name:reading() for name in ('danger','health_critical','food_urgent','work_allowed')}
    rest = {name:reading() for name in ('night_rest_opportunity','vanilla_sleep_window')}
    if s:
        health_limit, food_limit = limits
        physiology['health'] = reading(s.player.health,'observed','vanilla.player.health','health_points')
        physiology['food'] = reading(s.player.food,'observed','vanilla.player.food','food_points')
        risk['danger'] = reading(s.player.danger,'observed','bridge.player.danger')
        risk['health_critical'] = reading(s.player.health<=health_limit,'derived','player.health + safety_limits')
        risk['food_urgent'] = reading(s.player.food<=food_limit,'derived','player.food + safety_limits')
        work = (s.active and s.armed and s.control_state!='EMERGENCY_STOP' and not s.player.danger
                and s.player.health>health_limit and s.player.food>food_limit)
        risk['work_allowed'] = reading(work,'derived','control + player.danger + safety_limits')
        rest['night_rest_opportunity'] = reading(s.time>=12000 and s.dimension=='minecraft:overworld','derived','vanilla.time + dimension')
        rest['vanilla_sleep_window'] = reading(s.time>=12542 and s.dimension=='minecraft:overworld','derived','vanilla.time + dimension')
    return dict(version=1,physiology=physiology,risk=risk,rest=rest,
                safety_limits=dict(health=limits[0],food=limits[1]),
                semantics=dict(physiology='Observed sensor values; missing sensors remain unavailable.',
                               risk='Derived constraints; not a physiological measurement.',
                               rest='Time opportunity; no measured fatigue.',
                               motivation='Selection scores are exposed separately in Motivations.',
                               preference='Evidence-linked preferences are exposed separately in Preferences.',
                               narrative='Interpretations are not sensor readings.'))
