from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/entries", tags=["entries"])


@router.post("", response_model=schemas.EntryOut, status_code=201)
def create_entry(
    payload: schemas.EntryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    substance = None
    if payload.substance_id:
        substance = (
            db.query(models.Substance)
            .filter(models.Substance.id == payload.substance_id, models.Substance.user_id == user.id)
            .first()
        )
        if not substance:
            raise HTTPException(status_code=404, detail="Substance introuvable")

    # Même règle que logEntry dans mockData.js : prix saisi s'il y en a un,
    # sinon estimé à partir du coût unitaire de la substance.
    price = payload.price
    if price is None and substance and substance.unit_cost is not None:
        price = round(payload.quantity * substance.unit_cost, 2)

    entry = models.ConsumptionEntry(
        price=price,
        user_id=user.id,
        substance_id=payload.substance_id,
        type=payload.type,
        quantity=payload.quantity,
        context=payload.context,
        mood=payload.mood,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(entry)
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
