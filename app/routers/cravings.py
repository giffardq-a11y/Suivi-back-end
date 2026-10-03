"""Sessions d'aide au craving : minuteur de report + respiration guidée +
rappel de la raison (côté app), puis journal de l'issue.

Préfixe /craving-sessions et non /cravings : GET et POST /cravings sont déjà
pris par les envies du module Humeur (routers/mood.py, table
craving_entries), dont le comportement ne doit pas changer.

Cycle de vie : POST démarre (issue 'en_cours') ; PUT termine avec
'resiste' | 'cede' | 'abandonne' et fixe ended_at. Une session terminée
garde son issue (409 si on tente d'en changer, y compris revenir à
'en_cours') ; la note, le déclencheur et l'intensité de fin restent
modifiables. 'cede' + log_entry crée l'entrée de consommation par le même
service que POST /entries (services/entries.py) et la lie (entry_id) — une
seule fois : un second appel ne crée pas de doublon.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import cravings as service
from ..services.common import aware, fuseau_utilisateur, now_utc
from ..services.entries import creer_entree

router = APIRouter(prefix="/craving-sessions", tags=["cravings"])

EN_COURS = models.CravingOutcome.EN_COURS.value
CEDE = models.CravingOutcome.CEDE.value
RESISTE = models.CravingOutcome.RESISTE.value


def _substance(db: Session, user: models.User, substance_id: str) -> models.Substance:
    sub = (
        db.query(models.Substance)
        .filter(models.Substance.id == substance_id, models.Substance.user_id == user.id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Consommation introuvable")
    return sub


def _sessions(db: Session, user: models.User, substance_id: str | None, days: int | None):
    q = db.query(models.Craving).filter(models.Craving.user_id == user.id)
    if substance_id:
        _substance(db, user, substance_id)
        q = q.filter(models.Craving.substance_id == substance_id)
    if days:
        q = q.filter(models.Craving.started_at >= now_utc() - timedelta(days=days))
    return q


@router.post("", response_model=schemas.CravingOut, status_code=201)
def start_craving(
    payload: schemas.CravingStart,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _substance(db, user, payload.substance_id)
    c = models.Craving(
        user_id=user.id, substance_id=payload.substance_id, started_at=now_utc(),
        planned_seconds=payload.planned_seconds, intensity_start=payload.intensity_start,
        trigger_label=payload.trigger, outcome=EN_COURS,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return service.serialiser(c)


@router.get("", response_model=list[schemas.CravingOut])
def list_cravings(
    substance_id: str | None = None,
    days: int | None = Query(None, ge=1, le=3660),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sessions = (
        _sessions(db, user, substance_id, days)
        .order_by(models.Craving.started_at.desc())
        .offset(offset).limit(limit).all()
    )
    return [service.serialiser(c) for c in sessions]


@router.get("/stats", response_model=schemas.CravingStats)
def craving_stats(
    substance_id: str | None = None,
    days: int = Query(30, ge=1, le=3660),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sessions = _sessions(db, user, substance_id, days).all()
    return service.statistiques(sessions, fuseau_utilisateur(user), days, substance_id)


@router.get("/suggestion", response_model=schemas.CravingSuggestion)
def craving_suggestion(
    substance_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Raison = substances.reason (« Pourquoi je réduis »), null si non
    renseignée. Aucun repli sur un autre champ : ni le profil ni les
    objectifs n'ont de champ raison/motivation, et Substance.note est une
    note libre (« Note / justification »), pas forcément une motivation."""
    sub = _substance(db, user, substance_id)
    resistes = (
        _sessions(db, user, substance_id, 7)
        .filter(models.Craving.outcome == RESISTE)
        .count()
    )
    return schemas.CravingSuggestion(substance_id=sub.id, raison=sub.reason, derniers_resistes=resistes)


@router.put("/{craving_id}", response_model=schemas.CravingOut)
def update_craving(
    craving_id: str,
    payload: schemas.CravingUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    c = (
        db.query(models.Craving)
        .filter(models.Craving.id == craving_id, models.Craving.user_id == user.id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Craving introuvable")

    nouvelle = payload.outcome.value if payload.outcome is not None else c.outcome
    if c.outcome != EN_COURS and nouvelle != c.outcome:
        raise HTTPException(status_code=409, detail="Session déjà terminée : son issue ne change plus")
    if payload.log_entry and nouvelle != CEDE:
        raise HTTPException(status_code=422, detail="log_entry n'a de sens qu'avec l'issue 'cede'")

    champs = payload.model_fields_set
    if "intensity_end" in champs:
        c.intensity_end = payload.intensity_end
    if "note" in champs:
        c.note = payload.note
    if "trigger" in champs:
        c.trigger_label = payload.trigger
    if nouvelle != c.outcome:
        c.outcome = nouvelle
        c.ended_at = now_utc()

    if payload.log_entry and c.entry_id is None:
        entree = creer_entree(db, user, schemas.EntryCreate(
            substance_id=c.substance_id, quantity=payload.quantity,
            occurred_at=aware(c.ended_at) if c.ended_at else now_utc(),
        ))
        db.flush()
        c.entry_id = entree.id

    db.commit()
    db.refresh(c)
    return service.serialiser(c)
