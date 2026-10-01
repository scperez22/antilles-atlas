"""
Read-only API.

    GET /claims                     list, filterable by kind / sourcing / subject
    GET /claims/{key}               detail: attachments + transmission, relations, boundaries
    GET /sources                    list, filterable by category
    GET /sources/{key}              detail: derivation edges both ways, attached claims
    GET /geometries                 GeoJSON FeatureCollection of boundary polygons
        ?as_of=1492                 only claims whose when_range contains that year
        ?bbox=w,s,e,n               only polygons intersecting that box (lon/lat)

Temporal rule (same as test_schema): a claim matches as_of=Y when
when_range @> Y. The range is half-open, so [1492, 1493) matches 1492 only.
A claim with no when_range never matches an as_of query.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import (
    BoundaryGeometry, Claim, ClaimSource, Entity, Source, SourceCategory,
)
from app.schemas import (
    AttachmentOut, BoundaryRef, ClaimDetail, ClaimSummary, DerivationEdge, EntityOut,
    RelationOut, SourceDetail, SourceSummary, YearRange,
)
from app.sourcing import sourcing_status

router = APIRouter()

YEAR = dict(ge=-3000, le=2100)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _range(r) -> YearRange | None:
    return None if r is None else YearRange(start=r.lower, end=r.upper)


def _v(e):
    """Enum -> its stored value; None stays None."""
    return None if e is None else e.value


def _claim_summary(c: Claim) -> ClaimSummary:
    return ClaimSummary(
        key=c.key,
        assertion=c.assertion.strip(),
        kind=_v(c.kind),
        subject=EntityOut(key=c.subject.key, name=c.subject.name, kind=_v(c.subject.kind)) if c.subject else None,
        when_label=c.when_label,
        when_range=_range(c.when_range),
        research_status=_v(c.research_status),
        sourcing_status=sourcing_status(c),
        attachment_count=len(c.attachments),
        boundary_count=len(c.boundaries),
    )


def _source_summary(s: Source) -> SourceSummary:
    return SourceSummary(key=s.key, author=s.author, title=s.title, category=_v(s.category),
                         composed_label=s.composed_label, original_extant=s.original_extant)


_UPSTREAM_SQL = text("""
    WITH RECURSIVE up(origin_id, derived_id, kind) AS (
        SELECT d.origin_id, d.derived_id, d.kind
        FROM source_derivation d WHERE d.derived_id = :sid
        UNION
        SELECT d.origin_id, d.derived_id, d.kind
        FROM source_derivation d JOIN up ON d.derived_id = up.origin_id
    )
    SELECT o.key, dv.key, up.kind
    FROM up
    JOIN source o  ON o.id  = up.origin_id
    JOIN source dv ON dv.id = up.derived_id
    ORDER BY dv.key, o.key
