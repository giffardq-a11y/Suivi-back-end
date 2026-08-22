from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, to_ms, relative_time, start_of_week, start_of_day
from ..services.sport import (
    estimate_run_calories, estimate_strength_calories, estimate_other_sport_calories,
    calories_burned_on, increment_session_goals, mark_sport_habits_done_today,
)

router = APIRouter(tags=["training"])

OTHER_SPORTS = [
    "Vélo", "Natation", "Yoga", "Tennis", "Football", "Basketball", "Boxe", "Escalade",
    "Rameur", "HIIT", "Danse", "Ski", "Randonnée", "Golf", "Volleyball", "Pilates",
]

# Bibliothèque d'exercices — statique, sert le sélecteur du formulaire
# "Nouveau type de séance" (voir EXERCISE_LIBRARY côté mock).
EXERCISE_LIBRARY = [
    {"id": "lib-bench", "name": "Développé couché", "category": "salle_muscu"},
    {"id": "lib-incline-bench", "name": "Développé incliné haltères", "category": "salle_muscu"},
    {"id": "lib-military", "name": "Développé militaire", "category": "salle_muscu"},
    {"id": "lib-row-bar", "name": "Rowing barre", "category": "salle_muscu"},
    {"id": "lib-row-dumbbell", "name": "Rowing haltère", "category": "salle_muscu"},
    {"id": "lib-lat-pulldown", "name": "Tirage vertical", "category": "salle_muscu"},
    {"id": "lib-leg-press", "name": "Presse à cuisses", "category": "salle_muscu"},
    {"id": "lib-squat-guided", "name": "Squat guidé", "category": "salle_muscu"},
    {"id": "lib-leg-curl", "name": "Leg curl", "category": "salle_muscu"},
    {"id": "lib-leg-extension", "name": "Leg extension", "category": "salle_muscu"},
    {"id": "lib-curl-bar", "name": "Curl biceps barre", "category": "salle_muscu"},
    {"id": "lib-triceps-pulley", "name": "Extension triceps poulie", "category": "salle_muscu"},
    {"id": "lib-deadlift", "name": "Soulevé de terre", "category": "salle_muscu"},
    {"id": "lib-hip-thrust", "name": "Hip thrust", "category": "salle_muscu"},
    {"id": "lib-flyes", "name": "Écarté couché", "category": "salle_muscu"},
    {"id": "lib-shrugs", "name": "Shrugs", "category": "salle_muscu"},
    {"id": "lib-calf-machine", "name": "Extension mollets machine", "category": "salle_muscu"},
    {"id": "lib-cable-crossover", "name": "Écarté poulie vis-à-vis", "category": "salle_muscu"},
    {"id": "lib-pushup", "name": "Pompes", "category": "poids_du_corps"},
    {"id": "lib-pushup-diamond", "name": "Pompes diamant", "category": "poids_du_corps"},
    {"id": "lib-squat-bw", "name": "Squats", "category": "poids_du_corps"},
    {"id": "lib-lunges-bw", "name": "Fentes", "category": "poids_du_corps"},
    {"id": "lib-lunges-jump", "name": "Fentes sautées", "category": "poids_du_corps"},
    {"id": "lib-plank", "name": "Gainage (planche)", "category": "poids_du_corps"},
    {"id": "lib-mountain-climbers", "name": "Mountain climbers", "category": "poids_du_corps"},
    {"id": "lib-burpees", "name": "Burpees", "category": "poids_du_corps"},
    {"id": "lib-superman", "name": "Superman", "category": "poids_du_corps"},
    {"id": "lib-crunch", "name": "Crunchs", "category": "poids_du_corps"},
    {"id": "lib-leg-raise", "name": "Relevé de jambes", "category": "poids_du_corps"},
    {"id": "lib-wall-sit", "name": "Chaise isométrique", "category": "poids_du_corps"},
    {"id": "lib-jumping-jacks", "name": "Jumping jacks", "category": "poids_du_corps"},
    {"id": "lib-glute-bridge", "name": "Pont fessier", "category": "poids_du_corps"},
    {"id": "lib-pullup", "name": "Tractions", "category": "calisthenie"},
    {"id": "lib-pullup-weighted", "name": "Tractions lestées", "category": "calisthenie"},
    {"id": "lib-pullup-australian", "name": "Tractions australiennes", "category": "calisthenie"},
    {"id": "lib-dips", "name": "Dips", "category": "calisthenie"},
    {"id": "lib-muscle-up", "name": "Muscle-up", "category": "calisthenie"},
    {"id": "lib-handstand-pushup", "name": "Handstand push-up", "category": "calisthenie"},
    {"id": "lib-pistol-squat", "name": "Pistol squat", "category": "calisthenie"},
    {"id": "lib-front-lever", "name": "Front lever", "category": "calisthenie"},
    {"id": "lib-back-lever", "name": "Back lever", "category": "calisthenie"},
    {"id": "lib-l-sit", "name": "L-sit", "category": "calisthenie"},
    {"id": "lib-planche", "name": "Planche (skill)", "category": "calisthenie"},
    {"id": "lib-human-flag", "name": "Human flag", "category": "calisthenie"},
    {"id": "lib-archer-pushup", "name": "Pompes archer", "category": "calisthenie"},
]


