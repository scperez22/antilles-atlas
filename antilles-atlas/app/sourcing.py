"""
Provisional sourcing status: sourced / unproven / pending.

This is NOT the Phase 5 evidence classifier. It answers one narrower question
the map needs now (proposal §2.4 item 3): does anything support this claim?

  sourced   at least one attachment with role supports or qualifies
  unproven  no supporting attachment, and research_status is "researched"
            (someone looked and found nothing: C004)
  pending   no supporting attachment, and nobody has finished looking (C001)

Kept in one function on purpose, so Phase 5 replaces it in one place.
"""

from __future__ import annotations

from app.models import Claim, ResearchStatus, Role

SUPPORTING = {Role.SUPPORTS, Role.QUALIFIES}


def sourcing_status(claim: Claim) -> str:
    if any(a.role in SUPPORTING for a in claim.attachments):
        return "sourced"
    if claim.research_status is ResearchStatus.RESEARCHED:
        return "unproven"
    return "pending"
