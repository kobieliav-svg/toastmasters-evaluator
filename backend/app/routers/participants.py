from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/participants", tags=["participants"])


@router.get("/", response_model=List[schemas.Participant])
def list_participants(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.Participant)
    if not include_inactive:
        q = q.filter(models.Participant.active == True)  # noqa: E712
    return q.order_by(models.Participant.name).all()


@router.post("/", response_model=schemas.Participant)
def create_participant(payload: schemas.ParticipantCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Participant).filter(models.Participant.name == payload.name).first()
    if existing:
        raise HTTPException(400, "A participant with this name already exists")
    p = models.Participant(**payload.dict())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{participant_id}", response_model=schemas.Participant)
def update_participant(participant_id: int, payload: schemas.ParticipantUpdate, db: Session = Depends(get_db)):
    p = db.query(models.Participant).get(participant_id)
    if not p:
        raise HTTPException(404, "Participant not found")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{participant_id}")
def deactivate_participant(participant_id: int, db: Session = Depends(get_db)):
    """Soft-delete: keeps history/trend data intact, just hides from active roster."""
    p = db.query(models.Participant).get(participant_id)
    if not p:
        raise HTTPException(404, "Participant not found")
    p.active = False
    db.commit()
    return {"ok": True}
