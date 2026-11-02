from typing import Literal, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, model_validator


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
    bed: bool = False
    lit: bool = False


class Player(StrictModel):
    x: float
    y: float
    z: float
    health: float = Field(ge=0, le=2048)
    food: int = Field(ge=0, le=20)
    danger: bool
    inventory: dict[str, int]
    foods: list['FoodOffer'] = Field(default_factory=list, max_length=36)
    tools: list['ToolStatus'] = Field(default_factory=list, max_length=36)


class ToolStatus(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', max_length=128)
    slot: int = Field(ge=0, le=35)
    damage: int = Field(ge=0, le=100000)
    max_damage: int = Field(ge=1, le=100000)
    kind: Literal['pickaxe','axe','shovel','hoe','other']
    usable: bool


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


class SocialObservation(StrictModel):
    person_uuid: UUID
    entity_type: Literal['minecraft:villager','mca:male_villager','mca:female_villager']
    name: str = Field(min_length=1,max_length=96,pattern=r'^[^\x00-\x1f\x7f]+$')
    x: float
    y: float
    z: float
    can_contact: bool = False


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
    input_count: int = Field(default=1, ge=1, le=9)
    output_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    output_count: int = Field(ge=1, le=64)
    inputs: dict[Annotated[str,Field(pattern=r'^minecraft:[a-z0-9_]+$',max_length=128)],
                 Annotated[int,Field(strict=True,ge=1,le=9)]] = Field(default_factory=dict, max_length=9)
    grid: Literal[2, 3] = 2
    station: Pos | None = None

    @model_validator(mode='after')
    def validate_recipe(self):
        if self.inputs and (sum(self.inputs.values())>self.grid*self.grid
                            or self.inputs.get(self.input_id)!=self.input_count or self.output_id in self.inputs):
            raise ValueError('Alocação de ingredientes inválida')
        if self.grid==3 and (not self.inputs or self.station is None):
            raise ValueError('Receita 3x3 exige estação e ingredientes explícitos')
        if self.grid==2 and self.station is not None:
            raise ValueError('Receita 2x2 não deve anunciar bancada')
        return self


class PlacementSpot(Pos):
    support: Pos

    @model_validator(mode='after')
    def validate_support(self):
        if (self.support.x,self.support.y+1,self.support.z)!=(self.x,self.y,self.z):
            raise ValueError('Apoio deve estar imediatamente abaixo da posição')
        return self


class MiningOffer(Pos):
    id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    tool_id: str = Field(pattern=r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', max_length=128)
    tool_slot: int = Field(ge=0, le=35)
    tool_damage: int = Field(ge=0, le=100000)
    tool_max_damage: int = Field(ge=0, le=100000)
    tool_speed: float = Field(default=1, gt=0, le=1000)
    tool_suitable: bool = True
    tool_required: bool = True
    tool_wear: int = Field(default=1, ge=0, le=1)
    tool_material: str = Field(default='unknown', max_length=64)

    @model_validator(mode='after')
    def validate_durability(self):
        if self.tool_id=='minecraft:air':
            if self.tool_required or self.tool_damage or self.tool_max_damage or self.tool_wear or self.tool_slot>=9:
                raise ValueError('Mão vazia só serve para um alvo que dispensa ferramenta')
        elif self.tool_max_damage-self.tool_damage<3 or self.tool_wear!=1:
            raise ValueError('Ferramenta sem reserva de durabilidade')
        return self


class CookingOffer(StrictModel):
    id: str = Field(pattern=r'^minecraft:[a-z0-9_/]+$', max_length=128)
    input_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    output_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    cook_ticks: int = Field(ge=1, le=200)
    fuel_id: str | None = Field(default=None, pattern=r'^minecraft:[a-z0-9_]+$', max_length=128)
    fuel_ticks: int = Field(ge=0, le=20000)

    @model_validator(mode='after')
    def validate_fuel(self):
        if self.input_id==self.output_id or self.input_id==self.fuel_id or self.output_id==self.fuel_id:
            raise ValueError('Receita de cozimento inválida')
        if self.fuel_id is not None and self.fuel_ticks<self.cook_ticks:
            raise ValueError('Uma unidade de combustível não cobre esta receita')
        return self


class FarmlandObservation(Pos):
    moisture: int = Field(default=-1, ge=-1, le=7)
    water: Pos | None = None


class TillingOffer(Pos):
    id: Literal['minecraft:dirt', 'minecraft:grass_block']
    tool_id: str = Field(pattern=r'^minecraft:[a-z0-9_]+_hoe$', max_length=128)
    tool_slot: int = Field(ge=0, le=35)
    tool_damage: int = Field(ge=0, le=100000)
    tool_max_damage: int = Field(ge=1, le=100000)
    water: Pos

    @model_validator(mode='after')
    def validate_tilling(self):
        if self.tool_max_damage-self.tool_damage < 3:
            raise ValueError('Enxada sem reserva de durabilidade')
        if abs(self.water.x-self.x)>4 or abs(self.water.z-self.z)>4 or self.water.y not in (self.y,self.y+1):
            raise ValueError('Agua fora do alcance de hidratacao')
        return self


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
    capabilities: list[str] = Field(default_factory=lambda: ['approach', 'break', 'collect'], max_length=32)
    control_state: Literal['ACTIVE', 'PAUSED', 'EMERGENCY_STOP', 'DISCONNECTED', 'DISABLED'] | None = None
    control_epoch: int = Field(default=0, ge=0)
    biome: str = Field(default='unknown', max_length=128)
    frontiers: list[Frontier] = Field(default_factory=list, max_length=16)
    entities: list[str] = Field(default_factory=list, max_length=32)
    recipes: list[RecipeOffer] = Field(default_factory=list, max_length=32)
    items: list[ItemObservation] = Field(default_factory=list, max_length=24)
    placement_spots: list[PlacementSpot] = Field(default_factory=list, max_length=12)
    shelter_sites: list[Pos] = Field(default_factory=list, max_length=4)
    mining: list[MiningOffer] = Field(default_factory=list, max_length=16)
    cooking: list[CookingOffer] = Field(default_factory=list, max_length=16)
    farmland: list[FarmlandObservation] = Field(default_factory=list, max_length=12)
    tilling: list[TillingOffer] = Field(default_factory=list, max_length=12)
    storage: list[Pos] = Field(default_factory=list, max_length=8)
    social: list[SocialObservation] = Field(default_factory=list, max_length=8)
