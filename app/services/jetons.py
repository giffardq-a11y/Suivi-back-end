"""Jetons de rafraîchissement révocables, avec rotation.

- Chaque jeton émis a une ligne dans refresh_tokens (son jti).
- /auth/refresh : le jeton présenté doit exister, ne pas être révoqué ni
  expiré ; il est révoqué et remplacé par un nouveau (rotation).
- Un jeton déjà remplacé qui revient = réutilisation, signe probable de vol :
  toutes les sessions de l'utilisateur sont révoquées, il doit se reconnecter.
- /auth/logout révoque le jeton de l'appareil ; un changement de mot de
  passe révoque toutes les sessions.
- Transition : un jeton émis avant ce mécanisme (sans jti) est accepté une
  dernière fois et échangé contre un jeton suivi.
"""
import logging
import uuid
from datetime import timedelta

from jose import JWTError
from sqlalchemy.orm import Session

from .. import models
from ..security import (
    REFRESH_TOKEN_EXPIRE_DAYS, create_access_token, create_refresh_token, decode_refresh_token,
)
from .common import now_utc

log = logging.getLogger("suivi.jetons")


class JetonRefuse(Exception):
    pass


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=now_utc().tzinfo)


def emettre(db: Session, user_id: str) -> dict:
    """Nouvelle paire access + refresh ; le refresh est enregistré."""
    jti = str(uuid.uuid4())
    db.add(models.RefreshToken(
        id=jti, user_id=user_id, created_at=now_utc(),
        expires_at=now_utc() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return {"access_token": create_access_token(user_id), "refresh_token": create_refresh_token(user_id, jti)}


def revoquer_tout(db: Session, user_id: str) -> int:
    lignes = db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user_id, models.RefreshToken.revoked_at.is_(None)).all()
    for ligne in lignes:
        ligne.revoked_at = now_utc()
    db.commit()
    return len(lignes)


def rotation(db: Session, jeton: str) -> tuple[models.User, dict]:
    try:
        user_id, jti = decode_refresh_token(jeton)
    except JWTError:
        raise JetonRefuse("Refresh token invalide ou expiré")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise JetonRefuse("Utilisateur introuvable")

    if jti is None:
        log.info("Jeton de rafraîchissement sans jti échangé (transition)")
        return user, emettre(db, user_id)

    ligne = db.query(models.RefreshToken).filter(models.RefreshToken.id == jti).first()
    if ligne is None or ligne.user_id != user_id:
        raise JetonRefuse("Refresh token inconnu")
    if ligne.revoked_at is not None:
        if ligne.replaced_by is not None:
            # Déjà échangé une fois : quelqu'un d'autre a une copie.
            n = revoquer_tout(db, user_id)
            log.warning("Réutilisation d'un refresh token : %s session(s) révoquée(s)", n)
        raise JetonRefuse("Session expirée, reconnecte-toi")
    if _aware(ligne.expires_at) < now_utc():
        raise JetonRefuse("Refresh token expiré")

    paire = emettre(db, user_id)
    _, nouveau_jti = decode_refresh_token(paire["refresh_token"])
    ligne.revoked_at = now_utc()
    ligne.replaced_by = nouveau_jti
    db.commit()
    return user, paire


def revoquer(db: Session, jeton: str) -> bool:
    """Révoque un jeton (déconnexion). Silencieux s'il est déjà invalide."""
    try:
        user_id, jti = decode_refresh_token(jeton)
    except JWTError:
        return False
    ligne = db.query(models.RefreshToken).filter(
        models.RefreshToken.id == jti, models.RefreshToken.user_id == user_id).first() if jti else None
    if ligne is None or ligne.revoked_at is not None:
        return False
    ligne.revoked_at = now_utc()
    db.commit()
    return True
