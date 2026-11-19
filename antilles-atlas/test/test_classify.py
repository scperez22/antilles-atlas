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