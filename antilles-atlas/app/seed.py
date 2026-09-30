"""
Seed loader: reads a structured corpus file and writes it to the database.

Why a second seed format?  seed/claims.yaml is the Phase 2 hand-entry: prose
fields, FILL / UNREAD / VERIFY markers, friction notes. It was built to expose
schema problems, and it did. This loader reads seed/corpus.yaml instead: the
same content, but every field already matches a column or an enum value, so
nothing has to be guessed while loading. If a value doesn't fit, loading fails
with the record and field named. It never coerces or skips silently.

Rules:
  * Idempotent. Rows are matched by `key`, so running it twice changes nothing.
    Children (attachments, boundaries, derivations, relations) are replaced
    wholesale for every record present in the file.
  * Never commits. The caller owns the transaction, which is what lets the
    tests roll everything back.
  * Records absent from the file are left alone (no deletes).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, shape
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.models import (
    Access, BoundaryGeometry, Claim, ClaimKind, ClaimRelation,
    ClaimRelationKind, ClaimSource, DerivationKind, Entity, EntityKind,
    EvidenceType, Proximity, ResearchStatus, Role, Source, SourceCategory,
    SourceDerivation,
)


class SeedError(ValueError):
    """The seed file is wrong. The message says which record and field."""


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------

def _check_fields(where: str, record: dict, allowed: set[str], required: set[str]) -> None:
    if not isinstance(record, dict):
        raise SeedError(f"{where}: expected a mapping, got {type(record).__name__}")
    unknown = set(record) - allowed
    if unknown:
        raise SeedError(f"{where}: unknown field(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
    missing = required - set(record)
    if missing:
        raise SeedError(f"{where}: missing required field(s) {sorted(missing)}")


def _enum(cls, value: Any, where: str):
    try:
        return cls(value)
    except ValueError:
        options = [m.value for m in cls]
        raise SeedError(f"{where}: {value!r} is not a valid {cls.__name__}; choose from {options}") from None


def _opt_enum(cls, value: Any, where: str):
    return None if value is None else _enum(cls, value, where)


def _range(value: Any, where: str) -> Range[int] | None:
    """[a, b] in the YAML becomes the half-open int range [a, b).

    Half-open matches how models.py documents it: "c. 1492-1498" is written
    [1492, 1499], because 1498 itself must be included.
    """
    if value is None:
        return None
    ok = (isinstance(value, list) and len(value) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in value))
    if not ok:
        raise SeedError(f"{where}: range must be [start, end] integers, got {value!r}")
    if value[0] >= value[1]:
        raise SeedError(f"{where}: range start must be below end (end is exclusive), got {value!r}")
    return Range(value[0], value[1], bounds="[)")


def _get_or_new(db: Session, model, key: str):
    obj = db.scalar(select(model).where(model.key == key))
    if obj is None:
        obj = model(key=key)
        db.add(obj)
    return obj


def _by_key(db: Session, model, key: str, where: str):
    obj = db.scalar(select(model).where(model.key == key))
    if obj is None:
        raise SeedError(f"{where}: no {model.__name__} with key {key!r}")
    return obj


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

# (west, south, east, north). Generous: covers the Greater Antilles and the
# Lesser Antilles extension. Widen it if the project's scope ever does.
CARIBBEAN_BBOX = (-90.0, 10.0, -58.0, 25.0)

def _read_multipolygon(path: pathlib.Path, where: str) -> MultiPolygon:
    """Read a GeoJSON file and return a MultiPolygon (WGS84 lon/lat).

    Accepts a bare geometry, one Feature, or a FeatureCollection holding exactly
    one feature (QGIS exports a FeatureCollection by default).
    """
    if not path.is_file():
        raise SeedError(f"{where}: geometry file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        feats = data.get("features") or []
        if len(feats) != 1:
            raise SeedError(f"{where}: expected exactly 1 feature in {path.name}, found {len(feats)}")
        data = feats[0]
    if data.get("type") == "Feature":
        data = data.get("geometry")
    geom = shape(data)
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    if geom.geom_type != "MultiPolygon":
        raise SeedError(f"{where}: boundary must be a Polygon or MultiPolygon, got {geom.geom_type}")
    minx, miny, maxx, maxy = geom.bounds
    if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
        raise SeedError(f"{where}: coordinates outside lon/lat range; wrong CRS? bounds={geom.bounds}")
    # Sanity net, not a scope rule: a lon/lat swap on Hispaniola is still a valid
    # lon/lat pair (lon 18, lat -73) and would load silently without this.
    w, s_, e, n = CARIBBEAN_BBOX
    if not (w <= minx and maxx <= e and s_ <= miny and maxy <= n):
        raise SeedError(f"{where}: geometry lies outside the Caribbean box {CARIBBEAN_BBOX} "
                        f"(lon/lat swapped?) bounds={geom.bounds}")
    if not geom.is_valid:
        raise SeedError(f"{where}: invalid geometry (self-intersection?) in {path.name}")
    return geom


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_ENTITY = ({"key", "name", "kind", "notes"}, {"key", "name", "kind"})
_SOURCE = (
    {"key", "author", "title", "category", "composed_label", "composed_range", "language",
     "original_extant", "publisher", "place", "venue", "doi", "url", "notes"},
    {"key", "title", "category"},
)
_DERIVATION = ({"origin", "derived", "kind", "notes"}, {"origin", "derived", "kind"})
_CLAIM = (
    {"key", "assertion", "kind", "subject", "when_label", "when_range", "dating",
     "research_status", "notes", "attachments", "boundaries"},
    {"key", "assertion", "kind"},
)
_ATTACHMENT = (
    {"source", "role", "evidence_type", "locus", "access", "proximity", "notes"},
    {"source", "role", "evidence_type"},
)
_BOUNDARY = (
    {"geojson", "interpretation_label", "source_figure", "imprecision"},
    {"geojson", "interpretation_label"},
)
_RELATION = ({"from", "to", "kind", "notes"}, {"from", "to", "kind"})
_TOP = {"entities", "sources", "derivations", "claims", "relations"}


def load_seed(db: Session, doc: dict, base_dir: pathlib.Path) -> dict[str, int]:
    """Write `doc` (a parsed corpus file) into `db`. Flushes; never commits.

    `base_dir` is the folder geojson paths are relative to (the seed folder).
    Returns row counts for what the file contained.
    """
    if not isinstance(doc, dict):
        raise SeedError("corpus file must be a mapping at the top level")
    unknown = set(doc) - _TOP
    if unknown:
        raise SeedError(f"top level: unknown section(s) {sorted(unknown)}; allowed: {sorted(_TOP)}")

    counts = dict(entities=0, sources=0, derivations=0, claims=0,
                  attachments=0, boundaries=0, relations=0)

    with db.no_autoflush:
        # 1. entities
        for rec in doc.get("entities") or []:
            where = f"entity {rec.get('key', '?')}"
            _check_fields(where, rec, *_ENTITY)
            e = _get_or_new(db, Entity, rec["key"])
            e.name = rec["name"]
            e.kind = _enum(EntityKind, rec["kind"], f"{where}.kind")
            e.notes = rec.get("notes")
            counts["entities"] += 1

        # 2. sources
        for rec in doc.get("sources") or []:
            where = f"source {rec.get('key', '?')}"
            _check_fields(where, rec, *_SOURCE)
            s = _get_or_new(db, Source, rec["key"])
            s.title = rec["title"]
            s.category = _enum(SourceCategory, rec["category"], f"{where}.category")
            s.author = rec.get("author")
            s.composed_label = rec.get("composed_label")
            s.composed_range = _range(rec.get("composed_range"), f"{where}.composed_range")
            s.language = rec.get("language")
            s.original_extant = rec.get("original_extant", True)
            for f in ("publisher", "place", "venue", "doi", "url", "notes"):
                setattr(s, f, rec.get(f))
            counts["sources"] += 1
    db.flush()

    # 3. derivation edges: replace every edge whose derived source is in the file
    derivs = doc.get("derivations") or []
    if derivs:
        with db.no_autoflush:
            resolved = []
            for i, rec in enumerate(derivs):
                where = f"derivation #{i + 1}"
                _check_fields(where, rec, *_DERIVATION)
                resolved.append((
                    _by_key(db, Source, rec["origin"], f"{where}.origin"),
                    _by_key(db, Source, rec["derived"], f"{where}.derived"),
                    _enum(DerivationKind, rec["kind"], f"{where}.kind"),
                    rec.get("notes"),
                ))
        derived_ids = {d.id for _, d, _, _ in resolved}
        db.execute(delete(SourceDerivation).where(SourceDerivation.derived_id.in_(derived_ids)))
        db.expire_all()
        for origin, derived, kind, notes in resolved:
            db.add(SourceDerivation(origin_id=origin.id, derived_id=derived.id, kind=kind, notes=notes))
            counts["derivations"] += 1
        db.flush()

    # 4. claims (children are cleared and flushed first: SQLAlchemy runs INSERTs
    #    before DELETEs in one flush, which would trip the unique constraints)
    claims_in_file: list[Claim] = []
    for rec in doc.get("claims") or []:
        where = f"claim {rec.get('key', '?')}"
        _check_fields(where, rec, *_CLAIM)
        with db.no_autoflush:
            c = _get_or_new(db, Claim, rec["key"])
            c.assertion = rec["assertion"]
            c.kind = _enum(ClaimKind, rec["kind"], f"{where}.kind")
            c.subject = _by_key(db, Entity, rec["subject"], f"{where}.subject") if rec.get("subject") else None
            c.when_label = rec.get("when_label")
            c.when_range = _range(rec.get("when_range"), f"{where}.when_range")
            c.dating = rec.get("dating")
            c.research_status = _enum(ResearchStatus, rec.get("research_status", "not_researched"),
                                      f"{where}.research_status")
            c.notes = rec.get("notes")
            c.attachments.clear()
            c.boundaries.clear()
        db.flush()

        with db.no_autoflush:
            for j, att in enumerate(rec.get("attachments") or [], start=1):
                w = f"{where} attachment #{j}"
                _check_fields(w, att, *_ATTACHMENT)
                c.attachments.append(ClaimSource(
                    source=_by_key(db, Source, att["source"], f"{w}.source"),
                    role=_enum(Role, att["role"], f"{w}.role"),
                    evidence_type=_enum(EvidenceType, att["evidence_type"], f"{w}.evidence_type"),
                    locus=att.get("locus"),
                    access=_opt_enum(Access, att.get("access"), f"{w}.access"),
                    proximity=_opt_enum(Proximity, att.get("proximity"), f"{w}.proximity"),
                    notes=att.get("notes"),
                ))
                counts["attachments"] += 1

            for j, b in enumerate(rec.get("boundaries") or [], start=1):
                w = f"{where} boundary #{j}"
                _check_fields(w, b, *_BOUNDARY)
                mp = _read_multipolygon(base_dir / b["geojson"], w)
                c.boundaries.append(BoundaryGeometry(
                    geom=from_shape(mp, srid=4326),
                    interpretation_label=b["interpretation_label"],
                    source_figure=b.get("source_figure"),
                    imprecision=b.get("imprecision"),
                ))
                counts["boundaries"] += 1
        db.flush()
        claims_in_file.append(c)
        counts["claims"] += 1

    # 5. claim relations: replace every relation leaving a claim in the file
    rels = doc.get("relations") or []
    if rels:
        with db.no_autoflush:
            resolved_rel = []
            for i, rec in enumerate(rels):
                where = f"relation #{i + 1}"
                _check_fields(where, rec, *_RELATION)
                resolved_rel.append((
                    _by_key(db, Claim, rec["from"], f"{where}.from"),
                    _by_key(db, Claim, rec["to"], f"{where}.to"),
                    _enum(ClaimRelationKind, rec["kind"], f"{where}.kind"),
                    rec.get("notes"),
                ))
        db.execute(delete(ClaimRelation).where(
            ClaimRelation.from_claim_id.in_({f.id for f, _, _, _ in resolved_rel})))
        db.expire_all()
        for f, t, kind, notes in resolved_rel:
            db.add(ClaimRelation(from_claim_id=f.id, to_claim_id=t.id, kind=kind, notes=notes))
            counts["relations"] += 1
        db.flush()

    return counts
