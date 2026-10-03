"""Création d'une entrée de consommation : logique unique, partagée par
POST /entries et par la fin d'une session de craving « cédé » avec
log_entry (PUT /craving-sessions/{id}). L'appelant committe."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas


def creer_entree(db: Session, user: models.User, payload: schemas.EntryCreate) -> models.ConsumptionEntry:
    """Ajoute l'entrée à la session (sans commit). 404 si la substance
    indiquée n'appartient pas à l'utilisateur."""
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
    return entry
