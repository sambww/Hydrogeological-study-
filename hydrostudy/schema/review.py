"""review.yaml: the licensed reviewer's decisions and opinions. Null opinions become highlighted placeholders."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Reviewer(BaseModel):
    name: str | None = None
    title: str | None = None
    license_type: Literal["P.G.", "P.E."] | None = None
    license_no: str | None = None
    firm: str | None = None
    firm_registration_no: str | None = None
    status: Literal["draft", "reviewed", "final"] = "draft"
    authorization_date: str | None = None


class Decisions(BaseModel):
    t_ft2d: dict[str, float] | None = None       # aquifer name -> override
    s: dict[str, float] | None = None
    r_w_ft: dict[str, float] | None = None       # well id -> override
    cone_edge_thresholds_ft: list[float] | None = None
    other_aquifer_wells: Literal["compute_and_flag", "na"] | None = None


class Opinions(BaseModel):
    conclusion: str | None = None
    lithology_basis: str | None = None
    recharge_features: str | None = None
    confinement: str | None = None
    water_quality: str | None = None
    aquifer_identification: str | None = None
    parameter_selection: str | None = None
    spacing: str | None = None


class Review(BaseModel):
    reviewer: Reviewer = Reviewer()
    decisions: Decisions = Decisions()
    opinions: Opinions = Opinions()
    notes: list[str] = []