class RunCreate(BaseModel):
    distanceKm: float
    durationMin: float
    caloriesOverride: int | None = None


class OtherSportCreate(BaseModel):
    sportLabel: str
    durationMin: float
    intensity: str | None = None
    distanceKm: float | None = None
    caloriesOverride: int | None = None


class WorkoutTemplateCreate(BaseModel):
    name: str
    exercises: list[dict]
    scheduledTime: str | None = None
    notificationsEnabled: bool = False


class StrengthSessionLog(BaseModel):
    templateId: str | None = None
    templateName: str | None = None
    mode: str = "quick_duration"
    durationMin: float = 0
    caloriesBurned: int | None = None
    exercises: list[dict] = []


@router.get("/training")
def get_training(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    runs = (
        db.query(models.Run)
        .filter(models.Run.user_id == user.id)
        .order_by(models.Run.occurred_at.desc())
        .all()
    )
    other_log = (
        db.query(models.OtherSportLog)
        .filter(models.OtherSportLog.user_id == user.id)
        .order_by(models.OtherSportLog.occurred_at.desc())
        .limit(10)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id, "distanceKm": r.distance_km, "durationMin": r.duration_min,
                "occurredAt": to_ms(r.occurred_at), "caloriesBurned": r.calories_burned,
                "paceMinPerKm": f"{(r.duration_min / r.distance_km):.2f}" if r.distance_km else "0.00",
                "relativeTime": relative_time(r.occurred_at),
            }
            for r in runs
        ],
        "other_sports": OTHER_SPORTS,
        "other_sports_log": [
            {
                "id": s.id, "sportLabel": s.sport_label, "durationMin": s.duration_min,
                "intensity": s.intensity, "distanceKm": s.distance_km,
                "occurredAt": to_ms(s.occurred_at), "caloriesBurned": s.calories_burned,
            }
            for s in other_log
        ],
    }


