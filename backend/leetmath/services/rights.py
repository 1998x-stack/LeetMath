"""Rights gate (docs/05 §4.8, docs/11 §4). Rights are revocable, expiring and action-scoped — never a boolean."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import RightsGrant, Source

ACTIONS = ("display", "reproduce", "adapt", "redistribute", "export", "commercial")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def grant_allows(grant: RightsGrant | None, action: str, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    if grant is None:
        return False, "NO_GRANT"
    if grant.status != "active":
        return False, f"GRANT_{grant.status.upper()}"
    if grant.valid_from and _aware(grant.valid_from) > now:
        return False, "GRANT_NOT_YET_VALID"
    if grant.valid_to and _aware(grant.valid_to) <= now:
        return False, "GRANT_EXPIRED"
    if action not in (grant.permitted_actions or []):
        return False, f"ACTION_NOT_PERMITTED:{action}"
    return True, "OK"


def valid_grant_clause(now: datetime | None = None):
    """SQL predicate on RightsGrant for 'currently valid for public display'."""
    now = now or datetime.now(timezone.utc)
    return and_(
        RightsGrant.status == "active",
        or_(RightsGrant.valid_from.is_(None), RightsGrant.valid_from <= now),
        or_(RightsGrant.valid_to.is_(None), RightsGrant.valid_to > now),
    )


def grant_by_ref(s: Session, ref: str | None) -> RightsGrant | None:
    if not ref:
        return None
    return s.scalar(select(RightsGrant).where(or_(RightsGrant.code == ref, RightsGrant.id == ref)))


def source_by_code(s: Session, code: str) -> Source | None:
    return s.scalar(select(Source).where(Source.code == code))
