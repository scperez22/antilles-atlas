"""API tests. The app reads from the same rolled-back test session as the test."""

import copy
import json
import pathlib

import pytest
import yaml
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.seed import load_seed

SEED_DIR = pathlib.Path(__file__).resolve().parent.parent / "seed"

# Test-only squares. Not reconstructions of anything.
VEGA_SQ = [[-74.0, 18.0], [-72.5, 18.0], [-72.5, 19.0], [-74.0, 19.0], [-74.0, 18.0]]
POP_SQ = [[-74.5, 17.9], [-72.0, 17.9], [-72.0, 19.2], [-74.5, 19.2], [-74.5, 17.9]]


def _write(tmp_path, name, ring):
    p = tmp_path / name
    p.write_text(json.dumps({"type": "Polygon", "coordinates": [ring]}))
    return name


@pytest.fixture
def client(db, tmp_path):
    """Real corpus + two test polygons (C002 Vega, C004 popular), both c. 1492."""
    doc = copy.deepcopy(yaml.safe_load((SEED_DIR / "corpus.yaml").read_text(encoding="utf-8")))
    claims = {c["key"]: c for c in doc["claims"]}
    for c in claims.values():          # real traced polygons (C011) are tested in test_seed
        c.pop("boundaries", None)
    claims["C002"]["boundaries"] = [{"geojson": _write(tmp_path, "vega.geojson", VEGA_SQ),
                                     "interpretation_label": "vega-1990"}]
    claims["C004"]["boundaries"] = [{"geojson": _write(tmp_path, "pop.geojson", POP_SQ),
                                     "interpretation_label": "popular"}]
    load_seed(db, doc, tmp_path)

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---- claims -----------------------------------------------------------------

def test_claims_list_carries_computed_sourcing_status(client):
    status = {c["key"]: c["sourcing_status"] for c in client.get("/claims").json()}
    assert status == {"C001": "pending", "C002": "sourced", "C003": "sourced",
                      "C004": "unproven", "C006": "pending", "C011": "sourced"}


def test_claims_filter_by_sourcing_and_subject(client):
    assert [c["key"] for c in client.get("/claims?sourcing=unproven").json()] == ["C004"]
    assert [c["key"] for c in client.get("/claims?subject=xaragua").json()] == ["C002", "C004", "C006", "C011"]


def test_bad_sourcing_filter_is_422(client):
    assert client.get("/claims?sourcing=true").status_code == 422


def test_claim_detail_shows_dispute_from_both_sides(client):
    c002 = client.get("/claims/C002").json()
    c003 = client.get("/claims/C003").json()
    assert {"kind": "disputes", "claim": "C003", "direction": "in", "notes": None} in c002["relations"]
    assert {"kind": "disputes", "claim": "C002", "direction": "out", "notes": None} in c003["relations"]


def test_claim_detail_includes_boundary_refs_and_half_open_range(client):
    c = client.get("/claims/C002").json()
    assert c["when_range"] == {"start": 1492, "end": 1493}
    assert [b["interpretation_label"] for b in c["boundaries"]] == ["vega-1990"]
    assert c["attachments"][0]["source"]["key"] == "vega-1990"
    assert c["attachments"][0]["transmission"] == []     # Vega has no derivation edges


def test_unknown_claim_is_404(client):
    assert client.get("/claims/C999").status_code == 404


# ---- sources ----------------------------------------------------------------

def test_sources_filter_by_category(client):
    keys = [s["key"] for s in client.get("/sources?category=later_transmission").json()]
    assert keys == ["arrom-edition", "colon-historie", "ulloa-1571"]


def test_source_detail_pane_original_has_three_derivatives(client):
    s = client.get("/sources/pane-original").json()
    assert s["original_extant"] is False and s["derived_from"] == []
    assert {(d["derived"], d["kind"]) for d in s["derivatives"]} == {
        ("colon-historie", "copy"), ("martyr-decades", "excerpt"), ("lascasas-apologetica", "excerpt")}


def test_source_detail_lists_attached_claims(client):
    assert client.get("/sources/herrera-malatesta-2022").json()["claims"] == ["C003"]


# ---- geometries -------------------------------------------------------------

def feature_claims(resp):
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    return [f["properties"]["claim"] for f in body["features"]]


def test_geometries_returns_both_competing_interpretations(client):
    fc = client.get("/geometries").json()
    assert [f["properties"]["interpretation_label"] for f in fc["features"]] == ["vega-1990", "popular"]
    assert fc["features"][0]["geometry"]["type"] == "MultiPolygon"
    assert {f["properties"]["sourcing_status"] for f in fc["features"]} == {"sourced", "unproven"}


@pytest.mark.parametrize("year, expected", [
    (1491, []),                   # before
    (1492, ["C002", "C004"]),     # inside [1492, 1493)
    (1493, []),                   # end is exclusive
])
def test_geometries_as_of_respects_half_open_range(client, year, expected):
    assert feature_claims(client.get(f"/geometries?as_of={year}")) == expected


def test_geometries_bbox(client):
    # Box only the popular polygon reaches (it extends to -72.0; Vega stops at -72.5)
    assert feature_claims(client.get("/geometries?bbox=-72.3,18.2,-72.1,18.4")) == ["C004"]
    assert feature_claims(client.get("/geometries?bbox=-60,10,-59,11")) == []


def test_geometries_bad_bbox_is_422(client):
    assert client.get("/geometries?bbox=1,2,3").status_code == 422
    assert client.get("/geometries?bbox=-72,18,-74,19").status_code == 422


def test_map_client_is_served_without_shadowing_the_api(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "maplibre-gl" in page.text
    assert client.get("/app.js").status_code == 200
    # The static mount is at "/", so make sure API routes still win.
    assert client.get("/claims").headers["content-type"].startswith("application/json")
    assert client.get("/geometries").json()["type"] == "FeatureCollection"
