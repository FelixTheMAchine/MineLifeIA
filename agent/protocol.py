from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Pos(StrictModel):
    x: int = Field(ge=-30000000, le=30000000)
    y: int = Field(ge=-2048, le=2048)
    z: int = Field(ge=-30000000, le=30000000)


class Block(Pos):
    id: str = Field(pattern=r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', max_length=128)
    log: bool
    harvestable: bool = False


class Player(StrictModel):
    x: float
    y: float
    z: float
    health: float = Field(ge=0, le=2048)
    food: int = Field(ge=0, le=20)
    danger: bool
    inventory: dict[str, int]
    foods: list['FoodOffer'] = Field(default_factory=list, max_length=9)


class FoodOffer(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', max_length=128)
    slot: int = Field(ge=0, le=35)
    count: int = Field(ge=1, le=64)
    nutrition: int = Field(ge=1, le=20)


class ItemObservation(StrictModel):
    entity_id: UUID
    x: float
    y: float
    z: float
    item_id: str = Field(pattern=r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', max_length=128)
    count: int = Field(ge=1, le=64)
    edible: bool


class Result(StrictModel):
    id: UUID
    status: Literal['success', 'failed', 'cancelled']
    reason: str = Field(max_length=200)
    evidence: dict = Field(default_factory=dict)


class Frontier(Pos):
    safe: bool
    path_length: int = Field(ge=1, le=64)


class RecipeOffer(StrictModel):
    id: str = Field(pattern=r'^minecraft:[a-z0-9_/]+$', max_length=128)
    input_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    input_count: int = Field(default=1, ge=1, le=4)
    output_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    output_count: int = Field(ge=1, le=64)


class Step(StrictModel):
    protocol: Literal[1]
    session: UUID
    world: str = Field(pattern=r'^[a-f0-9]{64}$')
    dimension: str = Field(max_length=128)
    seq: int = Field(ge=1)
    day: int = Field(ge=1)
    time: int = Field(ge=0, lt=24000)
    active: bool
    armed: bool
    player: Player
    blocks: list[Block] = Field(max_length=128)
    results: list[Result] = Field(max_length=64)
    running: UUID | None = None
    capabilities: list[str] = Field(default_factory=lambda: ['approach', 'break', 'collect'], max_length=16)
    control_state: Literal['ACTIVE', 'PAUSED', 'EMERGENCY_STOP', 'DISCONNECTED', 'DISABLED'] | None = None
    control_epoch: int = Field(default=0, ge=0)
    biome: str = Field(default='unknown', max_length=128)
    frontiers: list[Frontier] = Field(default_factory=list, max_length=16)
    entities: list[str] = Field(default_factory=list, max_length=32)
    recipes: list[RecipeOffer] = Field(default_factory=list, max_length=32)
    items: list[ItemObservation] = Field(default_factory=list, max_length=24)
