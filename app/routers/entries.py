from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services.entries import creer_entree

router = APIRouter(prefix="/entries", tags=["entries"])


@router.post("", response_model=schemas.EntryOut, status_code=201)
def create_entry(
    payload: schemas.EntryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Logique dans services/entries.py, partagée avec les sessions de craving.
    entry = creer_entree(db, user, payload)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=list[schemas.EntryOut])
def list_entries(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id)
        .order_by(models.ConsumptionEntry.occurred_at.desc())
        .limit(50)
        .all()
    )
