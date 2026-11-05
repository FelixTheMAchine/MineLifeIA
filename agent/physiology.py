"""Optional, scoped server observations. These readings never authorize actions."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SensorModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class ThirstData(SensorModel):
    level: int = Field(ge=0, le=20)
    has_thirst: bool


class ThirstSensor(SensorModel):
    status: Literal['observed', 'not_installed', 'unsupported', 'unknown']
    mod_version: str | None = Field(max_length=128)
    api: Literal['dehydration:ThirstManagerAccess-v1.4.2']
    data: ThirstData | None

    @model_validator(mode='after')
    def observed_data(self):
        if (self.status == 'observed') != (self.data is not None):
            raise ValueError('Only observed sensors have data')
        if self.status == 'observed' and self.mod_version != '1.4.2':
            raise ValueError('Unsupported Dehydration version')
        if (self.status == 'not_installed') != (self.mod_version is None):
            raise ValueError('Installed sensor requires a version')
        return self


class TemperatureThresholds(SensorModel):
    maxVeryCold: int = Field(ge=-1000000, le=1000000)
    maxCold: int = Field(ge=-1000000, le=1000000)
    minCold: int = Field(ge=-1000000, le=1000000)
    normal: int = Field(ge=-1000000, le=1000000)
    minHot: int = Field(ge=-1000000, le=1000000)
    maxHot: int = Field(ge=-1000000, le=1000000)
    maxVeryHot: int = Field(ge=-1000000, le=1000000)

    @model_validator(mode='after')
    def ordered(self):
        values=list(self.model_dump().values())
        if any(a >= b for a,b in zip(values,values[1:])):
            raise ValueError('Temperature thresholds must be strictly ordered')
        return self


class TemperatureData(SensorModel):
    body: int = Field(ge=-1000000, le=1000000)
    unit: Literal['internal']
    thresholds: TemperatureThresholds
    heat_affected: bool
    cold_affected: bool
    ambient: None


class TemperatureSensor(SensorModel):
    status: Literal['observed', 'not_installed', 'unsupported', 'unknown']
    mod_version: str | None = Field(max_length=128)
    api: Literal['environmentz:EnvironmentzApi-v2.2.0']
    data: TemperatureData | None

    @model_validator(mode='after')
    def observed_data(self):
        if (self.status == 'observed') != (self.data is not None):
            raise ValueError('Only observed sensors have data')
        if self.status == 'observed' and self.mod_version != '2.2.0':
            raise ValueError('Unsupported EnvironmentZ version')
        if (self.status == 'not_installed') != (self.mod_version is None):
            raise ValueError('Installed sensor requires a version')
        return self


class Physiology(SensorModel):
    version: Literal[1]
    source: Literal['integrated_server']
    # UUIDs arrive as JSON strings inside Step.model_validate(), not JSON mode.
    session: str = Field(pattern=r'^[a-fA-F0-9-]{36}$')
    world: str = Field(pattern=r'^[a-f0-9]{64}$')
    dimension: str = Field(min_length=1, max_length=128)
    control_epoch: int = Field(ge=0)
    player_uuid: str = Field(pattern=r'^[a-fA-F0-9-]{36}$')
    sample_age_ms: int = Field(ge=0, le=2000)
    server_tick: int = Field(ge=0)
    thirst: ThirstSensor
    temperature: TemperatureSensor

    @field_validator('version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError('Version must be an integer')
        return value

    @model_validator(mode='after')
    def valid_ids(self):
        UUID(self.session)
        UUID(self.player_uuid)
        return self
