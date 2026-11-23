"""Phase 5: independence and transmission depth, checked against the real Pane chain."""

import pathlib

import pytest
import yaml
from sqlalchemy import select

from app.classify import independent, transmission_depth, witness_groups
from app.models import Source
from app.seed import load_seed

SEED_DIR = pathlib.Path(__file__).resolve().parent.parent / "seed"


@pytest.fixture
def src(db):
    load_seed(db, yaml.safe_load((SEED_DIR / "corpus.yaml").read_text(encoding="utf-8")), SEED_DIR)
    return lambda key: db.scalar(select(Source).where(Source.key == key))


@pytest.mark.parametrize("key, depth", [
    ("pane-original", 0),      # the lost original itself
    ("colon-historie", 1),
    ("ulloa-1571", 2),
    ("arrom-edition", 3),      # three copies away from what Pane wrote
    ("martyr-decades", 1),
])
def test_transmission_depth_counts_steps_to_the_original(src, key, depth):
    assert transmission_depth(src(key)) == depth


def test_martyr_and_las_casas_are_not_independent(src):
    """Both excerpt Pane: two books, one witness."""
    assert not independent(src("martyr-decades"), src("lascasas-apologetica"))


def test_a_copy_is_not_independent_of_its_original(src):
    assert not independent(src("arrom-edition"), src("pane-original"))


def test_unrelated_modern_sources_are_independent(src):
    assert independent(src("vega-1990"), src("herrera-malatesta-2022"))


def test_pane_martyr_lascasas_collapse_to_one_witness(src):
    groups = witness_groups([src("pane-original"), src("martyr-decades"),
                             src("lascasas-apologetica"), src("vega-1990")])
    assert sorted(len(g) for g in groups) == [1, 3]



# ---- profile -----------------------------------------------------------------

from app.classify import profile
from app.models import Access, Claim, EvidenceType, Proximity


def _load(db, corpus):
    load_seed(db, corpus, SEED_DIR)
    return lambda key: db.scalar(select(Claim).where(Claim.key == key))


@pytest.fixture
def corpus():
    return yaml.safe_load((SEED_DIR / "corpus.yaml").read_text(encoding="utf-8"))


def _attach(source, role="supports", access=None, proximity=None):
    return {"source": source, "role": role, "evidence_type": "documentary",
            "access": access, "proximity": proximity}


def test_pane_family_is_one_witness_not_three(db, corpus):
    """Proposal validation case: Pane + Martyr + Las Casas all trace to one lost text."""
    c001 = next(c for c in corpus["claims"] if c["key"] == "C001")
    c001["attachments"] = [
        _attach("pane-original", access="direct", proximity="contemporary"),
        _attach("martyr-decades", access="secondhand", proximity="contemporary"),
        _attach("lascasas-apologetica", access="informant", proximity="generational"),
    ]
    p = profile(_load(db, corpus)("C001"))
    assert p.independent_witnesses == 1
    assert p.closest_proximity is Proximity.CONTEMPORARY
    assert p.best_access is Access.DIRECT
    assert p.shallowest_transmission == 0


def test_qualifying_source_is_shown_but_not_counted(db, corpus):
    c001 = next(c for c in corpus["claims"] if c["key"] == "C001")
    c001["attachments"] = [_attach("pane-original"),
                           _attach("vega-1990", role="qualifies")]
    p = profile(_load(db, corpus)("C001"))
    assert p.independent_witnesses == 1          # vega does not add a witness
    assert p.qualifying_sources == ("vega-1990",)


def test_unsourced_claim_has_an_empty_profile(db, corpus):
    p = profile(_load(db, corpus)("C004"))
    assert (p.independent_witnesses, p.closest_proximity, p.best_access,
            p.shallowest_transmission, p.evidence_types) == (0, None, None, None, ())


def test_danville_profile_is_distant_and_secondhand(db, corpus):
    p = profile(_load(db, corpus)("C011"))
    assert p.independent_witnesses == 1
    assert p.closest_proximity is Proximity.DISTANT
    assert p.best_access is Access.SECONDHAND
    assert p.evidence_types == (EvidenceType.DOCUMENTARY,)