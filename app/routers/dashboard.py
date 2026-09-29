from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.dashboard_helpers import build_dashboard_dict

router = APIRouter(tags=["dashboard"])


@router.get("/me/dashboard", response_model=schemas.DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Journées sans tabac / alcool, paliers de santé, habitudes cochées
    # automatiquement : constatés ici, l'Accueil étant ouvert chaque jour.
    resultats = personnage_hooks.constater(db, user)
    return {**build_dashboard_dict(db, user), "personnage": personnage_hooks.resumer(resultats)}
