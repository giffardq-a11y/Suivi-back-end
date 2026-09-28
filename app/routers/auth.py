import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..modules import MODULES, est_actif
from ..services import jetons, limite
from ..services.compte import consommer_jeton, creer_jeton
from ..services.email import envoyer_email
from ..security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")


@router.post("/signup", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: schemas.SignupRequest, request: Request, db: Session = Depends(get_db)):
    limite.verifier(f"inscription:{limite.ip_client(request)}", *limite.INSCRIPTION_PAR_IP)
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email")

    # Modules cochés à l'onboarding, filtrés aux clés connues (une clé
    # obsolète ou mal orthographiée envoyée par une vieille version de l'app
    # est ignorée plutôt que de faire échouer l'inscription). Absent = None
    # = tout actif (voir modules.modules_actifs), comportement inchangé pour
    # les clients qui n'envoient pas encore ce champ.
    enabled_modules = None
    if payload.modules is not None:
        enabled_modules = [m for m in payload.modules if m in MODULES]

    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.email.split("@")[0],
        enabled_modules=enabled_modules,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Les 2 substances "de base" (alcool/tabac) sont un pilier de l'app
    # (streaks Accueil, économies, bénéfices santé) — sans elles un nouveau
    # compte réel se retrouverait avec un dashboard vide. Coût par défaut
    # neutre, éditable ensuite dans Paramètres (voir routers/settings.py).
    # Créées seulement si le module addictions est actif (toujours vrai tant
    # qu'un client n'envoie pas encore `modules`).
    if est_actif(user, "addictions"):
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

    return schemas.AuthResponse(user=schemas.UserOut.model_validate(user), **jetons.emettre(db, user.id))


@router.post("/login", response_model=schemas.AuthResponse)
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Par IP (un attaquant qui essaie beaucoup de comptes) et par compte visé
    # (beaucoup d'IP sur un même compte). Contrepartie assumée : quelqu'un
    # peut bloquer 15 min la connexion d'un compte dont il connaît l'adresse.
    limite.verifier(f"connexion-ip:{limite.ip_client(request)}", *limite.CONNEXION_PAR_IP)
    limite.verifier(f"connexion-compte:{payload.email.lower()}", *limite.CONNEXION_PAR_COMPTE)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    return schemas.AuthResponse(user=schemas.UserOut.model_validate(user), **jetons.emettre(db, user.id))


@router.post("/refresh", response_model=schemas.TokenPair)
def refresh(payload: schemas.RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Rotation : le jeton présenté est révoqué et remplacé (services/jetons.py)."""
    limite.verifier(f"rafraichissement:{limite.ip_client(request)}", *limite.RAFRAICHISSEMENT_PAR_IP)
    try:
        _, paire = jetons.rotation(db, payload.refresh_token)
    except jetons.JetonRefuse as erreur:
        raise HTTPException(status_code=401, detail=str(erreur))
    return schemas.TokenPair(**paire)


@router.post("/logout", status_code=204)
def logout(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    """Révoque le jeton de rafraîchissement de cet appareil. Pas d'auth
    exigée : détenir le jeton suffit à prouver qu'on peut le révoquer, et la
    déconnexion doit marcher même avec un jeton d'accès expiré."""
    jetons.revoquer(db, payload.refresh_token)


# ---------- Mot de passe oublié ----------
# Le lien envoyé ouvre une page web du backend (routers/compte_web.py) qui
# appelle /auth/reset-password : pas besoin de lien profond vers l'app.

@router.post("/forgot-password", status_code=202)
def forgot_password(payload: schemas.ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Répond toujours 202, que le compte existe ou non : la réponse ne doit
    pas permettre de savoir quelles adresses ont un compte."""
    limite.verifier(f"oubli:{limite.ip_client(request)}", *limite.OUBLI_PAR_IP)
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if user is not None:
        jeton = creer_jeton(db, user, "reset_password")
        if jeton is not None:
            lien = f"{BACKEND_BASE_URL}/compte/mot-de-passe?token={jeton}"
            # Un échec d'envoi est journalisé, pas renvoyé : la réponse doit
            # rester la même que le compte existe ou non.
            try:
                envoyer_email(
                    user.email,
                    "Tanren : réinitialisation du mot de passe",
                    "Bonjour,\n\nPour choisir un nouveau mot de passe, ouvre ce lien (valable 30 minutes, "
                    f"une seule fois) :\n{lien}\n\nSi tu n'as rien demandé, ignore ce message : "
                    "ton mot de passe actuel reste valable.\n",
                )
            except Exception:
                logging.getLogger("suivi.auth").exception("Échec d'envoi du lien de réinitialisation")
    return {"ok": True}


@router.post("/reset-password")
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    user = consommer_jeton(db, payload.token, "reset_password")
    if user is None:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré : refais une demande depuis l'app.")
    user.password_hash = hash_password(payload.password)
    db.commit()
    # Nouveau mot de passe : toutes les sessions ouvertes sont fermées.
    jetons.revoquer_tout(db, user.id)
    return {"ok": True}
