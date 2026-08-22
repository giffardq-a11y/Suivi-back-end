from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/substances", tags=["substances"])


class SubstanceCreate(BaseModel):
    label: str
    unit: str | None = None
    unit_cost: float = 0
    note: str | None = None


@router.post("", status_code=201)
def create_substance(
    payload: SubstanceCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sub = models.Substance(
        user_id=user.id,
        label=payload.label,
        category=models.SubstanceCategory.OTHER,
        unit_cost=payload.unit_cost,
        unit=payload.unit,
        note=payload.note,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return {"ok": True, "id": sub.id}
