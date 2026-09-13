"""Intake schema (pydantic v2). One intake.yaml per project."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hydrostudy.geo.crs import parse_coordinate

AquiferName = Literal["Chicot", "Evangeline", "Burkeville", "Jasper", "Catahoula", "Other"]


class Interval(BaseModel):
    top_ft: float = Field(ge=-10)
    bottom_ft: float

    @model_validator(mode="after")
    def _order(self):
        if self.bottom_ft <= self.top_ft:
            raise ValueError(f"interval bottom ({self.bottom_ft}) must be below top ({self.top_ft})")
        return self

    @property
    def thickness_ft(self) -> float:
        return self.bottom_ft - self.top_ft


class BoreholeInterval(Interval):
    diameter_in: float = Field(gt=0)


class CasingInterval(Interval):
    diameter_in: float = Field(gt=0)
    wall_in: float | None = None
    material: str = "steel"


class ScreenInterval(Interval):
    diameter_in: float = Field(gt=0)
    material: str = "steel"
    slot_in: float | None = None


class CementInterval(Interval):
    method: str = "pressure cemented"


class LithologyInterval(Interval):
    description: str
    source: str | None = None


class SourceRef(BaseModel):
    kind: Literal["gam", "site_test", "literature", "district", "driller", "estimate"] = "gam"
    citation: str = ""
    model_version: str | None = None
    notes: str | None = None


class SiteTest(BaseModel):
    well_ref: str
    q_gpm: float = Field(gt=0)
    duration_hr: float = Field(gt=0)
    swl_ft: float
    pwl_ft: float
    r_w_ft: float = Field(gt=0)
    date: str | None = None
    tracking_no: str | None = None

    @model_validator(mode="after")
    def _dd(self):
        if self.pwl_ft <= self.swl_ft:
            raise ValueError("pumping level must be deeper than static level")
        return self


class AquiferParams(BaseModel):
    t_ft2d: float | None = Field(default=None, gt=0, description="stated T; if omitted and a site_test exists, T is derived")
    s: float = Field(gt=0, lt=1)
    k_ftd: float | None = Field(default=None, gt=0)
    source: SourceRef = SourceRef()


class Confinement(BaseModel):
    status: Literal["confined", "semi-confined", "unconfined", "unknown"] = "unknown"
    confining_unit: str | None = None
    thickness_ft: float | None = None
    source: str | None = None


class Aquifer(BaseModel):
    name: AquiferName
    top_ft_bgl: float | None = None
    bottom_ft_bgl: float | None = None
    source: str | None = None
    confinement: Confinement = Confinement()
    params: AquiferParams
    site_test: SiteTest | None = None
    lithology_summary: str | None = None

    @property
    def thickness_ft(self) -> float | None:
        if self.top_ft_bgl is None or self.bottom_ft_bgl is None:
            return None
        return self.bottom_ft_bgl - self.top_ft_bgl


class WellBase(BaseModel):
    id: str
    display_name: str | None = Field(default=None, description="how the well is named in the report, e.g. 'Well No. 2'")
    lat: float
    lon: float
    coord_datum: str = "WGS84"
    aquifer: AquiferName
    max_rate_gpm: float = Field(gt=0)
    total_depth_ft: float | None = Field(default=None, gt=0)
    screen: list[ScreenInterval] = []

    @property
    def label(self) -> str:
        return self.display_name or f"Well {self.id}"

    @field_validator("lat", mode="before")
    @classmethod
    def _lat(cls, v):
        return parse_coordinate(v, "lat")

    @field_validator("lon", mode="before")
    @classmethod
    def _lon(cls, v):
        lon = parse_coordinate(v, "lon")
        if lon > 0:
            raise ValueError("Texas longitudes are west and must be negative (e.g. -95.578)")
        return lon


class ProposedWell(WellBase):
    total_depth_ft: float = Field(gt=0)
    elevation_ft_msl: float | None = None
    elevation_source: str | None = None
    static_water_level_ft: float | None = None
    swl_source: str | None = None
    borehole: list[BoreholeInterval] = []
    casing: list[CasingInterval] = []
    cement: list[CementInterval] = []
    filter_pack: list[Interval] = []
    packer_depth_ft: float | None = None
    pump_setting_ft: float | None = None
    anticipated_lithology: list[LithologyInterval] = []
    r_w_ft: float | None = Field(default=None, gt=0, description="pumped-well evaluation radius; default borehole radius across screen")
    nearest_property_boundary_ft: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _construction(self):
        for s in self.screen:
            if s.bottom_ft > self.total_depth_ft + 1e-6:
                raise ValueError(f"screen bottom {s.bottom_ft} exceeds total depth {self.total_depth_ft}")
        if self.casing and self.screen:
            if max(c.bottom_ft for c in self.casing) > min(s.top_ft for s in self.screen) + 1e-6:
                raise ValueError("casing bottom must not extend below the top of the first screen")
        if self.cement and self.casing:
            if max(c.bottom_ft for c in self.cement) > max(c.bottom_ft for c in self.casing) + 1e-6:
                raise ValueError("cement interval must lie within the cased interval")
        for b in self.borehole:
            if b.bottom_ft > self.total_depth_ft + 1e-6:
                raise ValueError("borehole interval exceeds total depth")
        return self

    def effective_r_w_ft(self) -> float:
        if self.r_w_ft:
            return self.r_w_ft
        if self.screen and self.borehole:
            top = min(s.top_ft for s in self.screen)
            for b in self.borehole:
                if b.top_ft <= top < b.bottom_ft:
                    return b.diameter_in / 24.0
        if self.borehole:
            return min(b.diameter_in for b in self.borehole) / 24.0
        if self.screen:
            return max(s.diameter_in for s in self.screen) / 24.0
        return 0.5


class ExistingWell(WellBase):
    registration_no: str | None = None
    permit_no: str | None = None
    status: str = "Operating"
    include_in_system: bool = True
    r_w_ft: float | None = Field(default=None, gt=0)
    nearest_property_boundary_ft: float | None = Field(default=None, ge=0)

    def effective_r_w_ft(self) -> float:
        if self.r_w_ft:
            return self.r_w_ft
        if self.screen:
            return max(s.diameter_in for s in self.screen) / 24.0
        return 0.5


class Revision(BaseModel):
    number: int = 1
    reason: str | None = None


class ReportMeta(BaseModel):
    title: str
    date: str
    revision: Revision = Revision()
    issuing_firm: Literal["ballard", "reviewer", "generic"] = "ballard"
    addressee: dict | None = None
    salutation: str | None = None


class Applicant(BaseModel):
    name: str
    contact: str | None = None
    address: str | None = None
    pws_name: str | None = None
    pws_id: str | None = None
    system_name: str | None = None


class DistrictRef(BaseModel):
    id: str = "lsgcd"
    county: str
    rules_version: str | None = None
    verified_on: str | None = None


class Site(BaseModel):
    parcel_ids: list[str] = []
    boundary_geojson: str | None = None
    nearest_boundary_distance_ft: float | None = Field(default=None, ge=0)
    boundary_distance_source: str | None = None
    county_line_distance_mi: float | None = None
    description: str | None = None
    address: str | None = None


class Permit(BaseModel):
    annual_volume_gal: float = Field(gt=0)
    per_well_volumes_gal: dict[str, float] | None = None
    spacing_exception_requested: bool = False


class ScenarioConfig(BaseModel):
    include_24h: bool = True
    include_max_production: bool = True
    fixed_durations_days: list[float] = []
    fixed_duration_labels: list[str] = []
    include_single_well_subcases: bool = False


class AnalysisConfig(BaseModel):
    cone_edge_thresholds_ft: list[float] = [1.0, 5.0]
    contour_interval_ft: float = 5.0
    map_radius_mi: float = 1.0
    grid_points: int = 401
    scenarios: ScenarioConfig = ScenarioConfig()
    other_aquifer_wells: Literal["compute_and_flag", "na"] = "compute_and_flag"
    well_efficiency: float | None = Field(default=None, gt=0, le=1)


class DataFiles(BaseModel):
    manifest: str = "data/manifest.yaml"


# ---------------------------------------------------------------------------------------------------------------
# Post-drilling (Guidelines Section III)
# ---------------------------------------------------------------------------------------------------------------

class PumpSpec(BaseModel):
    diameter_in: float = Field(gt=0)
    setting_ft: float = Field(gt=0)
    hp: float | None = None
    make_model: str | None = None
    intake_depth_ft: float | None = None


class LogRecord(BaseModel):
    type: Literal["resistivity", "induction", "sp", "gamma", "spectral_gamma", "caliper", "sonic", "other"]
    curves: list[str] = []
    top_ft: float = 0
    bottom_ft: float = Field(gt=0)
    date: str | None = None
    las_file: str | None = None
    pdf_file: str | None = None
    open_hole: bool = True
    casing_at_log: Literal["open", "steel", "pvc"] = "open"
    contractor: str | None = None


class TestStep(BaseModel):
    rate_gpm: float = Field(gt=0)
    duration_min: float = Field(gt=0)


class ObservationWell(BaseModel):
    id: str
    distance_ft: float = Field(gt=0)


class AquiferTest(BaseModel):
    id: str
    kind: Literal["constant_rate", "step", "recovery"]
    rate_gpm: float | None = Field(default=None, gt=0)
    steps: list[TestStep] = []
    start: str | None = None
    duration_min: float | None = Field(default=None, gt=0)
    data_file: str
    r_w_ft: float = Field(gt=0)
    observation_well: ObservationWell | None = None
    swl_ft: float | None = None       # static level before this test (defaults to as_built.static_water_level_ft)
    notes: str | None = None

    @model_validator(mode="after")
    def _kind(self):
        if self.kind == "constant_rate" and self.rate_gpm is None:
            raise ValueError(f"test {self.id}: constant_rate test needs rate_gpm")
        if self.kind == "step" and len(self.steps) < 2:
            raise ValueError(f"test {self.id}: step test needs at least two steps")
        if self.kind == "recovery" and self.rate_gpm is None:
            raise ValueError(f"test {self.id}: recovery test needs the rate_gpm of the preceding pumping period")
        return self


class FieldParam(BaseModel):
    time: str
    sc_us_cm: float | None = None
    temp_c: float | None = None
    ph: float | None = None
    source: str | None = None


class AsBuiltConstruction(BaseModel):
    total_depth_ft: float = Field(gt=0)
    borehole: list[BoreholeInterval] = []
    casing: list[CasingInterval] = []
    blank_liner: list[CasingInterval] = []
    screen: list[ScreenInterval] = []
    cement: list[CementInterval] = []
    filter_pack: list[Interval] = []
    packer_depth_ft: float | None = None
    lithology: list[LithologyInterval] = []

    @model_validator(mode="after")
    def _geom(self):
        for s in self.screen:
            if s.bottom_ft > self.total_depth_ft + 1e-6:
                raise ValueError("as-built screen extends below total depth")
        for bl in self.blank_liner:
            for s in self.screen:
                if bl.top_ft < s.bottom_ft and s.top_ft < bl.bottom_ft:
                    raise ValueError("blank liner overlaps a screen interval")
        return self


class PreDrillingReference(BaseModel):
    title: str | None = None
    date: str | None = None
    analysis_json: str | None = None   # path to the pre-drilling build/analysis.json for comparison


class AsBuilt(BaseModel):
    well_id: str
    completion_date: str | None = None
    tdlr_tracking_no: str | None = None
    driller: str | None = None
    construction: AsBuiltConstruction
    static_water_level_ft: float
    swl_date: str | None = None
    pump: PumpSpec
    logs: list[LogRecord] = []
    tests: list[AquiferTest] = []
    field_params: list[FieldParam] = []
    rerun_interference: bool = True
    s_source: Literal["gam", "test"] = "gam"
    pre_drilling_report: PreDrillingReference | None = None


class Intake(BaseModel):
    schema_version: int = 1
    mode: Literal["lsgcd_pre_drilling", "feasibility", "lsgcd_post_drilling"] = "lsgcd_pre_drilling"
    report: ReportMeta
    applicant: Applicant
    district: DistrictRef
    site: Site = Site()
    aquifers: list[Aquifer]
    proposed_wells: list[ProposedWell]
    existing_wells: list[ExistingWell] = []
    permit: Permit
    analysis: AnalysisConfig = AnalysisConfig()
    data: DataFiles = DataFiles()
    as_built: AsBuilt | None = None

    @model_validator(mode="after")
    def _cross(self):
        if self.mode == "lsgcd_post_drilling":
            if self.as_built is None:
                raise ValueError("mode lsgcd_post_drilling requires an as_built block")
            if self.as_built.well_id not in {w.id for w in self.proposed_wells}:
                raise ValueError(f"as_built.well_id {self.as_built.well_id} is not a proposed well")
        names = {a.name for a in self.aquifers}
        for w in list(self.proposed_wells) + list(self.existing_wells):
            if w.aquifer not in names:
                raise ValueError(f"well {w.id} aquifer {w.aquifer} is not defined in aquifers[]")
        ids = [w.id for w in list(self.proposed_wells) + list(self.existing_wells)]
        if len(ids) != len(set(ids)):
            raise ValueError("well ids must be unique")
        if not self.proposed_wells:
            raise ValueError("at least one proposed well is required")
        return self

    def aquifer(self, name: str) -> Aquifer:
        for a in self.aquifers:
            if a.name == name:
                return a
        raise KeyError(name)

    @property
    def all_wells(self):
        return list(self.proposed_wells) + list(self.existing_wells)

    @property
    def system_rate_gpm(self) -> float:
        return sum(w.max_rate_gpm for w in self.proposed_wells) + sum(
            w.max_rate_gpm for w in self.existing_wells if w.include_in_system
        )
