"""Connexion à des calendriers externes (Google Calendar, Outlook) par
OAuth2 — flux "authorization code" standard.

STATUT : scaffold fonctionnel dans sa structure, mais pas testé en
conditions réelles (pas d'accès réseau ni d'identifiants OAuth dans
l'environnement où ce projet a été généré). Pour l'activer réellement :

1. Google Calendar
   - Va sur https://console.cloud.google.com/ → crée un projet (gratuit)
   - APIs & Services → Bibliothèque → active "Google Calendar API"
   - APIs & Services → Écran de consentement OAuth → configure-le en mode
     "Test" (pas besoin de validation Google pour un usage personnel) et
     ajoute ton propre email comme "utilisateur de test"
   - APIs & Services → Identifiants → Créer des identifiants → ID client
     OAuth → type "Application Web"
   - URI de redirection autorisé : http://localhost:8000/integrations/google_calendar/callback
     (remplace localhost:8000 par l'adresse réelle du backend en prod)
   - Récupère le Client ID et le Client Secret

2. Outlook / Microsoft Calendar
   - Va sur https://portal.azure.com/ → Azure Active Directory →
     Inscriptions d'applications → Nouvelle inscription (gratuit)
   - Type de compte : "Comptes dans n'importe quel annuaire organisationnel
     et comptes Microsoft personnels"
   - URI de redirection : http://localhost:8000/integrations/microsoft_calendar/callback
   - API permissions → Microsoft Graph → Delegated → ajoute Calendars.Read
   - Certificats et secrets → Nouveau secret client

3. Renseigne les variables d'environnement (voir backend/.env.example) :
   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
   MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET,
   BACKEND_BASE_URL (pour construire les URIs de redirection)

Le flux, une fois configuré :
   Mobile → GET /integrations/{provider}/authorize → reçoit une URL
   Mobile → ouvre cette URL dans le navigateur du téléphone
   Utilisateur se connecte chez Google/Microsoft et autorise l'accès
   Google/Microsoft redirige vers /integrations/{provider}/callback (ici)
   Ce endpoint échange le code contre un token et le stocke en base
   L'utilisateur revient sur l'app, qui voit la connexion comme active
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/integrations", tags=["integrations"])

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")

PROVIDER_CONFIG = {
    "google_calendar": {
        "label": "Google Calendar",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/calendar.readonly",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
    },
    "microsoft_calendar": {
        "label": "Outlook Calendar",
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "Calendars.Read offline_access",
        "client_id_env": "MICROSOFT_CLIENT_ID",
        "client_secret_env": "MICROSOFT_CLIENT_SECRET",
        "extra_authorize_params": {},
    },
}


def _redirect_uri(provider: str) -> str:
    return f"{BACKEND_BASE_URL}/integrations/{provider}/callback"


def _require_provider(provider: str) -> dict:
    config = PROVIDER_CONFIG.get(provider)
    if not config:
        raise HTTPException(status_code=404, detail=f"Fournisseur inconnu : {provider}")
    return config


@router.get("")
def list_integrations(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rows = db.query(models.ExternalIntegration).filter(models.ExternalIntegration.user_id == user.id).all()
    return [
        {"provider": r.provider, "label": PROVIDER_CONFIG.get(r.provider, {}).get("label", r.provider), "connected_at": r.connected_at}
        for r in rows
    ]


@router.get("/{provider}/authorize")
def get_authorize_url(
    provider: str,
    user: models.User = Depends(get_current_user),
):
    config = _require_provider(provider)
    client_id = os.environ.get(config["client_id_env"])
    if not client_id:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{config['label']} n'est pas configuré côté serveur : variable d'environnement "
                f"{config['client_id_env']} manquante. Voir les instructions en haut de "
                f"app/routers/integrations.py."
            ),
        )

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": config["scope"],
        # On fait transiter l'id utilisateur dans `state` pour savoir à qui
        # associer le token une fois revenu sur /callback (pas de session
        # de navigateur partagée entre mobile et backend).
        "state": user.id,
        **config["extra_authorize_params"],
    }
    query = urlencode(params)
    return {"authorize_url": f"{config['authorize_url']}?{query}"}


@router.get("/{provider}/callback", response_class=HTMLResponse)
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),  # user_id transmis dans authorize()
    db: Session = Depends(get_db),
):
    config = _require_provider(provider)
    client_id = os.environ.get(config["client_id_env"])
    client_secret = os.environ.get(config["client_secret_env"])
    if not client_id or not client_secret:
        raise HTTPException(status_code=501, detail=f"{config['label']} n'est pas configuré côté serveur.")

    user = db.query(models.User).filter(models.User.id == state).first()
    if not user:
        raise HTTPException(status_code=400, detail="Utilisateur introuvable pour ce callback OAuth.")

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            config["token_url"],
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": _redirect_uri(provider),
                "grant_type": "authorization_code",
            },
        )
    if token_response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Échec de l'échange du code OAuth : {token_response.text}")

    payload = token_response.json()
    expires_at = None
    if payload.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload["expires_in"])

    existing = (
        db.query(models.ExternalIntegration)
        .filter(models.ExternalIntegration.user_id == user.id, models.ExternalIntegration.provider == provider)
        .first()
    )
    if existing:
        existing.access_token = payload["access_token"]
        existing.refresh_token = payload.get("refresh_token", existing.refresh_token)
        existing.expires_at = expires_at
    else:
        db.add(models.ExternalIntegration(
            user_id=user.id, provider=provider,
            access_token=payload["access_token"], refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
        ))
    db.commit()

    return f"""
    <html><body style="font-family: sans-serif; text-align: center; padding: 40px;">
      <h2>{config['label']} connecté ✓</h2>
      <p>Tu peux fermer cette fenêtre et retourner sur l'app.</p>
    </body></html>
    """


@router.delete("/{provider}")
def disconnect_integration(
    provider: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    row = (
        db.query(models.ExternalIntegration)
        .filter(models.ExternalIntegration.user_id == user.id, models.ExternalIntegration.provider == provider)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}
