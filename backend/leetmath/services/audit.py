"""Append-only audit trail + outbox (docs/04 §7, docs/08 §8)."""
from __future__ import annotations

import contextvars

from sqlalchemy.orm import Session

from ..content.contract import canonical_json, sha256_text
from ..models import AuditEvent, OutboxEvent

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def _h(obj) -> str | None:
    return None if obj is None else sha256_text(canonical_json(obj))


def audit(
    s: Session,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before=None,
    after=None,
    **meta,
) -> AuditEvent:
    ev = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_hash=_h(before),
        after_hash=_h(after),
        meta=meta,
        request_id=request_id_var.get(),
    )
    s.add(ev)
    return ev


def outbox(s: Session, topic: str, **payload) -> None:
    s.add(OutboxEvent(topic=topic, payload=payload))
