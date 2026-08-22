from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, to_ms

router = APIRouter(tags=["profile"])

ACTIVITY_FACTORS = {
    "sedentaire": 1.2,
    "legerement_actif": 1.375,
    "actif": 1.55,
    "tres_actif": 1.725,
}
# 1 kg de graisse ≈ 7700 kcal — approximation standard (même valeur que
# mockData.js/computeSuggestedCalorieBudget) pour convertir un rythme de
# perte/prise de poids visé en delta calorique quotidien.
KCAL_PER_KG = 7700


class ProfileUpdate(BaseModel):
    age: int | None = None
    heightCm: float | None = None
    sex: str | None = None
    activityLevel: str | None = None
    goalType: str | None = None
    goalRateKgPerMonth: float | None = None


class WeightEntryCreate(BaseModel):
    weightKg: float
    note: str | None = None


class WeightGoalUpdate(BaseModel):
    value: float


class BodyFatEntryCreate(BaseModel):
    percent: float
    note: str | None = None


class CalorieBudgetUpdate(BaseModel):
    value: int


class MealPhotoProviderUpdate(BaseModel):
    provider: str


def _get_or_create_profile(db: Session, user: models.User) -> models.Profile:
    profile = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    if not profile:
        profile = models.Profile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _current_weight_kg(db: Session, user: models.User) -> float | None:
    last = (
        db.query(models.WeightEntry)
        .filter(models.WeightEntry.user_id == user.id)
        .order_by(models.WeightEntry.occurred_at.desc())
        .first()
    )
    return last.weight_kg if last else None


def _suggested_calorie_budget(profile: models.Profile, current_weight_kg: float | None) -> int | None:
    if not (profile.age and profile.height_cm and profile.sex and profile.activity_level and current_weight_kg):
        return None

    # Mifflin-St Jeor : métabolisme de base (BMR), avant dépenses du jour.
    bmr = 10 * current_weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    bmr += 5 if profile.sex == "homme" else (-161 if profile.sex == "femme" else -78)

    factor = ACTIVITY_FACTORS.get(profile.activity_level, 1.2)
    tdee = bmr * factor

    if not profile.goal_type or profile.goal_type == "maintien":
        return round(tdee)

    kg_per_month = abs(profile.goal_rate_kg_per_month or 0)
    daily_delta = (kg_per_month * KCAL_PER_KG) / 30
    sign = -1 if profile.goal_type == "perte" else 1
    return round(tdee + sign * daily_delta)


def _serialize_profile(db: Session, user: models.User, profile: models.Profile) -> dict:
    current_weight = _current_weight_kg(db, user)
    return {
        "age": profile.age,
        "heightCm": profile.height_cm,
        "sex": profile.sex,
        "activityLevel": profile.activity_level,
        "goalType": profile.goal_type,
        "goalRateKgPerMonth": profile.goal_rate_kg_per_month,
        "suggested_calorie_budget": _suggested_calorie_budget(profile, current_weight),
        "current_weight_kg": current_weight,
    }


@router.get("/profile")
def get_profile(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    return _serialize_profile(db, user, profile)


@router.put("/profile")
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)
    patch = payload.model_dump(exclude_unset=True)
    if "age" in patch:
        profile.age = patch["age"]
    if "heightCm" in patch:
        profile.height_cm = patch["heightCm"]
    if "sex" in patch:
        profile.sex = patch["sex"]
    if "activityLevel" in patch:
        profile.activity_level = patch["activityLevel"]
    if "goalType" in patch:
        profile.goal_type = patch["goalType"]
    if "goalRateKgPerMonth" in patch:
        profile.goal_rate_kg_per_month = patch["goalRateKgPerMonth"]
    db.commit()
    db.refresh(profile)
    return _serialize_profile(db, user, profile)


def _serialize_weight(db: Session, user: models.User, profile: models.Profile) -> dict:
    entries = (
        db.query(models.WeightEntry)
        .filter(models.WeightEntry.user_id == user.id)
        .order_by(models.WeightEntry.occurred_at.asc())
        .all()
    )
    with_deltas = []
    for i, w in enumerate(entries):
        delta = round((w.weight_kg - entries[i - 1].weight_kg) * 10) / 10 if i > 0 else 0
        with_deltas.append({
            "id": w.id, "weightKg": w.weight_kg, "occurredAt": to_ms(w.occurred_at),
            "note": w.note, "delta": delta,
        })
    current = with_deltas[-1] if with_deltas else None
    start = with_deltas[0] if with_deltas else None
    total_delta = round((current["weightKg"] - start["weightKg"]) * 10) / 10 if current and start else 0

    return {
        "entries": list(reversed(with_deltas)),
        "current_kg": current["weightKg"] if current else None,
        "start_kg": start["weightKg"] if start else None,
        "total_delta": total_delta,
        "goal_kg": profile.weight_goal_kg,
    }


@router.get("/weight")
def get_weight_history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    return _serialize_weight(db, user, profile)


@router.post("/weight", status_code=201)
def add_weight_entry(
    payload: WeightEntryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.add(models.WeightEntry(
        user_id=user.id, weight_kg=payload.weightKg, note=payload.note, occurred_at=now_utc(),
    ))
    db.commit()
    return {"ok": True}


@router.put("/weight/goal")
def update_weight_goal(
    payload: WeightGoalUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)
    profile.weight_goal_kg = payload.value
    db.commit()
    return {"ok": True}


@router.get("/body-fat")
def get_body_fat_history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    entries = (
        db.query(models.BodyFatEntry)
        .filter(models.BodyFatEntry.user_id == user.id)
        .order_by(models.BodyFatEntry.occurred_at.asc())
        .all()
    )
    out = [{"id": e.id, "percent": e.percent, "occurredAt": to_ms(e.occurred_at), "note": e.note} for e in entries]
    return {
        "entries": list(reversed(out)),
        "current_percent": out[-1]["percent"] if out else None,
        "start_percent": out[0]["percent"] if out else None,
    }


@router.post("/body-fat", status_code=201)
def log_body_fat_entry(
    payload: BodyFatEntryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.add(models.BodyFatEntry(
        user_id=user.id, percent=payload.percent, note=payload.note, occurred_at=now_utc(),
    ))
    db.commit()
    return {"ok": True}


@router.put("/diet/calorie-budget")
def update_calorie_budget(
    payload: CalorieBudgetUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)
    profile.daily_calorie_budget = payload.value
    db.commit()
    return {"ok": True}


@router.get("/meal-photo-provider")
def get_meal_photo_provider(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    return {"provider": profile.meal_photo_provider}


@router.put("/meal-photo-provider")
def update_meal_photo_provider(
    payload: MealPhotoProviderUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    profile = _get_or_create_profile(db, user)
    profile.meal_photo_provider = payload.provider
    db.commit()
    return {"ok": True}
