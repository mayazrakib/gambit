from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class ExplorerOptions(BaseModel,):
    model_config = ConfigDict(
        extra='forbid',
        strict=True,
    )

    population: Literal[
        'masters',
        'lichess',
    ] = 'masters'

    since: str | None = None
    until: str | None = None

    speeds: list[Literal[
        'ultraBullet',
        'bullet',
        'blitz',
        'rapid',
        'classical',
        'correspondence',
    ]] | None = None

    ratings: list[Literal[
        0,
        1000,
        1200,
        1400,
        1600,
        1800,
        2000,
        2200,
        2500,
    ]] | None = None

    limit: int = Field(
        default=8,
        ge=1,
        le=20,
    )

    example_limit: int = Field(
        default=2,
        ge=0,
        le=4,
    )

class Outcomes(BaseModel,):
    model_config = ConfigDict(
        extra='ignore',
        strict=True,
    )

    white: int = Field(ge=0,)
    draws: int = Field(ge=0,)
    black: int = Field(ge=0,)

def validate_optional_integer(value: object,) -> int | None:
    if value is not None and type(value,) is not int:
        raise ValueError('Provider numeric evidence must use integer units or null.',)

    return value