@router.post("/training/runs", status_code=201)
def add_run(
    payload: RunCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    calories = payload.caloriesOverride or estimate_run_calories(payload.durationMin)
    db.add(models.Run(
        user_id=user.id, distance_km=payload.distanceKm, duration_min=payload.durationMin,
        calories_burned=calories, occurred_at=now_utc(),
    ))
    db.commit()
    increment_session_goals(db, user)
    mark_sport_habits_done_today(db, user)
    return {"ok": True}


@router.post("/training/other-sports", status_code=201)
def log_other_sport(
    payload: OtherSportCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    calories = payload.caloriesOverride or estimate_other_sport_calories(payload.durationMin, payload.intensity)
    db.add(models.OtherSportLog(
        user_id=user.id, sport_label=payload.sportLabel, duration_min=payload.durationMin,
        intensity=payload.intensity, distance_km=payload.distanceKm,
        calories_burned=calories, occurred_at=now_utc(),
    ))
    db.commit()
    increment_session_goals(db, user)
    mark_sport_habits_done_today(db, user)
    return {"ok": True}


@router.get("/workout-templates")
def get_workout_templates(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    templates = (
        db.query(models.WorkoutTemplate)
        .filter(or_(models.WorkoutTemplate.user_id == user.id, models.WorkoutTemplate.user_id.is_(None)))
        .all()
    )
    return [
        {
            "id": t.id, "name": t.name, "exerciseCount": len(t.exercises or []),
            "scheduledTime": t.scheduled_time, "notificationsEnabled": t.notifications_enabled,
        }
        for t in templates
    ]


@router.get("/workout-templates/{template_id}")
def get_workout_template_detail(
    template_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tpl = (
        db.query(models.WorkoutTemplate)
        .filter(
            models.WorkoutTemplate.id == template_id,
            or_(models.WorkoutTemplate.user_id == user.id, models.WorkoutTemplate.user_id.is_(None)),
        )
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Modèle de séance introuvable.")
    return {
        "id": tpl.id, "name": tpl.name, "exercises": tpl.exercises,
        "scheduledTime": tpl.scheduled_time, "notificationsEnabled": tpl.notifications_enabled,
    }


@router.post("/workout-templates", status_code=201)
def add_workout_template(
    payload: WorkoutTemplateCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    exercises = [
        {
            "id": e.get("id") or f"ex-{i}",
            "name": e["name"],
            "sets": e.get("sets", []),
            "restSeconds": e.get("restSeconds", 90),
        }
        for i, e in enumerate(payload.exercises)
    ]
    tpl = models.WorkoutTemplate(
        user_id=user.id, name=payload.name, exercises=exercises,
        scheduled_time=payload.scheduledTime, notifications_enabled=payload.notificationsEnabled,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return {"ok": True, "id": tpl.id}


@router.post("/strength-sessions", status_code=201)
def log_strength_session(
    payload: StrengthSessionLog,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    calories = payload.caloriesBurned or estimate_strength_calories(payload.mode, payload.durationMin)
    db.add(models.StrengthSession(
        user_id=user.id, template_id=payload.templateId, template_name=payload.templateName,
        mode=payload.mode, duration_min=payload.durationMin, calories_burned=calories,
        exercises=payload.exercises, occurred_at=now_utc(),
    ))
    db.commit()
    increment_session_goals(db, user)
    mark_sport_habits_done_today(db, user)
    return {"ok": True}


@router.get("/strength-sessions")
def get_strength_sessions(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    sessions = (
        db.query(models.StrengthSession)
        .filter(models.StrengthSession.user_id == user.id)
        .order_by(models.StrengthSession.occurred_at.desc())
        .all()
    )
    return [
        {
            "id": s.id, "templateId": s.template_id, "templateName": s.template_name,
            "mode": s.mode, "durationMin": s.duration_min, "caloriesBurned": s.calories_burned,
            "exercises": s.exercises, "occurredAt": to_ms(s.occurred_at),
            "relativeTime": relative_time(s.occurred_at),
        }
        for s in sessions
    ]


@router.get("/exercise-library")
def get_exercise_library():
    return EXERCISE_LIBRARY


@router.get("/stats/sport")
def get_sport_stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    week_start = start_of_week(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    runs = db.query(models.Run).filter(models.Run.user_id == user.id).all()
    strength = db.query(models.StrengthSession).filter(models.StrengthSession.user_id == user.id).all()
    other = db.query(models.OtherSportLog).filter(models.OtherSportLog.user_id == user.id).all()

    all_sessions = (
        [("course", r.occurred_at, r.calories_burned or 0) for r in runs]
        + [("muscu", s.occurred_at, s.calories_burned or 0) for s in strength]
        + [("autre", o.occurred_at, o.calories_burned or 0) for o in other]
    )

    def tz_aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=week_start.tzinfo)

    sessions_week = [s for s in all_sessions if tz_aware(s[1]) >= week_start]
    sessions_month = [s for s in all_sessions if tz_aware(s[1]) >= month_start]

    calories_week = sum(s[2] for s in sessions_week)
    calories_month = sum(s[2] for s in sessions_month)
    distance_week_km = sum(r.distance_km for r in runs if tz_aware(r.occurred_at) >= week_start)

    by_type_week = {"course": 0, "muscu": 0, "autre": 0}
    for t, _, _ in sessions_week:
        by_type_week[t] = by_type_week.get(t, 0) + 1

    recent = sorted(all_sessions, key=lambda s: s[1], reverse=True)[:8]

    return {
        "sessions_this_week": len(sessions_week),
        "sessions_this_month": len(sessions_month),
        "calories_this_week": round(calories_week),
        "calories_this_month": round(calories_month),
        "distance_week_km": round(distance_week_km * 10) / 10,
        "by_type_week": by_type_week,
        "recent_sessions": [
            {"type": t, "calories": round(c), "relativeTime": relative_time(dt)}
            for t, dt, c in recent
        ],
    }