""")


def _upstream(db: Session, source_id: int) -> list[DerivationEdge]:
    rows = db.execute(_UPSTREAM_SQL, {"sid": source_id}).all()
    return [DerivationEdge(origin=o, derived=d, kind=k) for o, d, k in rows]


_CLAIM_LOAD = (
    selectinload(Claim.subject),
    selectinload(Claim.attachments),
    selectinload(Claim.boundaries),
)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------

@router.get("/claims", response_model=list[ClaimSummary], tags=["claims"])
def list_claims(
    kind: str | None = None,
    subject: str | None = Query(None, description="entity key, e.g. xaragua"),
    sourcing: str | None = Query(None, pattern="^(sourced|unproven|pending)$"),
    db: Session = Depends(get_db),
):
    stmt = select(Claim).options(*_CLAIM_LOAD).order_by(Claim.key)
    if kind:
        stmt = stmt.where(Claim.kind == kind)
    if subject:
        stmt = stmt.join(Claim.subject).where(Entity.key == subject)
    out = [_claim_summary(c) for c in db.scalars(stmt)]
    if sourcing:
        # Filtered in Python because sourcing_status is computed, not stored.
        # Fine at corpus size (~80 claims); revisit if that ever changes.
        out = [c for c in out if c.sourcing_status == sourcing]
    return out


@router.get("/claims/{key}", response_model=ClaimDetail, tags=["claims"])
def get_claim(key: str, db: Session = Depends(get_db)):
    c = db.scalar(
        select(Claim).where(Claim.key == key).options(
            *_CLAIM_LOAD,
            selectinload(Claim.attachments).selectinload(ClaimSource.source),
            selectinload(Claim.relations_out), selectinload(Claim.relations_in),
        )
    )
    if c is None:
        raise HTTPException(404, f"no claim {key!r}")

    attachments = [
        AttachmentOut(
            source=_source_summary(a.source), role=_v(a.role), evidence_type=_v(a.evidence_type),
            locus=a.locus, access=_v(a.access), proximity=_v(a.proximity), notes=a.notes,
            transmission=_upstream(db, a.source_id),
        )
        for a in c.attachments
    ]
    relations = (
        [RelationOut(kind=_v(r.kind), claim=r.to_claim.key, direction="out", notes=r.notes) for r in c.relations_out]
        + [RelationOut(kind=_v(r.kind), claim=r.from_claim.key, direction="in", notes=r.notes) for r in c.relations_in]
    )
    boundaries = [BoundaryRef(id=b.id, interpretation_label=b.interpretation_label,
                              source_figure=b.source_figure, imprecision=b.imprecision) for b in c.boundaries]
    return ClaimDetail(**_claim_summary(c).model_dump(), notes=c.notes, dating=c.dating,
                       attachments=attachments, relations=relations, boundaries=boundaries)


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=list[SourceSummary], tags=["sources"])
def list_sources(category: SourceCategory | None = None, db: Session = Depends(get_db)):
    stmt = select(Source).order_by(Source.key)
    if category:
        stmt = stmt.where(Source.category == category)
    return [_source_summary(s) for s in db.scalars(stmt)]


@router.get("/sources/{key}", response_model=SourceDetail, tags=["sources"])
def get_source(key: str, db: Session = Depends(get_db)):
    s = db.scalar(select(Source).where(Source.key == key).options(
        selectinload(Source.derived_from), selectinload(Source.derivatives),
        selectinload(Source.attachments).selectinload(ClaimSource.claim),
    ))
    if s is None:
        raise HTTPException(404, f"no source {key!r}")
    edge = lambda d: DerivationEdge(origin=d.origin.key, derived=d.derived.key, kind=_v(d.kind))  # noqa: E731
    return SourceDetail(
        **_source_summary(s).model_dump(),
        language=s.language, composed_range=_range(s.composed_range),
        publisher=s.publisher, place=s.place, venue=s.venue, doi=s.doi, url=s.url, notes=s.notes,
        derived_from=[edge(d) for d in s.derived_from],
        derivatives=[edge(d) for d in s.derivatives],
        claims=sorted({a.claim.key for a in s.attachments}),
    )


# ---------------------------------------------------------------------------
# geometries
# ---------------------------------------------------------------------------

def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be four numbers: west,south,east,north") from None
    if not (w < e and s < n):
        raise HTTPException(422, "bbox must satisfy west < east and south < north")
    return w, s, e, n


@router.get("/geometries", tags=["geometries"])
def list_geometries(
    as_of: int | None = Query(None, description="year; BCE is negative", **YEAR),
    bbox: str | None = Query(None, description="west,south,east,north in lon/lat"),
    db: Session = Depends(get_db),
):
    stmt = (
        select(BoundaryGeometry, func.ST_AsGeoJSON(BoundaryGeometry.geom, 6))
        .join(BoundaryGeometry.claim)
        .options(selectinload(BoundaryGeometry.claim).options(*_CLAIM_LOAD))
        .order_by(Claim.key, BoundaryGeometry.id)
    )
    if as_of is not None:
        stmt = stmt.where(Claim.when_range.contains(as_of))
    if bbox:
        w, s, e, n = _parse_bbox(bbox)
        stmt = stmt.where(func.ST_Intersects(BoundaryGeometry.geom, func.ST_MakeEnvelope(w, s, e, n, 4326)))

    features = []
    for b, geojson in db.execute(stmt).all():
        c = b.claim
        features.append({
            "type": "Feature",
            "id": b.id,
            "geometry": json.loads(geojson),
            "properties": {
                "claim": c.key,
                "subject": c.subject.key if c.subject else None,
                "subject_name": c.subject.name if c.subject else None,
                "interpretation_label": b.interpretation_label,
                "imprecision": b.imprecision,
                "when_label": c.when_label,
                "sourcing_status": sourcing_status(c),
            },
        })
    return {"type": "FeatureCollection", "features": features}
