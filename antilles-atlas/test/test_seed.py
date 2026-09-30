"""Seed loader tests. The loader must be strict, idempotent, and never commit."""

import copy
import json
import pathlib

import pytest
import yaml
from sqlalchemy import func, select, text

from app.models import (
    BoundaryGeometry, Claim, ClaimRelation, ClaimRelationKind, Entity, ResearchStatus, Source,
)
from app.seed import SeedError, load_seed

SEED_DIR = pathlib.Path(__file__).resolve().parent.parent / "seed"


@pytest.fixture
def corpus():
    return yaml.safe_load((SEED_DIR / "corpus.yaml").read_text(encoding="utf-8"))


def claim(db, key):
    return db.scalar(select(Claim).where(Claim.key == key))


def test_real_corpus_loads(db, corpus):
    counts = load_seed(db, corpus, SEED_DIR)
    assert counts == dict(entities=3, sources=8, derivations=5, claims=5,
                          attachments=2, boundaries=0, relations=1)


def test_unsourced_popular_claim_reads_researched_not_unresearched(db, corpus):
    """C004 is the demo: zero sources, but someone looked. C001 is the opposite."""
    load_seed(db, corpus, SEED_DIR)
    c004, c001 = claim(db, "C004"), claim(db, "C001")
    assert c004.attachments == [] and c004.research_status is ResearchStatus.RESEARCHED
    assert c001.attachments == [] and c001.research_status is ResearchStatus.IN_PROGRESS


def test_dispute_is_loaded_as_a_relation(db, corpus):
    load_seed(db, corpus, SEED_DIR)
    rel = db.scalar(select(ClaimRelation))
    assert (rel.from_claim.key, rel.to_claim.key, rel.kind) == ("C003", "C002", ClaimRelationKind.DISPUTES)


def test_pane_chain_is_walkable_after_load(db, corpus):
    load_seed(db, corpus, SEED_DIR)
    arrom = db.scalar(select(Source).where(Source.key == "arrom-edition"))
    keys = set(db.execute(text("""
        WITH RECURSIVE up(id) AS (
            SELECT CAST(:sid AS integer)
            UNION
            SELECT d.origin_id FROM source_derivation d JOIN up ON d.derived_id = up.id
        ) SELECT s.key FROM up JOIN source s ON s.id = up.id
    """), {"sid": arrom.id}).scalars())
    assert keys == {"arrom-edition", "ulloa-1571", "colon-historie", "pane-original"}


def test_loading_twice_changes_nothing(db, corpus):
    first = load_seed(db, corpus, SEED_DIR)
    tables = ["entity", "source", "source_derivation", "claim", "claim_source", "claim_relation"]
    before = [db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables]
    second = load_seed(db, corpus, SEED_DIR)
    after = [db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables]
    assert first == second and before == after


def test_reload_picks_up_edits(db, corpus):
    load_seed(db, corpus, SEED_DIR)
    edited = copy.deepcopy(corpus)
    next(c for c in edited["claims"] if c["key"] == "C001")["research_status"] = "researched"
    load_seed(db, edited, SEED_DIR)
    db.refresh(claim(db, "C001"))
    assert claim(db, "C001").research_status is ResearchStatus.RESEARCHED


# ---- strictness: mistakes must fail loudly, naming the record ---------------

def test_unknown_field_is_rejected(db, corpus):
    corpus["claims"][0]["assertions"] = "typo"
    with pytest.raises(SeedError, match=r"claim C001.*unknown field.*assertions"):
        load_seed(db, corpus, SEED_DIR)


def test_bad_enum_value_names_the_choices(db, corpus):
    corpus["claims"][1]["kind"] = "claimed_boundary_partial"
    with pytest.raises(SeedError, match=r"claim C002\.kind.*claimed_boundary_partial.*choose from"):
        load_seed(db, corpus, SEED_DIR)


def test_unknown_source_reference_is_rejected(db, corpus):
    corpus["claims"][1]["attachments"][0]["source"] = "nope"
    with pytest.raises(SeedError, match=r"no Source with key 'nope'"):
        load_seed(db, corpus, SEED_DIR)


def test_inverted_range_is_rejected(db, corpus):
    corpus["claims"][0]["when_range"] = [1499, 1492]
    with pytest.raises(SeedError, match=r"range start must be below end"):
        load_seed(db, corpus, SEED_DIR)


# ---- geometry: a traced polygon flows through to the spatial-temporal query --

def _polygon_file(tmp_path, ring, wrapper="FeatureCollection"):
    geom = {"type": "Polygon", "coordinates": [ring]}
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geom}]}
    p = tmp_path / "xaragua.geojson"
    p.write_text(json.dumps(data))
    return p


def _with_boundary(corpus, filename):
    next(c for c in corpus["claims"] if c["key"] == "C002")["boundaries"] = [
        {"geojson": filename, "interpretation_label": "vega-1990",
         "source_figure": "test plate", "imprecision": "test"}]


def test_traced_polygon_is_loaded_and_queryable_by_place_and_year(db, corpus, tmp_path):
    _polygon_file(tmp_path, [[-74, 18], [-72, 18], [-72, 19], [-74, 19], [-74, 18]])
    _with_boundary(corpus, "xaragua.geojson")
    assert load_seed(db, corpus, tmp_path)["boundaries"] == 1

    def hits(year, lon, lat):
        return db.execute(text("""
            SELECT c.key FROM claim c JOIN boundary_geometry b ON b.claim_id = c.id
            WHERE c.when_range @> CAST(:y AS integer)
              AND ST_Intersects(b.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        """), dict(y=year, lon=lon, lat=lat)).scalars().all()

    assert hits(1492, -73.3, 18.4) == ["C002"]
    assert hits(1493, -73.3, 18.4) == []       # range is [1492, 1493): 1493 excluded
    assert hits(1492, -60.0, 18.4) == []       # right year, wrong place


def test_swapped_lon_lat_is_caught(db, corpus, tmp_path):
    """Hispaniola with lat/lon swapped is still a *valid* lon/lat pair (lon 18,
    lat -73), so only the Caribbean bounding-box check can catch it."""
    _polygon_file(tmp_path, [[18, -74], [18, -72], [19, -72], [19, -74], [18, -74]])
    _with_boundary(corpus, "xaragua.geojson")
    with pytest.raises(SeedError, match="outside the Caribbean box"):
        load_seed(db, corpus, tmp_path)


def test_out_of_range_coordinates_are_caught(db, corpus, tmp_path):
    _polygon_file(tmp_path, [[18, 173], [19, 173], [19, 174], [18, 174], [18, 173]])
    _with_boundary(corpus, "xaragua.geojson")
    with pytest.raises(SeedError, match="outside lon/lat range"):
        load_seed(db, corpus, tmp_path)


def test_missing_geometry_file_is_rejected(db, corpus, tmp_path):
    _with_boundary(corpus, "does-not-exist.geojson")
    with pytest.raises(SeedError, match="geometry file not found"):
        load_seed(db, corpus, tmp_path)
