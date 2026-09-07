# Intentionally empty.
#
# Schema design is deferred until ~10 claims (including the Pané
# transmission case) have been hand-entered and validated against the
# evidence classification ruleset (see proposal §5, Phase 2). Models for
# polity, claim, source, claim_source, geometry_version, and period will
# be added here once that validation work exposes what the schema
# actually needs to represent.

from app.db import Base  # noqa: F401  (kept so Alembic autogenerate has a target)
