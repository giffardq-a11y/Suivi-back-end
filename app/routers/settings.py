from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, days_since
from ..services.dashboard_helpers import build_dashboard_dict
from ..services.habit_progress import effective_habit_target
from .profile import _get_or_create_profile

router = APIRouter(tags=["settings"])

SUGGESTED_HABITS = [
    "Lecture", "Yoga", "Journaling", "Cuisine saine", "Appel à un proche", "Sortie nature",
    "Musique", "Dessin", "Écriture", "Jardinage", "Bricolage", "Bénévolat",
]

TRANSFORMATION_BENEFITS = {
    "today": ["Ton corps commence déjà à récupérer.", "Meilleure qualité de sommeil dès cette nuit."],
    "30": ["Peau plus claire et meilleure hydratation.", "Endurance physique en nette progression.", "Économies déjà visibles sur ton budget."],
    "90": ["Fonction pulmonaire et cardiovasculaire nettement améliorée.", "Nouvelles habitudes bien installées.", "Risques de santé à long terme significativement réduits."],
}


class SubstanceSettingIn(BaseModel):
    key: str
    unit_cost: float


class HabitSettingIn(BaseModel):
    id: str
    target: str


class SettingsSave(BaseModel):
    substances: list[SubstanceSettingIn] | None = None
    habits: list[HabitSettingIn] | None = None
    suggestedSelected: list[str] | None = None


class InvitePartnerBody(BaseModel):
    email: str


class ReportSettingsUpdate(BaseModel):
    autoSend: bool | None = None
    whatsappNumber: str | None = None
    sendTime: str | None = None
    reminderEnabled: bool | None = None
    reminderMinutesBefore: int | None = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    profile = _get_or_create_profile(db, user)
    built_in = [
        {"key": s.category.value, "label": s.label, "unit": s.unit, "unit_cost": s.unit_cost}
        for s in user.substances
        if s.category in (models.SubstanceCategory.ALCOHOL, models.SubstanceCategory.TOBACCO)
    ]
    custom = [
        {"id": s.id, "label": s.label, "unit": s.unit, "unit_cost": s.unit_cost, "note": s.note}
        for s in user.substances
        if s.category == models.SubstanceCategory.OTHER
    ]
    now = now_utc()
    habits_out = [
        {
            "id": h.id, "label": h.label, "target": effective_habit_target(h, now),
            "progressive": bool(h.progressive_rhythm),
            "linked_activity": h.linked_activity,
            "scheduled_time": h.scheduled_time,
            "notifications_enabled": h.notifications_enabled,
        }
        for h in user.habits if h.active
    ]
    selected = profile.suggested_habits_selected or []
    suggested = [{"label": label, "selected": label in selected} for label in SUGGESTED_HABITS]

    return {
        "substances": built_in,
        "customSubstances": custom,
        "habits": habits_out,
        "suggested_habits": suggested,
    }


@router.put("/settings")
def save_settings(
    payload: SettingsSave,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.substances:
        by_key = {s.category.value: s for s in user.substances}
        for entry in payload.substances:
            sub = by_key.get(entry.key)
            if sub:
                sub.unit_cost = entry.unit_cost

    if payload.habits:
        by_id = {h.id: h for h in user.habits}
        for entry in payload.habits:
            habit = by_id.get(entry.id)
            # Une habitude progressive ou auto-gérée (linked_activity)
            # recalcule son target elle-même — un éditeur manuel ne doit pas
            # l'écraser (même garde que saveSettings côté mock).
            if habit and not habit.linked_activity and not habit.progressive_rhythm:
                habit.target = entry.target

    if payload.suggestedSelected is not None:
        profile = _get_or_create_profile(db, user)
        profile.suggested_habits_selected = payload.suggestedSelected

    db.commit()
    return {"ok": True}


@router.get("/avatar-info")
def get_avatar_info():
    return {"benefits": TRANSFORMATION_BENEFITS}


@router.get("/partner")
def get_partner(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    partner = db.query(models.Partner).filter(models.Partner.user_id == user.id).first()
    if not partner:
        return {"partner": None}
    return {
        "partner": {
            "name": partner.invited_email.split("@")[0],
            "connectedSinceDays": days_since(partner.connected_since),
            "scopes": partner.scopes or [],
            # Pas de vrai fil de rappels temps réel entre 2 comptes pour
            # l'instant (voir Partner dans models.py) — liste vide plutôt
            # que les 2 rappels de démo en dur côté mock.
            "reminders": [],
        }
    }


@router.delete("/partner")
def remove_partner(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.Partner).filter(models.Partner.user_id == user.id).delete()
    db.commit()
    return {"ok": True}


@router.post("/partner/invite")
def invite_partner(
    payload: InvitePartnerBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.query(models.Partner).filter(models.Partner.user_id == user.id).delete()
    db.add(models.Partner(
        user_id=user.id, invited_email=payload.email,
        scopes=["Séries", "Habitudes", "Objectifs"],
    ))
    db.commit()
    return {"ok": True}


def _get_or_create_report_settings(db: Session, user: models.User) -> models.ReportSettings:
    settings = db.query(models.ReportSettings).filter(models.ReportSettings.user_id == user.id).first()
    if not settings:
        settings = models.ReportSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/report")
def get_report(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    settings = _get_or_create_report_settings(db, user)
    dashboard = build_dashboard_dict(db, user)
    alcohol = next((s for s in dashboard["streaks"] if s["category"] == "alcohol"), None)
    tobacco = next((s for s in dashboard["streaks"] if s["category"] == "tobacco"), None)

    lines = ["🌟 Récap du jour", ""]
    if alcohol:
        lines.append(f"🍷 {alcohol['days']} j sans alcool (record {alcohol['personal_best_days']} j)")
    if tobacco:
        lines.append(f"🚬 {tobacco['days']} j sans tabac (record {tobacco['personal_best_days']} j)")
    lines.append(f"💰 {dashboard['savings']['total']} € économisés")
    done = sum(1 for h in dashboard["habits_today"] if h["done_today"])
    lines.append(f"✅ {done}/{len(dashboard['habits_today'])} habitudes complétées")
    lines.append(f"🎯 Objectif du moment : {dashboard['goals_summary']['top_goal_label'] or '—'}")
    message = "\n".join(lines)

    return {
        "message": message,
        "settings": {
            "autoSend": settings.auto_send,
            "whatsappNumber": settings.whatsapp_number,
            "sendTime": settings.send_time,
            "reminderEnabled": settings.reminder_enabled,
            "reminderMinutesBefore": settings.reminder_minutes_before,
        },
    }


@router.put("/report/settings")
def update_report_settings(
    payload: ReportSettingsUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    settings = _get_or_create_report_settings(db, user)
    patch = payload.model_dump(exclude_unset=True)
    if "autoSend" in patch:
        settings.auto_send = patch["autoSend"]
    if "whatsappNumber" in patch:
        settings.whatsapp_number = patch["whatsappNumber"]
    if "sendTime" in patch:
        settings.send_time = patch["sendTime"]
    if "reminderEnabled" in patch:
        settings.reminder_enabled = patch["reminderEnabled"]
    if "reminderMinutesBefore" in patch:
        settings.reminder_minutes_before = patch["reminderMinutesBefore"]
    db.commit()
    return {"ok": True}


@router.post("/report/send-test")
def send_test_report(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Envoi WhatsApp réel non implémenté (nécessite l'API Business WhatsApp
    # + un numéro vérifié) — voir zones ouvertes du récap. On confirme
    # juste que la génération du message fonctionne, sans réel envoi.
    return {"ok": True}
