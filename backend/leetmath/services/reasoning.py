"""Phase 1.5 Reasoning Practice (docs/reasoning-practice/ALGORITHMS.md, algorithm v0-local).

Self-recall scores are *never* written to `evaluations`; they are subjective evidence only.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    KnowledgeNode,
    KnowledgeSelfAssessment,
    LearningAttempt,
    Problem,
    ProblemRevision,
    ReasoningStep,
    RevisionPart,
    StepReviewEvent,
    StepReviewState,
    User,
    XpAward,
    utcnow,
)
from .catalog import public_revision
from .errors import ApiError

ALGORITHM_VERSION = "v0-local"
SCHEDULER_VERSION = "fixed-1-3-7"
GRADE = {"know": Decimal("1.0"), "fuzzy": Decimal("0.45"), "unsure": Decimal("0")}
INTERVAL_DAYS = {"know": 7, "fuzzy": 3, "unsure": 1}
PRIOR_ALPHA = PRIOR_BETA = 2.0
SELF_ASSESS_WEIGHT = 0.5


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _steps_for_revision(s: Session, rev: ProblemRevision) -> list[ReasoningStep]:
    out = []
    for part in rev.parts:
        out += s.scalars(select(ReasoningStep).where(ReasoningStep.revision_part_id == part.id)
                         .order_by(ReasoningStep.step_order)).all()
    return out


def practice_catalog(s: Session) -> list[dict]:
    out = []
    for p in s.scalars(select(Problem).order_by(Problem.display_id)):
        rev = public_revision(s, p)
        if rev is None:
            continue
        steps = _steps_for_revision(s, rev)
        if steps:
            out.append({"problem_id": p.id, "display_id": p.display_id, "slug": p.slug, "revision_id": rev.id,
                        "title": rev.title, "part_count": len(rev.parts), "step_count": len(steps),
                        "max_score": str(sum(Decimal(x.max_points) for x in steps)),
                        "difficulty": rev.platform_difficulty})
    return out


def start(s: Session, user: User, problem_revision_id: str | None, mode: str = "full") -> LearningAttempt:
    if mode == "full":
        rev = s.get(ProblemRevision, problem_revision_id) if problem_revision_id else None
        if rev is None or public_revision(s, s.get(Problem, rev.problem_id)) is not rev:
            raise ApiError("NOT_FOUND", "problem not available")
        steps = _steps_for_revision(s, rev)
        if not steps:
            raise ApiError("VALIDATION_FAILED", "this problem has no reasoning steps")
        att = LearningAttempt(user_id=user.id, problem_revision_id=rev.id, mode="full", card_ids=[x.id for x in steps])
    elif mode == "due":
        now = utcnow()
        states = s.scalars(select(StepReviewState).where(StepReviewState.user_id == user.id)
                           .order_by(StepReviewState.due_at)).all()
        chosen, seen_parts = [], set()
        for st in states:
            if _aware(st.due_at) > now:
                continue
            step = s.get(ReasoningStep, st.step_id)
            part = s.get(RevisionPart, step.revision_part_id)
            rev = s.get(ProblemRevision, part.problem_revision_id)
            if public_revision(s, s.get(Problem, rev.problem_id)) is not rev:
                continue  # retracted / rights-held / superseded content is hidden from review too
            if part.id in seen_parts:  # sibling burial: one card per part per session
                continue
            seen_parts.add(part.id)
            chosen.append(step.id)
            if len(chosen) >= 20:
                break
        if not chosen:
            raise ApiError("NOT_FOUND", "no cards are due")
        att = LearningAttempt(user_id=user.id, problem_revision_id=None, mode="due", card_ids=chosen)
    else:
        raise ApiError("VALIDATION_FAILED", "mode must be full or due")
    s.add(att)
    s.flush()
    return att


def _get_owned(s: Session, user: User, attempt_id: str) -> LearningAttempt:
    att = s.get(LearningAttempt, attempt_id)
    if att is None or att.user_id != user.id:
        raise ApiError("NOT_FOUND", "attempt not found")
    return att


def view(s: Session, user: User, attempt_id: str) -> dict:
    att = _get_owned(s, user, attempt_id)
    events = {e.step_id: e for e in s.scalars(select(StepReviewEvent).where(StepReviewEvent.attempt_id == att.id))}
    cards = []
    current_index = None
    for i, sid in enumerate(att.card_ids):
        st = s.get(ReasoningStep, sid)
        part = s.get(RevisionPart, st.revision_part_id)
        ev = events.get(sid)
        card = {"step_id": sid, "index": i, "part_key": part.part_key, "part_id": part.id, "order": st.step_order,
                "recall_cue": st.recall_cue, "max_points": str(st.max_points), "criticality": st.criticality,
                "knowledge_codes": st.knowledge_codes, "reviewed": ev is not None}
        if ev is not None:  # reference is revealed only after the student committed a rating
            card.update(rating=ev.rating, self_score=str(ev.self_score), reference_latex=st.reference_latex,
                        explanation=st.explanation)
        elif current_index is None:
            current_index = i
        cards.append(card)
    total = sum(Decimal(c["max_points"]) for c in cards)
    earned = sum(Decimal(c.get("self_score", "0")) for c in cards)
    codes = sorted({c for card in cards for c in card["knowledge_codes"]})
    assessed = {a.knowledge_code: a.level for a in s.scalars(select(KnowledgeSelfAssessment).where(KnowledgeSelfAssessment.attempt_id == att.id))}
    rev = s.get(ProblemRevision, att.problem_revision_id) if att.problem_revision_id else None
    return {
        "attempt_id": att.id, "mode": att.mode, "state": att.state, "algorithm_version": ALGORITHM_VERSION,
        "problem": None if rev is None else {"revision_id": rev.id, "title": rev.title, "shared_statement": rev.shared_statement,
                                             "parts": [{"id": p.id, "part_key": p.part_key, "prompt": p.prompt, "max_score": str(p.max_score)} for p in rev.parts]},
        "cards": cards, "current_index": current_index,
        "self_recall_score": str(earned), "self_recall_max": str(total),
        "score_label": "主观自评参考分（非正式数学成绩）",
        "knowledge_codes": codes, "knowledge_assessed": assessed,
    }


def review(s: Session, user: User, attempt_id: str, event_id: str, step_id: str, rating: str,
           revealed_before_rating: bool = False) -> dict:
    if rating not in GRADE:
        raise ApiError("VALIDATION_FAILED", "rating must be know / fuzzy / unsure")
    if not event_id or len(event_id) < 8:
        raise ApiError("VALIDATION_FAILED", "event_id (client UUID) required")
    att = _get_owned(s, user, attempt_id)
    prior = s.get(StepReviewEvent, event_id)
    if prior is not None:
        if prior.user_id != user.id or prior.step_id != step_id or prior.rating != rating or prior.attempt_id != att.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "event_id reused with different payload")
        return _review_result(s, prior, replayed=True, xp=0)
    if step_id not in att.card_ids:
        raise ApiError("VALIDATION_FAILED", "step is not part of this attempt")
    done = {e.step_id for e in s.scalars(select(StepReviewEvent).where(StepReviewEvent.attempt_id == att.id))}
    if step_id in done:
        raise ApiError("CONFLICT", "this step was already rated in this attempt (ratings are append-only)")
    idx = att.card_ids.index(step_id)
    if any(cid not in done for cid in att.card_ids[:idx]):
        raise ApiError("VALIDATION_FAILED", "rate the steps in order; future answers stay hidden")
    step = s.get(ReasoningStep, step_id)
    max_points = Decimal(step.max_points)
    ev = StepReviewEvent(id=event_id, user_id=user.id, attempt_id=att.id, step_id=step_id, rating=rating,
                         revealed_before_rating=revealed_before_rating, max_points=max_points,
                         self_score=(max_points * GRADE[rating]).quantize(Decimal("0.01")), algorithm_version=ALGORITHM_VERSION)
    s.add(ev)
    now = utcnow()
    st = s.get(StepReviewState, (user.id, step_id, SCHEDULER_VERSION))
    due = now + timedelta(days=INTERVAL_DAYS[rating])
    if st is None:
        s.add(StepReviewState(user_id=user.id, step_id=step_id, scheduler_version=SCHEDULER_VERSION, due_at=due,
                              review_count=1, last_rating=rating))
    else:
        st.due_at, st.last_rating, st.review_count = due, rating, st.review_count + 1
    # XP is decoupled from the rating so honest "unsure" never costs XP; one award per step per local day.
    local_day = now.astimezone(ZoneInfo(user.timezone or "UTC")).date().isoformat()
    xp = 0
    if s.get(XpAward, (user.id, step_id, local_day)) is None:
        xp = 5 + min(5, math.floor(max_points))
        s.add(XpAward(user_id=user.id, step_id=step_id, local_day=local_day, amount=xp))
    s.flush()
    if all(cid in done | {step_id} for cid in att.card_ids) and att.mode == "due":
        att.state, att.finished_at = "completed", now
    return _review_result(s, ev, replayed=False, xp=xp)


def _review_result(s: Session, ev: StepReviewEvent, replayed: bool, xp: int) -> dict:
    step = s.get(ReasoningStep, ev.step_id)
    st = s.get(StepReviewState, (ev.user_id, ev.step_id, SCHEDULER_VERSION))
    return {"event_id": ev.id, "replayed": replayed, "rating": ev.rating, "self_score": str(ev.self_score),
            "max_points": str(ev.max_points), "xp_awarded": xp, "reference_latex": step.reference_latex,
            "explanation": step.explanation, "next_due_at": st.due_at.isoformat() if st else None}


def knowledge_feedback(s: Session, user: User, attempt_id: str, levels: dict[str, int]) -> dict:
    att = _get_owned(s, user, attempt_id)
    if att.mode != "full":
        raise ApiError("VALIDATION_FAILED", "knowledge feedback applies to full-problem attempts")
    allowed = {c for sid in att.card_ids for c in (s.get(ReasoningStep, sid).knowledge_codes or [])}
    reviewed = {e.step_id for e in s.scalars(select(StepReviewEvent).where(StepReviewEvent.attempt_id == att.id))}
    if set(att.card_ids) - reviewed:
        raise ApiError("VALIDATION_FAILED", "finish all steps first")
    if set(levels) != allowed:
        raise ApiError("VALIDATION_FAILED", "rate exactly the tested knowledge points", {"expected": sorted(allowed)})
    for code, level in levels.items():
        if not isinstance(level, int) or not 1 <= level <= 4:
            raise ApiError("VALIDATION_FAILED", "levels are 1..4")
        if s.scalar(select(KnowledgeSelfAssessment).where(KnowledgeSelfAssessment.attempt_id == att.id,
                                                          KnowledgeSelfAssessment.knowledge_code == code)) is None:
            s.add(KnowledgeSelfAssessment(user_id=user.id, attempt_id=att.id, knowledge_code=code, level=level))
    att.state, att.finished_at = "completed", utcnow()
    s.flush()
    return view(s, user, att.id)


def profile(s: Session, user: User) -> dict:
    """Self-reported evidence index per knowledge code (Beta(2,2) prior). NOT an exam accuracy."""
    stats: dict[str, dict] = {}

    def node(code: str) -> dict:
        title = s.scalar(select(KnowledgeNode.title).where(KnowledgeNode.external_code == code).limit(1)) or code
        return stats.setdefault(code, {"code": code, "title": title, "alpha": PRIOR_ALPHA, "beta": PRIOR_BETA,
                                       "step_observations": 0, "self_assessments": 0})

    events = s.scalars(select(StepReviewEvent).where(StepReviewEvent.user_id == user.id).order_by(StepReviewEvent.occurred_at)).all()
    weak = {}
    calendar: dict[str, int] = {}
    tz = ZoneInfo(user.timezone or "UTC")
    for ev in events:
        step = s.get(ReasoningStep, ev.step_id)
        w = float(ev.max_points) * (0.3 if ev.revealed_before_rating else 1.0)  # peeking lowers evidence weight
        g = float(GRADE[ev.rating])
        for code in step.knowledge_codes or []:
            n = node(code)
            n["alpha"] += w * g
            n["beta"] += w * (1 - g)
            n["step_observations"] += 1
        day = _aware(ev.occurred_at).astimezone(tz).date().isoformat()
        calendar[day] = calendar.get(day, 0) + 1
        if step.criticality == "key":
            if ev.rating in ("fuzzy", "unsure"):
                weak[step.id] = {"step_id": step.id, "recall_cue": step.recall_cue, "rating": ev.rating,
                                 "knowledge_codes": step.knowledge_codes}
            else:
                weak.pop(step.id, None)
    for a in s.scalars(select(KnowledgeSelfAssessment).where(KnowledgeSelfAssessment.user_id == user.id)):
        n = node(a.knowledge_code)
        v = (a.level - 1) / 3
        n["alpha"] += SELF_ASSESS_WEIGHT * v
        n["beta"] += SELF_ASSESS_WEIGHT * (1 - v)
        n["self_assessments"] += 1
    knowledge = []
    for n in stats.values():
        idx = 100 * n["alpha"] / (n["alpha"] + n["beta"])
        knowledge.append({**{k: n[k] for k in ("code", "title", "step_observations", "self_assessments")},
                          "evidence_index": round(idx, 1), "low_sample": n["step_observations"] < 5})
    now = utcnow()
    states = s.scalars(select(StepReviewState).where(StepReviewState.user_id == user.id)).all()
    xp_total = s.scalar(select(func.coalesce(func.sum(XpAward.amount), 0)).where(XpAward.user_id == user.id)) or 0
    return {
        "label": "自评证据指数（主观自报，非考试正确率；样本少时不可比较）",
        "algorithm_version": ALGORITHM_VERSION, "scheduler_version": SCHEDULER_VERSION,
        "knowledge": sorted(knowledge, key=lambda k: k["code"]),
        "due_now": sum(1 for st in states if _aware(st.due_at) <= now),
        "scheduled": len(states),
        "weak_key_steps": list(weak.values())[-8:],
        "xp_total": int(xp_total),
        "calendar": calendar,
        "reviews_total": len(events),
    }
