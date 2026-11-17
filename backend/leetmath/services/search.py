"""Public catalog search over the read model (docs/09 §1–2, docs/07 §2).

* Only public + published + current + rights-valid (checked at query time, so expiry is immediate).
* Keyset (cursor) pagination with a stable tie-breaker → no duplicates / gaps across pages.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from ..models import Attempt, Problem, ProblemRevision, RightsGrant, SearchDocument
from .errors import ApiError
from .rights import valid_grant_clause

SORTS = {"relevance", "display_id", "updated_desc", "difficulty_asc", "difficulty_desc"}


def _enc(values: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, default=str).encode()).decode().rstrip("=")


def _dec(cursor: str) -> list:
    try:
        pad = "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(cursor + pad))
    except Exception as e:  # noqa: BLE001
        raise ApiError("VALIDATION_FAILED", "invalid cursor") from e


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(
    s: Session,
    *,
    query: str | None = None,
    grade_band: str | None = None,
    region: str | None = None,
    knowledge_id: str | None = None,
    difficulty_min: int | None = None,
    difficulty_max: int | None = None,
    response_type: str | None = None,
    source_kind: str | None = None,
    has_solution: bool | None = None,
    attempted: bool | None = None,
    user_id: str | None = None,
    sort: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    if not 1 <= limit <= 100:
        raise ApiError("VALIDATION_FAILED", "limit must be 1..100")
    q = (query or "").strip()
    sort = sort or ("relevance" if q else "display_id")
    if sort not in SORTS:
        raise ApiError("VALIDATION_FAILED", f"sort must be one of {sorted(SORTS)}")
    if sort == "relevance" and not q:
        sort = "display_id"
    D = SearchDocument
    stmt = (
        select(D)
        .join(Problem, Problem.id == D.problem_id)
        .join(ProblemRevision, ProblemRevision.id == D.revision_id)
        .join(RightsGrant, RightsGrant.id == D.rights_grant_id)
        .where(
            Problem.takedown_hold.is_(False),
            Problem.visibility == "public",
            Problem.deleted_at.is_(None),
            Problem.current_public_revision_id == D.revision_id,
            ProblemRevision.status == "published",
            valid_grant_clause(),
            RightsGrant.allows_display.is_(True),
        )
    )
    rank = literal(0)
    if q:
        terms = [t for t in q.split() if t][:8]
        for t in terms:
            pat = f"%{_escape_like(t)}%"
            stmt = stmt.where(or_(
                func.upper(D.display_id) == t.upper(),
                D.title.like(pat, escape="\\"), D.knowledge_text.like(pat, escape="\\"),
                D.body_text.like(pat, escape="\\"),
            ))
        full = f"%{_escape_like(q)}%"
        rank = case(
            (func.upper(D.display_id) == q.upper(), 0),
            (D.title.like(full, escape="\\"), 1),
            (D.knowledge_text.like(full, escape="\\"), 2),
            else_=3,
        )
    if grade_band:
        stmt = stmt.where(D.grade_band == grade_band)
    if region:
        stmt = stmt.where(D.region_hints.like(f"%,{_escape_like(region)},%", escape="\\"))
    if knowledge_id:
        stmt = stmt.where(D.knowledge_ids.like(f"%,{_escape_like(knowledge_id)},%", escape="\\"))
    if difficulty_min is not None:
        stmt = stmt.where(D.difficulty >= difficulty_min)
    if difficulty_max is not None:
        stmt = stmt.where(D.difficulty <= difficulty_max)
    if response_type:
        stmt = stmt.where(D.response_types.like(f"%,{_escape_like(response_type)},%", escape="\\"))
    if source_kind:
        stmt = stmt.where(D.source_kind == source_kind)
    if has_solution is not None:
        stmt = stmt.where(D.has_solution.is_(has_solution))
    if attempted is not None and user_id:
        done = select(ProblemRevision.problem_id).join(Attempt, Attempt.problem_revision_id == ProblemRevision.id).where(Attempt.user_id == user_id)
        stmt = stmt.where(D.problem_id.in_(done) if attempted else D.problem_id.not_in(done))

    # (expression, descending?) — always ends with display_id + problem_id as stable tie-breakers.
    keys: list[tuple] = {
        "relevance": [(rank, False)],
        "display_id": [],
        "updated_desc": [(D.updated_at, True)],
        "difficulty_asc": [(D.difficulty, False)],
        "difficulty_desc": [(D.difficulty, True)],
    }[sort] + [(D.display_id, False), (D.problem_id, False)]

    if cursor:
        vals = _dec(cursor)
        if len(vals) != len(keys):
            raise ApiError("VALIDATION_FAILED", "cursor does not match sort")
        vals = [datetime.fromisoformat(v) if isinstance(v, str) and expr is D.updated_at else v
                for (expr, _), v in zip(keys, vals, strict=True)]
        ors = []
        for i, (expr, desc) in enumerate(keys):
            eqs = [keys[j][0] == vals[j] for j in range(i)]
            ors.append(and_(*eqs, expr < vals[i] if desc else expr > vals[i]))
        stmt = stmt.where(or_(*ors))
    stmt = stmt.add_columns(*[k[0].label(f"k{i}") for i, k in enumerate(keys)])
    stmt = stmt.order_by(*[k[0].desc() if k[1] else k[0].asc() for k in keys]).limit(limit + 1)
    rows = s.execute(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [r[0] for r in rows]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _enc([last[i + 1] for i in range(len(keys))])
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more, "sort": sort}
