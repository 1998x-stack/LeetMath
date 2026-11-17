"""Phase 1.5 learning API under /api/v1/learning (docs/reasoning-practice/LEARNING_SCHEMA.md §5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import User
from ..services import reasoning
from .common import current_user, db, optional_user

router = APIRouter(prefix="/api/v1/learning")


@router.get("/catalog")
def catalog(s: Session = Depends(db), _u: User | None = Depends(optional_user)):
    return {"items": reasoning.practice_catalog(s)}


class StartIn(BaseModel):
    problem_revision_id: str | None = None
    mode: str = "full"


@router.post("/attempts", status_code=201)
def start(body: StartIn, s: Session = Depends(db), user: User = Depends(current_user)):
    att = reasoning.start(s, user, body.problem_revision_id, body.mode)
    return reasoning.view(s, user, att.id)


@router.get("/attempts/{aid}")
def view(aid: str, s: Session = Depends(db), user: User = Depends(current_user)):
    return reasoning.view(s, user, aid)


class ReviewIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    step_id: str
    rating: str
    revealed_before_rating: bool = False


@router.post("/attempts/{aid}/step-reviews")
def step_review(aid: str, body: ReviewIn, s: Session = Depends(db), user: User = Depends(current_user)):
    return reasoning.review(s, user, aid, body.event_id, body.step_id, body.rating, body.revealed_before_rating)


class FeedbackIn(BaseModel):
    levels: dict[str, int]


@router.post("/attempts/{aid}/knowledge-feedback")
def feedback(aid: str, body: FeedbackIn, s: Session = Depends(db), user: User = Depends(current_user)):
    return reasoning.knowledge_feedback(s, user, aid, body.levels)


@router.get("/profile")
def profile(s: Session = Depends(db), user: User = Depends(current_user)):
    return reasoning.profile(s, user)
