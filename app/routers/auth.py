from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: schemas.SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email")

    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.email.split("@")[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Les 2 substances "de base" (alcool/tabac) sont un pilier de l'app
    # (streaks Accueil, économies, bénéfices santé) — sans elles un nouveau
    # compte réel se retrouverait avec un dashboard vide. Coût par défaut
    # neutre, éditable ensuite dans Paramètres (voir routers/settings.py).
    db.add_all([
        models.Substance(
            user_id=user.id, label="Alcool", unit="1 verre",
            category=models.SubstanceCategory.ALCOHOL, unit_cost=6.0, usual_frequency_per_day=1.0,
        ),
        models.Substance(
            user_id=user.id, label="Tabac", unit="1 cigarette",
            category=models.SubstanceCategory.TOBACCO, unit_cost=0.6, usual_frequency_per_day=1.0,
        ),
    ])
    db.commit()

    return schemas.AuthResponse(
        user=schemas.UserOut.model_validate(user),
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/login", response_model=schemas.AuthResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    return schemas.AuthResponse(
        user=schemas.UserOut.model_validate(user),
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=schemas.TokenPair)
def refresh(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    try:
        user_id = decode_token(payload.refresh_token, expected_type="refresh")
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token invalide ou expiré")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    return schemas.TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
