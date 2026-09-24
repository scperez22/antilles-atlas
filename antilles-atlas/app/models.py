"""
antilles-atlas schema, drafted from the Phase 2 hand-entry in seed/claims.yaml.

Friction IDs in comments (C002-e, C005, ...) point back to the YAML entry 
that forced each decision. 

Tables
-------
entity                               things claims are ABOUT (polities, provinces, people, persons)
source                              one row per concrete text/edition, including LOST ones
source_derivation            edges between sources:  copy, translation, experpt, ....
claim                                 one assertion one source could support or fail to support 
claim_source                   a source's evidentiary role for a claim, plus dimensions
claim_relation                  claims about claims: disputes, decomes_to
boundary_geometry        cited polygon asserting poltical extent 
distrubution_geometry    point/area where materail was recovered """

from __future__ import annotations
 
import enum
from typing import Any
 
from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, JSONB, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship
 
# Single shared Base. Alembic's env.py reads app.db.Base.metadata, so every
# model MUST subclass this one. Declaring a second Base here would make the
# tables invisible to autogenerate.
from app.db import Base


#----------------------------------------------------------------------------
# Enums
#
# Stored as VARCHAT (native_enum=False), not as Postgres ENUM types. The 
# vocabularies will change during corpus entry, and Alembic autogenerate does 
# not detect added vales on a native Enum. With VARCHAR, adding a vlaue is a 
# Python-only change. Validation happens in Python.
#----------------------------------------------------------------------------

def _enum(e:  type[enum.Enum]) -> Enum:
    return Enum(
        e,
        native_enum=False,
        length=40,
        values_callable=lambda cls: [m.value for m in cls], #store "supports", not "SUPPORTS"
        validate_strings=True,
    )

class EntityKind(str, enum.Enum):
    POLITY = "polity"          # a cacicazgo, as some source conceives it
    PROVINCE = "province"      # Morales/Vega regions (C002-e)
    PEOPLE = "people"          # e.g. "Taíno (Hispaniola)"
    PERSON = "person"          # e.g. Bohechío (C006)
    SITE = "site"              # archaeological site
    REGION = "region"          # geographic, non-political

class SourceCategory(str, enum.Enum):
    #the six categories from proposal 2.3
    CONTEMPORARY_CHRONICLE = "contemporary_chronicle"
    LATER_TRANSMISSION = "later_transmission"    #transcriiption/abridgement/translation of another source 
    PEER_REVIEWED_ARCHAEOLOGY = "peer_reviewed_archaeology"
    MODERN_SYNTHESIS = "modern_synthesis"
    SITE_REPORT = "site_report"
    LINGUISTIC = "linguistic"

class DerivationKind(str, enum.Enum):
    COPY = "copy"  #transcribed/ incorporated whole
    TRANSLATION = "translation" #e.g Ulloa's 1571 italian 
    RECONSTRUCTION = "reconstruction" #e.g. Arrom back-rendering Spanish from Italian 
    EXCERPT = "excerpt" #partial use: marir, Las Casas drawing on Pane
    EDITION_OF = "edition_of" #Vega 1990 vs 1980 (friction on vega-1990)

class ClaimKind(str, enum.Enum):
    PRACTICE_OR_BELIEF = "practice_or_belief" 
    CLAIMED_BOUNDARY = "claimed_boundary"
    EVIDENCE_DISTRIBUTION = "evidence_distribution"
    ATTRIBUTION_OF_RULE = "attribution_of_rule"
    COMPARATIVE_EXTENT = "comparative_extent"
    HISTORIOGRAPHIC = "historiographic" # claims about scholarship
    COMPOSITE = "composite" #kept for display, never classified

class ResearchStatus(str, enum.Enum):
    #Workflow state, not eviidence. Lets the UI tell "no sources exist"
    # apart from "I haven't loooked yet"
    NOT_RESEARCHED = "not_researched"
    IN_PROGRESS = "in_progress"
    RESEARCHED = "researched"

class Role(str, enum.Enum):
    #evidentiary role of a source for a claim. 
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies" #supports with material caveat

class EvidenceType(str, enum.Enum):
    DOCUMENTARY = "documentary" 
    MATERIAL = "material"
    LINGUISTIC = "linguistic"

class Access(str, enum.Enum):
    DIRECT = "direct" #Author observed or handled the source
    INFORMANT = "informant" #Author relied on a witness or report
    SECONDHAND = "secondhand" #Author relied on a source 

class Proximity(str, enum.Enum):
    CONTEMPORARY = "contemporary" #written within a decade
    GENERATIONAL = "generational" #within living memory
    DISTANT = "distant" #later, pre-modern
    MODERN = "modern" #Modern scholarship

