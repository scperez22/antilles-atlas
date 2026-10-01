"""Response shapes for the API. Read-only; nothing here is accepted as input."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class YearRange(BaseModel):
    """Half-open [start, end): end is the first year NOT included."""
    start: int | None
    end: int | None


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    name: str
    kind: str


class ClaimSummary(BaseModel):
    key: str
    assertion: str
    kind: str
    subject: EntityOut | None
    when_label: str | None
    when_range: YearRange | None
    research_status: str
    sourcing_status: str
    attachment_count: int
    boundary_count: int


class DerivationEdge(BaseModel):
    origin: str
    derived: str
    kind: str


class SourceSummary(BaseModel):
    key: str
    author: str | None
    title: str
    category: str
    composed_label: str | None
    original_extant: bool


class AttachmentOut(BaseModel):
    source: SourceSummary
    role: str
    evidence_type: str
    locus: str | None
    access: str | None
    proximity: str | None
    notes: str | None
    # Every derivation edge upstream of the cited source. A graph, not a list:
    # Mártir's upstream is the lost Pané original via an excerpt edge.
    transmission: list[DerivationEdge]


class RelationOut(BaseModel):
    kind: str
    claim: str        # the OTHER claim's key
    direction: str    # "out": this claim -> other;  "in": other -> this claim
    notes: str | None


class BoundaryRef(BaseModel):
    id: int
    interpretation_label: str
    source_figure: str | None
    imprecision: str | None


class ClaimDetail(ClaimSummary):
    notes: str | None
    dating: dict | None
    attachments: list[AttachmentOut]
    relations: list[RelationOut]
    boundaries: list[BoundaryRef]


class SourceDetail(SourceSummary):
    language: str | None
    composed_range: YearRange | None
    publisher: str | None
    place: str | None
    venue: str | None
    doi: str | None
    url: str | None
    notes: str | None
    derived_from: list[DerivationEdge]
    derivatives: list[DerivationEdge]
    claims: list[str]   # keys of claims this source is attached to
