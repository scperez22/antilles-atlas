"""Schema tests. Each one pins a decision made from a seed/claims.yaml friction."""

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Point, Polygon
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import DataError, IntegrityError

from app.models import (
    BoundaryGeometry, Claim, ClaimKind, ClaimRelation, ClaimRelationKind,
    ClaimSource, DerivationKind, Entity, EntityKind, EvidenceType, ResearchStatus, Role, Source,
    SourceCategory, SourceDerivation,
)

# The Pané chain (pane-relacion friction): lost original, three descendants
# in a line, plus Mártir and Las Casas as parallel excerpting witnesses.
ANCESTORS_SQL = text("""
    WITH RECURSIVE up(id) AS (
        SELECT CAST(:sid AS integer)
        UNION
        SELECT d.origin_id FROM source_derivation d JOIN up ON d.derived_id = up.id
    )
    SELECT id FROM up
""")


def src(key, category=SourceCategory.CONTEMPORARY_CHRONICLE, **kw):
    return Source(key=key, title=key, category=category, **kw)


def edge(origin, derived, kind):
    return SourceDerivation(origin=origin, derived=derived, kind=kind)


@pytest.fixture
def pane_graph(db):
    original = src("pane-original", original_extant=False, composed_label="c. 1498")
    historie = src("colon-historie", SourceCategory.LATER_TRANSMISSION)
    ulloa = src("ulloa-1571", SourceCategory.LATER_TRANSMISSION)
    arrom = src("arrom-edition", SourceCategory.LATER_TRANSMISSION)
    martyr = src("martyr-decades")
    lascasas = src("lascasas-apologetica")
    db.add_all([
        edge(original, historie, DerivationKind.COPY),
        edge(historie, ulloa, DerivationKind.TRANSLATION),
        edge(ulloa, arrom, DerivationKind.RECONSTRUCTION),
        edge(original, martyr, DerivationKind.EXCERPT),
        edge(original, lascasas, DerivationKind.EXCERPT),
    ])
    db.flush()
    return dict(original=original, historie=historie, ulloa=ulloa,
                arrom=arrom, martyr=martyr, lascasas=lascasas)


def ancestors(db, source):
    return set(db.execute(ANCESTORS_SQL, {"sid": source.id}).scalars())


def test_pane_chain_walks_back_to_lost_original(db, pane_graph):
    g = pane_graph
    assert ancestors(db, g["arrom"]) == {
        g["arrom"].id, g["ulloa"].id, g["historie"].id, g["original"].id
    }
    assert g["original"].original_extant is False


def test_martyr_and_lascasas_share_upstream_pane(db, pane_graph):
    """C005: three attachments may be one testimony. Detectable via shared ancestry."""
    g = pane_graph
    shared = ancestors(db, g["martyr"]) & ancestors(db, g["lascasas"])
    assert g["original"].id in shared


def test_source_cannot_derive_from_itself(db):
    s = src("loop")
    db.add(edge(s, s, DerivationKind.COPY))
    with pytest.raises(IntegrityError):
        db.flush()


def test_unsourced_claim_has_no_attachments_and_is_flagged_researched(db):
    """C004: the popular Xaraguá formulation. Zero sources, and we HAVE looked."""
    xaragua = Entity(key="xaragua", name="Xaraguá", kind=EntityKind.POLITY)
    c004 = Claim(key="C004", assertion="Xaraguá was the largest...",
                 kind=ClaimKind.CLAIMED_BOUNDARY, subject=xaragua,
                 research_status=ResearchStatus.RESEARCHED)
    db.add(c004)
    db.flush()
    assert c004.attachments == []
    assert c004.research_status is ResearchStatus.RESEARCHED


def test_dispute_is_a_claim_relation_not_an_attachment_role(db):
    """C003: Herrera Malatesta SUPPORTS C003; C003 DISPUTES C002."""
    hm = src("herrera-malatesta-2022", SourceCategory.PEER_REVIEWED_ARCHAEOLOGY)
    c002 = Claim(key="C002", assertion="Vega's Xaraguá", kind=ClaimKind.CLAIMED_BOUNDARY)
    c003 = Claim(key="C003", assertion="No bounded territories",
                 kind=ClaimKind.HISTORIOGRAPHIC)
    c003.attachments.append(ClaimSource(source=hm, role=Role.SUPPORTS,
                                        evidence_type=EvidenceType.MATERIAL))
    db.add_all([c002, c003,
                ClaimRelation(from_claim=c003, to_claim=c002, kind=ClaimRelationKind.DISPUTES)])
    db.flush()
    assert [r.from_claim.key for r in c002.relations_in] == ["C003"]
    assert c002.attachments == []


def test_material_evidence_leaves_testimony_dimensions_null(db):
    """C007: access/proximity are n/a for material evidence -> NULL, not a score."""
    report = src("site-report", SourceCategory.SITE_REPORT)
    c = Claim(key="C007", assertion="Meillacoid present", kind=ClaimKind.EVIDENCE_DISTRIBUTION)
    c.attachments.append(ClaimSource(source=report, role=Role.SUPPORTS,
                                     evidence_type=EvidenceType.MATERIAL))
    db.add(c)
    db.flush()
    att = c.attachments[0]
    assert att.access is None and att.proximity is None


def test_boundary_rejects_a_point(db):
    """Boundaries are polygons, enforced by PostGIS, not by convention."""
    c = Claim(key="CX", assertion="x", kind=ClaimKind.CLAIMED_BOUNDARY)
    c.boundaries.append(BoundaryGeometry(
        geom=from_shape(Point(-73, 18.5), srid=4326), interpretation_label="bad"))
    db.add(c)
    with pytest.raises(DataError) as e:
        db.flush()
    assert "Geometry type" in str(e.value)


def test_competing_boundaries_and_spatial_temporal_query(db):
    """Proposal §1: 'which polities were present here in 1490?' as one join.
    Two interpretations of the same entity both come back."""
    xaragua = Entity(key="xaragua", name="Xaraguá", kind=EntityKind.POLITY)
    square = MultiPolygon([Polygon([(-74, 18), (-72, 18), (-72, 19), (-74, 19)])])
    for key, label in [("C002", "vega-1990"), ("C004", "popular")]:
        c = Claim(key=key, assertion=key, kind=ClaimKind.CLAIMED_BOUNDARY,
                  subject=xaragua, when_range=Range(1450, 1500))
        c.boundaries.append(BoundaryGeometry(
            geom=from_shape(square, srid=4326), interpretation_label=label))
        db.add(c)
    later = Claim(key="C999", assertion="later", kind=ClaimKind.CLAIMED_BOUNDARY,
                  subject=xaragua, when_range=Range(1520, 1550))
    later.boundaries.append(BoundaryGeometry(
        geom=from_shape(square, srid=4326), interpretation_label="later"))
    db.add(later)
    db.flush()

    rows = db.execute(text("""
        SELECT c.key, b.interpretation_label
        FROM claim c
        JOIN boundary_geometry b ON b.claim_id = c.id
        WHERE c.when_range @> 1490
          AND ST_Intersects(b.geom, ST_SetSRID(ST_MakePoint(-73.3, 18.4), 4326))
        ORDER BY c.key
    """)).all()
    assert rows == [("C002", "vega-1990"), ("C004", "popular")]
