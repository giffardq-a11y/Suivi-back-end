from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, to_ms, relative_time, is_same_day
from ..services.sport import calories_burned_on
from .profile import _get_or_create_profile

router = APIRouter(prefix="/diet", tags=["diet"])

MEAL_TYPE_LABEL = {
    "petit-dejeuner": "Petit-déjeuner",
    "dejeuner": "Déjeuner",
    "diner": "Dîner",
    "collation": "Collation",
}


class MealCreate(BaseModel):
    label: str
    calories: int
    type: str


def _meals_calories_on(db: Session, user_id: str, date_dt) -> int:
    meals = db.query(models.Meal).filter(models.Meal.user_id == user_id).all()
    return sum(m.calories for m in meals if is_same_day(m.occurred_at, date_dt))


def _serialize_meal(m: models.Meal) -> dict:
    return {
        "id": m.id, "label": m.label, "calories": m.calories, "type": m.type,
        "occurredAt": to_ms(m.occurred_at),
        "type_label": MEAL_TYPE_LABEL.get(m.type, m.type),
        "relativeTime": relative_time(m.occurred_at),
    }


@router.get("")
def get_diet(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    now = now_utc()

    all_meals = (
        db.query(models.Meal)
        .filter(models.Meal.user_id == user.id)
        .order_by(models.Meal.occurred_at.desc())
        .all()
    )
    meals_today = [m for m in all_meals if is_same_day(m.occurred_at, now)]
    consumed_today = sum(m.calories for m in meals_today)
    burned_today = calories_burned_on(db, user.id, now)
    net_today = consumed_today - burned_today

    return {
        "budget": profile.daily_calorie_budget,
        "consumed_today": consumed_today,
        "burned_today": burned_today,
        "net_today": net_today,
        "remaining_today": profile.daily_calorie_budget - net_today,
        "meals_today": [_serialize_meal(m) for m in meals_today],
        "recent_meals": [_serialize_meal(m) for m in all_meals[:15]],
    }


@router.post("/meals", status_code=201)
def add_meal(
    payload: MealCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.add(models.Meal(
        user_id=user.id, label=payload.label, calories=payload.calories, type=payload.type,
        occurred_at=now_utc(),
    ))
    db.commit()
    return {"ok": True}
