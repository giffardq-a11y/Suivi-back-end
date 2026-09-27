"""Suppression de compte et jetons à usage unique.

Suppression : plutôt qu'une liste de tables écrite à la main (qui oublierait
la prochaine table ajoutée), on part des clés étrangères du modèle. Une table
appartient à l'utilisateur si une de ses clés étrangères pointe vers `users`
avec son id, ou vers une ligne d'une table qui lui appartient (historique
d'une habitude, révision d'une carte, rappel d'un lien de partage...). On
supprime des feuilles vers la racine, `users` en dernier. Les lignes
partagées sans propriétaire (user_id NULL : modèles de séance et deck livrés
avec l'app) ne sont pas touchées. tests/test_suppression_compte.py vérifie
qu'aucune table ne reste avec une ligne de l'utilisateur supprimé.
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .. import models
from ..database import Base
from .common import now_utc

DUREE_JETON = {"reset_password": timedelta(minutes=30), "delete_account": timedelta(minutes=30)}
# Au-delà, une nouvelle demande est ignorée (anti-harcèlement par e-mail).
MAX_JETONS_PAR_HEURE = 3


def _condition(table, uid, conditions: dict):
    """Condition « la ligne appartient à uid » pour `table`, ou None."""
    if table.name in conditions:
        return conditions[table.name]
    clauses = []
    for fk in table.foreign_keys:
        cible = fk.column.table
        if cible.name == "users":
            clauses.append(fk.parent == uid)
        elif cible is not table:
            parent = _condition(cible, uid, conditions)
            if parent is not None:
                clauses.append(fk.parent.in_(select(fk.column).where(parent)))
    conditions[table.name] = or_(*clauses) if clauses else None
    return conditions[table.name]


def supprimer_utilisateur(db: Session, user_id: str) -> dict[str, int]:
    """Supprime l'utilisateur et tout ce qui lui appartient. Renvoie le nombre
    de lignes supprimées par table (utile au test et au journal)."""
    conditions: dict = {}
    tables = [t for t in Base.metadata.sorted_tables if t.name != "users"]
    for table in tables:
        _condition(table, user_id, conditions)
    compte = {}
    for table in reversed(tables):
        condition = conditions.get(table.name)
        if condition is None:
            continue
        resultat = db.execute(delete(table).where(condition))
        if resultat.rowcount:
            compte[table.name] = resultat.rowcount
    users = Base.metadata.tables["users"]
    compte["users"] = db.execute(delete(users).where(users.c.id == user_id)).rowcount
    db.commit()
    return compte


def tables_orphelines() -> list[str]:
    """Tables non vides reliées aux utilisateurs mais qu'on ne saurait pas
    rattacher à un utilisateur : doit rester vide (voir le test)."""
    conditions: dict = {}
    return [t.name for t in Base.metadata.sorted_tables
            if t.name != "users" and t.foreign_keys and _condition(t, "x", conditions) is None]


# ---------- Jetons à usage unique ----------

def _hacher(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def creer_jeton(db: Session, user: models.User, purpose: str) -> str | None:
    """Jeton en clair (à envoyer par e-mail), ou None si trop de demandes
    récentes. Seul son hachage est enregistré."""
    une_heure = now_utc() - timedelta(hours=1)
    recents = [
        j for j in db.query(models.AccountToken).filter(
            models.AccountToken.user_id == user.id, models.AccountToken.purpose == purpose).all()
        if (j.created_at if j.created_at.tzinfo else j.created_at.replace(tzinfo=une_heure.tzinfo)) >= une_heure
    ]
    if len(recents) >= MAX_JETONS_PAR_HEURE:
        return None
    jeton = secrets.token_urlsafe(32)
    db.add(models.AccountToken(
        user_id=user.id, purpose=purpose, token_hash=_hacher(jeton),
        expires_at=now_utc() + DUREE_JETON[purpose], created_at=now_utc(),
    ))
    db.commit()
    return jeton


def consommer_jeton(db: Session, jeton: str, purpose: str, marquer: bool = True) -> models.User | None:
    """Utilisateur du jeton s'il est valide (bon usage, pas expiré, pas déjà
    utilisé) ; le marque utilisé si `marquer`. None sinon."""
    if not jeton:
        return None
    ligne = db.query(models.AccountToken).filter(
        models.AccountToken.token_hash == _hacher(jeton), models.AccountToken.purpose == purpose).first()
    if ligne is None or ligne.used_at is not None:
        return None
    expire = ligne.expires_at if ligne.expires_at.tzinfo else ligne.expires_at.replace(tzinfo=now_utc().tzinfo)
    if expire < now_utc():
        return None
    if marquer:
        ligne.used_at = now_utc()
        # Un jeton utilisé invalide aussi les autres du même usage.
        for autre in db.query(models.AccountToken).filter(
                models.AccountToken.user_id == ligne.user_id, models.AccountToken.purpose == purpose,
                models.AccountToken.used_at.is_(None)).all():
            autre.used_at = now_utc()
        db.commit()
    return db.query(models.User).filter(models.User.id == ligne.user_id).first()
