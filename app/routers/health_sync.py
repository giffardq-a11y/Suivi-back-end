"""Import des données de la montre (Samsung Galaxy Watch → Samsung Health →
Health Connect → app).

Le téléphone lit Health Connect et envoie ici ce qu'il a trouvé ; le serveur
range chaque élément dans la table qui existe déjà (course, autre sport,
muscu, poids) plus deux nouvelles (sommeil, pas).

Anti-doublon : chaque enregistrement Health Connect a un identifiant stable,
conservé dans `external_id`. Une synchronisation qui renvoie les mêmes
séances ne crée rien de nouveau, elle met à jour les valeurs (une séance peut
être complétée après coup par la montre).

Rien n'est supprimé côté app si l'élément disparaît de la montre : une
donnée saisie à la main n'a pas à être effacée par une synchronisation.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import date_key, from_ms, is_same_day, now_utc
from ..services.sport import increment_session_goals, mark_sport_habits_done_today

router = APIRouter(prefix="/health", tags=["health"])

SOURCE = "health_connect"

# Types d'exercice Health Connect regroupés par destination dans l'app.
COURSE = {"running", "running_treadmill"}
NATATION = {"swimming_pool", "swimming_open_water"}
MUSCU = {"strength_training", "weightlifting"}


class ExerciseIn(BaseModel):
    externalId: str
    type: str                       # 'running', 'swimming_pool', 'strength_training'...
    label: str | None = None        # titre affiché par la montre
    startMs: int
    durationMin: float
    distanceKm: float | None = None
    calories: int | None = None
    heartRateAvg: int | None = None
    heartRateMax: int | None = None


class SleepIn(BaseModel):
    externalId: str
    startMs: int
    endMs: int


class StepsIn(BaseModel):
    dateKey: str                    # 'YYYY-MM-DD'
    steps: int


class WeightIn(BaseModel):
    externalId: str
    weightKg: float
    occurredMs: int


class HealthImportIn(BaseModel):
    exercises: list[ExerciseIn] = []
    sleep: list[SleepIn] = []
    steps: list[StepsIn] = []
    weights: list[WeightIn] = []


def _existing(db: Session, model, user_id: str, external_id: str):
    return (
        db.query(model)
        .filter(model.user_id == user_id, model.source == SOURCE, model.external_id == external_id)
        .first()
    )


def _import_exercise(db: Session, user: models.User, ex: ExerciseIn) -> str:
    """Range une séance dans la bonne table. Renvoie 'cree' ou 'maj'."""
    occurred = from_ms(ex.startMs)
    kind = (ex.type or "").lower()

    if kind in COURSE:
        model, champs = models.Run, {
            "distance_km": ex.distanceKm or 0,
            "duration_min": ex.durationMin,
            "calories_burned": ex.calories or 0,
        }
    elif kind in MUSCU:
        model, champs = models.StrengthSession, {
            "template_name": ex.label or "Séance (montre)",
            "mode": "watch",
            "duration_min": ex.durationMin,
            "calories_burned": ex.calories or 0,
            "exercises": [],
        }
    else:
        label = ex.label or ("Natation" if kind in NATATION else kind.replace("_", " ").capitalize() or "Sport")
        model, champs = models.OtherSportLog, {
            "sport_label": label,
            "duration_min": ex.durationMin,
            "distance_km": ex.distanceKm,
            "calories_burned": ex.calories or 0,
            "intensity": None,
        }

    champs.update({
        "occurred_at": occurred,
        "heart_rate_avg": ex.heartRateAvg,
        "heart_rate_max": ex.heartRateMax,
    })

    ligne = _existing(db, model, user.id, ex.externalId)
    if ligne:
        for k, v in champs.items():
            setattr(ligne, k, v)
        return "maj"

    db.add(model(user_id=user.id, source=SOURCE, external_id=ex.externalId, **champs))
    return "cree"


def _mark_sleep_habits(db: Session, user: models.User, nuit: models.SleepLog) -> None:
    """Coche les habitudes liées au sommeil pour le jour du réveil."""
    habits = (
        db.query(models.Habit)
        .filter(models.Habit.user_id == user.id, models.Habit.linked_activity == "sleep_session")
        .all()
    )
    for h in habits:
        if not any(is_same_day(l.occurred_at, nuit.ended_at) for l in h.logs):
            db.add(models.HabitLog(habit_id=h.id, occurred_at=nuit.ended_at))


@router.post("/import", status_code=201)
def import_health(
    payload: HealthImportIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    resume = {"seances_creees": 0, "seances_mises_a_jour": 0, "nuits": 0, "jours_de_pas": 0, "pesees": 0}

    seances_nouvelles = 0
    for ex in payload.exercises:
        resultat = _import_exercise(db, user, ex)
        if resultat == "cree":
            resume["seances_creees"] += 1
            seances_nouvelles += 1
        else:
            resume["seances_mises_a_jour"] += 1

    for nuit in payload.sleep:
        debut, fin = from_ms(nuit.startMs), from_ms(nuit.endMs)
        ligne = _existing(db, models.SleepLog, user.id, nuit.externalId)
        duree = max(0.0, (fin - debut).total_seconds() / 60)
        if ligne:
            ligne.started_at, ligne.ended_at, ligne.duration_min = debut, fin, duree
            ligne.date_key = date_key(fin)
        else:
            ligne = models.SleepLog(
                user_id=user.id, source=SOURCE, external_id=nuit.externalId,
                started_at=debut, ended_at=fin, duration_min=duree, date_key=date_key(fin),
            )
            db.add(ligne)
            resume["nuits"] += 1
        _mark_sleep_habits(db, user, ligne)

    for jour in payload.steps:
        ligne = (
            db.query(models.DailySteps)
            .filter(models.DailySteps.user_id == user.id, models.DailySteps.date_key == jour.dateKey)
            .first()
        )
        if ligne:
            ligne.steps = jour.steps
        else:
            db.add(models.DailySteps(user_id=user.id, date_key=jour.dateKey, steps=jour.steps, source=SOURCE))
        resume["jours_de_pas"] += 1

    for pesee in payload.weights:
        if _existing(db, models.WeightEntry, user.id, pesee.externalId):
            continue
        db.add(models.WeightEntry(
            user_id=user.id, source=SOURCE, external_id=pesee.externalId,
            weight_kg=pesee.weightKg, occurred_at=from_ms(pesee.occurredMs),
            note="Importé de la montre",
        ))
        resume["pesees"] += 1

    db.commit()

    # Une séance importée compte comme une séance faite : mêmes effets qu'une
    # séance saisie à la main (objectifs "nombre de séances", habitudes sport).
    if seances_nouvelles:
        for _ in range(seances_nouvelles):
            increment_session_goals(db, user)
        mark_sport_habits_done_today(db, user)
    else:
        db.commit()

    return {"ok": True, **resume}


@router.get("/summary")
def health_summary(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Ce que l'app affiche dans Paramètres : dernière synchro et volumes."""
    dernieres = []
    for model in (models.Run, models.OtherSportLog, models.StrengthSession):
        ligne = (
            db.query(model)
            .filter(model.user_id == user.id, model.source == SOURCE)
            .order_by(model.occurred_at.desc())
            .first()
        )
        if ligne:
            dernieres.append(ligne.occurred_at)

    nuits = db.query(models.SleepLog).filter(models.SleepLog.user_id == user.id).all()
    pas = db.query(models.DailySteps).filter(models.DailySteps.user_id == user.id).all()
    derniere_nuit = max(nuits, key=lambda n: n.ended_at, default=None)
    aujourdhui = date_key(now_utc())

    return {
        "seances_importees": sum(
            db.query(m).filter(m.user_id == user.id, m.source == SOURCE).count()
            for m in (models.Run, models.OtherSportLog, models.StrengthSession)
        ),
        "derniere_seance_ms": int(max(dernieres).timestamp() * 1000) if dernieres else None,
        "nuits_importees": len(nuits),
        "derniere_nuit_min": derniere_nuit.duration_min if derniere_nuit else None,
        "pas_aujourdhui": next((p.steps for p in pas if p.date_key == aujourdhui), None),
        "pesees_importees": db.query(models.WeightEntry).filter(
            models.WeightEntry.user_id == user.id, models.WeightEntry.source == SOURCE
        ).count(),
    }