class ClaimRelationKind(str, enum.Enum):
    DISPUTES = "disputes" #c003 disputes c002
    DECOMPOSES_TO = "decomposes_to" #C009 -> C009A, C009b, C006

    #----------------------------------------------------------------------------
    # Entity
    #----------------------------------------------------------------------------

class Entity(Base):
    """What a claim is about.
    Deliberately NOT called polity (C002-e): Vega's reconstruction may be about Morales provinces,
    not the five caicazgos. Both become entities. The schema doesn't decide which set is real; that is the point.
    """

    __tablename__ = "entity"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)   # stable slug: "xaragua"
    name: Mapped[str] = mapped_column(Text)                      # display: "Xaraguá"
    kind: Mapped[EntityKind] = mapped_column(_enum(EntityKind))
    notes: Mapped[str | None] = mapped_column(Text)
 
    claims: Mapped[list[Claim]] = relationship(back_populates="subject")

class Source(Base):
    """One concrete text. Lost texts get a row too (original_extant=False).
    
    For Pane this means four rows: the lost original, Ferdinand's Columbus's 
    Historie, Ulloa's 1572 tranlation, Arrom's edition. """

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)   # stable slug: "pane-1526"
    author: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text) 
    category: Mapped[SourceCategory] = mapped_column(_enum(SourceCategory))

    #Human-readable date as written plus a queryable range.
    composed_label: Mapped[str | None] = mapped_column(Text) 
    composed_range: Mapped[Range[int] | None] = mapped_column(INT4RANGE)

    language: Mapped[str | None] = mapped_column(String(40))
    original_extant: Mapped[bool] = mapped_column(Boolean, default=True)

    #Bibliographic detail; all optional because Lost
    publisher: Mapped[str | None] = mapped_column(Text)
    place: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    attachments: Mapped[list[ClaimSource]] = relationship(back_populates="source")

    #edges where this source is the DERIVED  text
    derived_from: Mapped[list[SourceDerivation]] = relationship(
        foreign_keys="SourceDerivation.derived_id", back_populates="derived"
    )

    #Edges where this source is the origin text
    derivatives: Mapped[list[SourceDerivation]] = relationship(
        foreign_keys="SourceDerivation.origin_id", back_populates="origin"
    )

class SourceDerivation(Base):
    """A directed edge: derived came from origin by kind. 
    
    Why a graph and not an ordered list (pane-relacion friction):
    Marir and Las Casas each get an EXCERPT edge rom the lost Pane original. 
    They are parallel witnessess because they share a parent, so no parallel_witness type is needed; it falls out of the shape."""

    __tablename__ = "source_derivation"
    __table_args__ = (
        UniqueConstraint("origin_id", "derived_id", "kind"),
        CheckConstraint("origin_id <> derived_id", name="no_self_derivation"),
    )
 
    id: Mapped[int] = mapped_column(primary_key=True)
    origin_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    derived_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    kind: Mapped[DerivationKind] = mapped_column(_enum(DerivationKind))
    notes: Mapped[str | None] = mapped_column(Text)
 
    origin: Mapped[Source] = relationship(foreign_keys=[origin_id], back_populates="derivatives")
    derived: Mapped[Source] = relationship(foreign_keys=[derived_id], back_populates="derived_from")



#--------------------------------------------------------------------------------------------
#Claim
#--------------------------------------------------------------------------------------------

