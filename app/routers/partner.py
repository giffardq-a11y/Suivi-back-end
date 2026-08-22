"""Partage avec un proche — vrai lien à double sens entre 2 comptes réels
(remplace la version précédente qui stockait juste un email invité sans
relier de vrais comptes). Flux :

- A invite B par email (POST /partner/invite) -> crée un PartnerLink
  status='pending' si B a un compte, sinon erreur explicite.
- B voit l'invitation en attente dans GET /partner (pendingReceived) et
  l'accepte (POST /partner/invites/{id}/accept) ou la refuse (delete).
- Si B avait déjà invité A entre-temps (invitation mutuelle), la seconde
  invitation accepte directement la première au lieu d'en créer une 2e.
- Une fois accepté, chacun peut envoyer un message d'encouragement à
  l'autre (POST /partner/reminders) — visible dans les rappels reçus de
  l'autre, pas les siens.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, days_since, to_ms, relative_time

router = APIRouter(prefix="/partner", tags=["partner"])

DEFAULT_SCOPES = ["Séries", "Habitudes", "Objectifs"]


class InvitePartnerBody(BaseModel):
    email: str


class SendReminderBody(BaseModel):
    text: str


def _other_user(link: models.PartnerLink, me_id: str) -> str:
    return link.recipient_id if link.requester_id == me_id else link.requester_id


def _my_active_link(db: Session, user_id: str) -> models.PartnerLink | None:
    return (
        db.query(models.PartnerLink)
        .filter(
            or_(models.PartnerLink.requester_id == user_id, models.PartnerLink.recipient_id == user_id),
            models.PartnerLink.status == "accepted",
        )
        .first()
    )


def _serialize_state(db: Session, user: models.User) -> dict:
    active = _my_active_link(db, user.id)
    if active:
        other_id = _other_user(active, user.id)
        other = db.query(models.User).filter(models.User.id == other_id).first()
        reminders = (
            db.query(models.PartnerReminder)
            .filter(models.PartnerReminder.link_id == active.id, models.PartnerReminder.from_user_id == other_id)
            .order_by(models.PartnerReminder.created_at.desc())
            .limit(20)
            .all()
        )
        return {
            "partner": {
                "name": other.display_name or other.email.split("@")[0],
                "connectedSinceDays": days_since(active.accepted_at or active.created_at),
                "scopes": active.scopes or DEFAULT_SCOPES,
                "reminders": [
                    {
                        "id": r.id, "text": r.text,
                        "from": other.display_name or other.email.split("@")[0],
                        "time": relative_time(r.created_at),
                    }
                    for r in reminders
                ],
            },
            "pendingSent": None,
            "pendingReceived": [],
        }

    pending_sent = (
        db.query(models.PartnerLink)
        .filter(models.PartnerLink.requester_id == user.id, models.PartnerLink.status == "pending")
        .first()
    )
    pending_received = (
        db.query(models.PartnerLink)
        .filter(models.PartnerLink.recipient_id == user.id, models.PartnerLink.status == "pending")
        .all()
    )

    pending_sent_out = None
    if pending_sent:
        recipient = db.query(models.User).filter(models.User.id == pending_sent.recipient_id).first()
        pending_sent_out = {"linkId": pending_sent.id, "email": recipient.email if recipient else None}

    pending_received_out = []
    for link in pending_received:
        requester = db.query(models.User).filter(models.User.id == link.requester_id).first()
        pending_received_out.append({
            "linkId": link.id,
            "name": requester.display_name or requester.email.split("@")[0],
            "email": requester.email,
        })

    return {"partner": None, "pendingSent": pending_sent_out, "pendingReceived": pending_received_out}


@router.get("")
def get_partner(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _serialize_state(db, user)


@router.post("/invite")
def invite_partner(
    payload: InvitePartnerBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    email = payload.email.strip().lower()
    if email == user.email.lower():
        raise HTTPException(status_code=400, detail="Tu ne peux pas t’inviter toi-même.")

    target = db.query(models.User).filter(models.User.email == email).first()
    if not target:
        raise HTTPException(status_code=404, detail="Aucun compte Suivi n’est associé à cet email.")

    if _my_active_link(db, user.id):
        raise HTTPException(status_code=400, detail="Tu es déjà connecté·e à un proche — retire le lien actuel avant d’en inviter un autre.")

    # Invitation mutuelle : l'autre m'avait déjà invité, on accepte direct
    # plutôt que de créer une 2e invitation en double.
    reverse_pending = (
        db.query(models.PartnerLink)
        .filter(
            models.PartnerLink.requester_id == target.id,
            models.PartnerLink.recipient_id == user.id,
            models.PartnerLink.status == "pending",
        )
        .first()
    )
    if reverse_pending:
        reverse_pending.status = "accepted"
        reverse_pending.accepted_at = now_utc()
        db.commit()
        return _serialize_state(db, user)

    already_sent = (
        db.query(models.PartnerLink)
        .filter(
            models.PartnerLink.requester_id == user.id,
            models.PartnerLink.recipient_id == target.id,
            models.PartnerLink.status == "pending",
        )
        .first()
    )
    if already_sent:
        return _serialize_state(db, user)

    db.add(models.PartnerLink(
        requester_id=user.id, recipient_id=target.id, status="pending", scopes=DEFAULT_SCOPES,
    ))
    db.commit()
    return _serialize_state(db, user)


@router.post("/invites/{link_id}/accept")
def accept_invite(
    link_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    link = (
        db.query(models.PartnerLink)
        .filter(models.PartnerLink.id == link_id, models.PartnerLink.recipient_id == user.id, models.PartnerLink.status == "pending")
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Invitation introuvable.")
    if _my_active_link(db, user.id):
        raise HTTPException(status_code=400, detail="Tu es déjà connecté·e à un proche.")
    link.status = "accepted"
    link.accepted_at = now_utc()
    db.commit()
    return _serialize_state(db, user)


@router.delete("/invites/{link_id}")
def decline_or_cancel_invite(
    link_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    link = (
        db.query(models.PartnerLink)
        .filter(
            models.PartnerLink.id == link_id,
            or_(models.PartnerLink.requester_id == user.id, models.PartnerLink.recipient_id == user.id),
        )
        .first()
    )
    if link:
        db.delete(link)
        db.commit()
    return {"ok": True}


@router.delete("")
def remove_partner(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    active = _my_active_link(db, user.id)
    if active:
        db.delete(active)
        db.commit()
    return {"ok": True}


@router.post("/reminders")
def send_reminder(
    payload: SendReminderBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    active = _my_active_link(db, user.id)
    if not active:
        raise HTTPException(status_code=400, detail="Pas de proche connecté pour l’instant.")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message vide.")
    db.add(models.PartnerReminder(link_id=active.id, from_user_id=user.id, text=text))
    db.commit()
    return {"ok": True}