class Claim(Base):
    """One assertion one source can support or fail to support (proposal )
    
    There is no classification column. Classfication i scomputed from claim_source rows, never stored or assigned.
    """

    __tablename__ = "claim"
 
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True)   # "C001"
    assertion: Mapped[str] = mapped_column(Text)
    kind: Mapped[ClaimKind] = mapped_column(_enum(ClaimKind))
 
    # Nullable: historiographic claims (C003) aren't about one entity.
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("entity.id"))
 
    # Time the claim is ABOUT. Years as ints; BCE is negative.
    # The range is the full window of possibility, so "c. 1492–1498" is
    # [1492, 1499). The label keeps the original wording.
    when_label: Mapped[str | None] = mapped_column(Text)
    when_range: Mapped[Range[int] | None] = mapped_column(INT4RANGE)
 
    # Structured dating basis (C008): {"basis": "radiocarbon",
    # "lab_code": ..., "calibration": ...}. JSONB because the shape differs
    # by method and the set of methods isn't settled.
    # Known loss: a calibrated date is a probability distribution; the range
    # above flattens it to its bounds. Documented, accepted.
    dating: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
 
    research_status: Mapped[ResearchStatus] = mapped_column(
        _enum(ResearchStatus), default=ResearchStatus.NOT_RESEARCHED
    )
    notes: Mapped[str | None] = mapped_column(Text)   # where `friction` goes
 
    subject: Mapped[Entity | None] = relationship(back_populates="claims")
    attachments: Mapped[list[ClaimSource]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    boundaries: Mapped[list[BoundaryGeometry]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    distributions: Mapped[list[DistributionGeometry]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    relations_out: Mapped[list[ClaimRelation]] = relationship(
        foreign_keys="ClaimRelation.from_claim_id", back_populates="from_claim",
        cascade="all, delete-orphan",
    )
    relations_in: Mapped[list[ClaimRelation]] = relationship(
        foreign_keys="ClaimRelation.to_claim_id", back_populates="to_claim"
    )

class ClaimSource(Base):
     """The evidentiary role one source plays for one claim 
     Dimensions are nullable on purpose: for material evidence, 
     access and proximity don't apply , and Null means not applicable. 
     The classifier skips NULLs rather than scoring them. 
     There is no trasmisssion column. Transmission is computed by walking 
     source_derivation upward from the source you cite. Storing it here too 
     would let the two disagree.
     """

     __tablename__ = "claim_source"
     __table_args__ = (UniqueConstraint("claim_id", "source_id", "role"), )
     id: Mapped[int] = mapped_column(primary_key=True)
     claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
     source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="RESTRICT"))

     role: Mapped[Role] = mapped_column(_enum(Role))
     evidence_type: Mapped[EvidenceType] = mapped_column(_enum(EvidenceType))
     locus: Mapped[str | None] = mapped_column(Text)   # chapter/page in THIS edition

     access: Mapped[Access | None] = mapped_column(_enum(Access))
     proximity: Mapped[Proximity | None] = mapped_column(_enum(Proximity))
     notes: Mapped[str | None] = mapped_column(Text)   #prose reasoning

     claim: Mapped[Claim] = relationship(back_populates="attachments")
     source: Mapped[Source] = relationship(back_populates="attachments")


class ClaimRelation(Base):
    """Claims about claims (C003, C009, C010).
 
    C003 in the YAML has `role: contradicts, target_claim: C002`. That is two
    facts, stored in two places:
      - Herrera Malatesta SUPPORTS C003        -> claim_source
      - C003 DISPUTES C002                     -> claim_relation
    """
 
    __tablename__ = "claim_relation"
    __table_args__ = (
        UniqueConstraint("from_claim_id", "to_claim_id", "kind"),
        CheckConstraint("from_claim_id <> to_claim_id", name="no_self_relation"),
    )
 
    id: Mapped[int] = mapped_column(primary_key=True)
    from_claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
    to_claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
    kind: Mapped[ClaimRelationKind] = mapped_column(_enum(ClaimRelationKind))
    notes: Mapped[str | None] = mapped_column(Text)
 
    from_claim: Mapped[Claim] = relationship(foreign_keys=[from_claim_id], back_populates="relations_out")
    to_claim: Mapped[Claim] = relationship(foreign_keys=[to_claim_id], back_populates="relations_in")


#-------------------------------------------------------------------------------------------------------
#Geometry
#
#Two tables, not one, because proposal §3 treats boundaries and
# distributions as different classes of assertion. Separate tables let the
# DATABASE enforce that a boundary is a polygon.
#
# Geometry hangs off a CLAIM, never off an entity (C002-b). A boundary exists
# only as someone's cited assertion. "Vega's Xaraguá" and "the popular
# Xaraguá" are two claims with the same subject, each with its own polygon.
# That is the competing-interpretations feature.
#
# SRID 4326 = plain lon/lat (WGS84), which is what MapLibre and GeoJSON use.
# GeoAlchemy2 creates a GiST spatial index on each column automatically.
# ---------------------------------------------------------------------------
 
 
class BoundaryGeometry(Base):
    __tablename__ = "boundary_geometry"
 
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
 
    # MULTIPOLYGON, not POLYGON: a territory with offshore islands
    # (Gonâve, for Xaraguá) is several rings.
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
 
    interpretation_label: Mapped[str] = mapped_column(String(80))   # "vega-1990"
    source_figure: Mapped[str | None] = mapped_column(Text)         # page/plate traced from
    imprecision: Mapped[str | None] = mapped_column(Text)           # how rough, and why
 
    claim: Mapped[Claim] = relationship(back_populates="boundaries")
 
 
class DistributionGeometry(Base):
    __tablename__ = "distribution_geometry"
 
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"))
 
    # Generic GEOMETRY: a site is a point, a survey area is a polygon.
    geom: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326))
 
    material: Mapped[str | None] = mapped_column(Text)       # "Meillacoid ceramics"
    imprecision: Mapped[str | None] = mapped_column(Text)    # site location precision
 
    claim: Mapped[Claim] = relationship(back_populates="distributions")