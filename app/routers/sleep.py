"""Module Sommeil : saisie manuelle des nuits, qualité, réglages, statistiques.

La table sleep_logs est partagée avec l'import de la montre
(routers/health_sync.py). Les deux cohabitent sans se gêner : l'import ne
cherche que ses lignes (source 'health_connect' + external_id), les nuits
saisies ici portent source 'manual'. Conséquences voulues :
  - les horaires d'une nuit importée ne se modifient pas ici (la prochaine
    synchronisation les réécrirait) ; sa qualité et sa note, si ;
  - supprimer une nuit importée la fait revenir à la synchronisation
    suivante si la montre l'a toujours. C'est l'app qui doit le dire.
"""
import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.common import aware, date_key, from_ms, fuseau_utilisateur, now_utc, to_ms
from .health_sync import _mark_sleep_habits

router = APIRouter(prefix="/sleep", tags=["sleep"])

MANUEL = "manual"
SEUIL_NUIT_COMPLETE_MIN = 7 * 60      # « nuit de 7 h ou plus » du cahier
DUREE_MAX_MIN = 20 * 60               # au-delà, c'est une erreur de saisie
# Observations : pas de conclusion sous 3 nuits dans chaque groupe (avec /
# sans). Même à 3 c'est une tendance, pas une preuve : l'app la présente
# comme une observation, jamais comme un conseil.
MIN_NUITS_PAR_GROUPE = 3
FENETRE_ALCOOL = timedelta(hours=12)  # consommation dans les 12 h avant le coucher
FENETRE_SPORT = timedelta(hours=16)   # séance dans la journée qui précède le coucher


def _heure_valide(v: str | None) -> str | None:
    if v is not None:
        h, _, m = v.partition(":")
        if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
            raise ValueError("heure attendue au format HH:MM")
    return v


class SleepIn(BaseModel):
    startMs: int
    endMs: int
    quality: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class SleepUpdate(BaseModel):
    startMs: int | None = None
    endMs: int | None = None
    quality: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class SleepSettingsIn(BaseModel):
    targetHours: float | None = Field(default=None, ge=3, le=14)
    bedtimeTarget: str | None = None
    wakeTarget: str | None = None
    routineReminderEnabled: bool | None = None
    routineReminderTime: str | None = None

    @field_validator("bedtimeTarget", "wakeTarget", "routineReminderTime")
    @classmethod
    def _heures(cls, v):
        return _heure_valide(v)


def _reglages(db: Session, user: models.User) -> models.SleepSettings:
    ligne = db.query(models.SleepSettings).filter(models.SleepSettings.user_id == user.id).first()
    if ligne is None:
        try:
            ligne = models.SleepSettings(user_id=user.id)
            db.add(ligne)
            db.commit()
            db.refresh(ligne)
        except IntegrityError:
            db.rollback()
            ligne = db.query(models.SleepSettings).filter(models.SleepSettings.user_id == user.id).one()
    return ligne


def _serialiser_reglages(r: models.SleepSettings) -> dict:
    return {
        "targetHours": r.target_hours,
        "bedtimeTarget": r.bedtime_target,
        "wakeTarget": r.wake_target,
        "routineReminderEnabled": bool(r.routine_reminder_enabled),
        "routineReminderTime": r.routine_reminder_time,
    }


def _serialiser_nuit(n: models.SleepLog) -> dict:
    return {
        "id": n.id,
        "dateKey": n.date_key,
        "startedAt": to_ms(n.started_at),
        "endedAt": to_ms(n.ended_at),
        "durationMin": round(n.duration_min),
        "quality": n.quality,
        "note": n.note,
        "source": n.source or MANUEL,
    }


def _nuits(db: Session, user: models.User, depuis: datetime | None = None) -> list[models.SleepLog]:
    nuits = db.query(models.SleepLog).filter(models.SleepLog.user_id == user.id).all()
    if depuis is not None:
        nuits = [n for n in nuits if aware(n.ended_at) >= depuis]
    return sorted(nuits, key=lambda n: aware(n.ended_at), reverse=True)


def _nuit_de(db: Session, user: models.User, nuit_id: str) -> models.SleepLog:
    nuit = db.query(models.SleepLog).filter(models.SleepLog.id == nuit_id, models.SleepLog.user_id == user.id).first()
    if nuit is None:
        raise HTTPException(status_code=404, detail="Nuit introuvable")
    return nuit


def _horaires(debut: datetime, fin: datetime) -> float:
    duree = (fin - debut).total_seconds() / 60
    if duree <= 0:
        raise HTTPException(status_code=400, detail="Le réveil doit suivre le coucher.")
    if duree > DUREE_MAX_MIN:
        raise HTTPException(status_code=400, detail="Nuit de plus de 20 h : vérifie les heures saisies.")
    return duree


def _signaler_si_complete(db: Session, user: models.User, nuit: models.SleepLog) -> dict | None:
    if nuit.duration_min >= SEUIL_NUIT_COMPLETE_MIN:
        return personnage_hooks.evenement(db, user, "sleep_7h", nuit.id,
                                          {"dateKey": nuit.date_key, "durationMin": round(nuit.duration_min)})
    return None


@router.get("")
def get_sleep(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reglages = _reglages(db, user)
    nuits = _nuits(db, user, depuis=now_utc() - timedelta(days=days))
    derniere = nuits[0] if nuits else None
    return {
        "nights": [_serialiser_nuit(n) for n in nuits],
        "lastNight": {
            **_serialiser_nuit(derniere),
            "deltaToTargetMin": round(derniere.duration_min - reglages.target_hours * 60),
        } if derniere else None,
        "settings": _serialiser_reglages(reglages),
    }


@router.post("", status_code=201)
def add_sleep(
    payload: SleepIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    debut, fin = from_ms(payload.startMs), from_ms(payload.endMs)
    duree = _horaires(debut, fin)
    nuit = models.SleepLog(
        user_id=user.id, source=MANUEL, started_at=debut, ended_at=fin, duration_min=duree,
        date_key=date_key(fin), quality=payload.quality, note=payload.note,
    )
    db.add(nuit)
    db.flush()
    # Même effet qu'une nuit importée : les habitudes « sommeil » du jour du
    # réveil sont cochées.
    _mark_sleep_habits(db, user, nuit)
    db.commit()
    db.refresh(nuit)
    resultat = _signaler_si_complete(db, user, nuit)
    return {**_serialiser_nuit(nuit), "personnage": personnage_hooks.resumer([resultat])}


@router.put("/settings")
def update_sleep_settings(
    payload: SleepSettingsIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    r = _reglages(db, user)
    correspondance = {
        "targetHours": "target_hours", "bedtimeTarget": "bedtime_target", "wakeTarget": "wake_target",
        "routineReminderEnabled": "routine_reminder_enabled", "routineReminderTime": "routine_reminder_time",
    }
    for cle, valeur in payload.model_dump(exclude_unset=True).items():
        # Les heures peuvent être effacées (null) ; l'objectif et le booléen non.
        if valeur is None and cle in ("targetHours", "routineReminderEnabled"):
            continue
        setattr(r, correspondance[cle], valeur)
    db.commit()
    db.refresh(r)
    return _serialiser_reglages(r)


@router.put("/{nuit_id}")
def update_sleep(
    nuit_id: str,
    payload: SleepUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    nuit = _nuit_de(db, user, nuit_id)
    champs = payload.model_dump(exclude_unset=True)
    horaires_modifies = champs.get("startMs") is not None or champs.get("endMs") is not None
    if horaires_modifies:
        if (nuit.source or MANUEL) != MANUEL:
            raise HTTPException(
                status_code=400,
                detail="Les horaires d'une nuit importée de la montre ne se modifient pas (la synchronisation les réécrirait).",
            )
        debut = from_ms(champs["startMs"]) if champs.get("startMs") is not None else aware(nuit.started_at)
        fin = from_ms(champs["endMs"]) if champs.get("endMs") is not None else aware(nuit.ended_at)
        nuit.duration_min = _horaires(debut, fin)
        nuit.started_at, nuit.ended_at, nuit.date_key = debut, fin, date_key(fin)
    if "quality" in champs:
        nuit.quality = champs["quality"]
    if "note" in champs:
        nuit.note = champs["note"]
    db.commit()
    db.refresh(nuit)
    resultat = _signaler_si_complete(db, user, nuit) if horaires_modifies else None
    return {**_serialiser_nuit(nuit), "personnage": personnage_hooks.resumer([resultat])}


@router.delete("/{nuit_id}", status_code=204)
def delete_sleep(
    nuit_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    nuit = _nuit_de(db, user, nuit_id)
    db.delete(nuit)
    db.commit()
    personnage_hooks.retrait(db, user, "sleep_7h", nuit_id)


def _minutes_depuis_midi(dt: datetime, fuseau) -> int:
    """Heure de coucher en minutes comptées depuis midi : 23 h 30 et 0 h 30
    donnent 690 et 750, pas 1410 et 30. Sans ce décalage, la moyenne de deux
    couchers de part et d'autre de minuit tomberait en milieu de journée."""
    local = aware(dt).astimezone(fuseau)
    return (local.hour * 60 + local.minute - 12 * 60) % 1440


def _observation(cle: str, nuits: list[models.SleepLog], marquees: set[str]) -> dict | None:
    avec = [n.duration_min for n in nuits if n.id in marquees]
    sans = [n.duration_min for n in nuits if n.id not in marquees]
    if len(avec) < MIN_NUITS_PAR_GROUPE or len(sans) < MIN_NUITS_PAR_GROUPE:
        return None
    moy_avec, moy_sans = statistics.mean(avec), statistics.mean(sans)
    return {
        "key": cle,
        "nightsWith": len(avec),
        "nightsWithout": len(sans),
        "avgDurationWithMin": round(moy_avec),
        "avgDurationWithoutMin": round(moy_sans),
        "diffMin": round(moy_avec - moy_sans),
    }


def _nuits_precedees_de(nuits: list[models.SleepLog], instants: list[datetime], fenetre: timedelta) -> set[str]:
    marquees = set()
    for n in nuits:
        coucher = aware(n.started_at)
        if any(coucher - fenetre <= t <= coucher for t in instants):
            marquees.add(n.id)
    return marquees


@router.get("/stats")
def sleep_stats(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reglages = _reglages(db, user)
    nuits = _nuits(db, user, depuis=now_utc() - timedelta(days=days))
    cible_min = reglages.target_hours * 60
    fuseau = fuseau_utilisateur(user)

    couchers = [_minutes_depuis_midi(n.started_at, fuseau) for n in nuits]
    qualites = [n.quality for n in nuits if n.quality is not None]
    coucher_moyen = None
    if couchers:
        m = (round(statistics.mean(couchers)) + 12 * 60) % 1440
        coucher_moyen = f"{m // 60:02d}:{m % 60:02d}"

    # Observations : seulement ce que les données de l'app permettent de
    # calculer honnêtement. Alcool (entrées de consommation d'une substance
    # de catégorie alcool) et sport (séances enregistrées, saisies ou
    # importées). Pas d'écran : l'app ne mesure pas le temps d'écran.
    alcool = [
        aware(e.occurred_at)
        for e in db.query(models.ConsumptionEntry)
        .join(models.Substance, models.ConsumptionEntry.substance_id == models.Substance.id)
        .filter(
            models.ConsumptionEntry.user_id == user.id,
            models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
            models.Substance.category == models.SubstanceCategory.ALCOHOL,
        ).all()
    ]
    sport = [
        aware(s.occurred_at)
        for modele in (models.Run, models.OtherSportLog, models.StrengthSession, models.FlexibilitySession)
        for s in db.query(modele).filter(modele.user_id == user.id).all()
    ]
    observations = [
        o for o in (
            _observation("alcohol", nuits, _nuits_precedees_de(nuits, alcool, FENETRE_ALCOOL)),
            _observation("sport", nuits, _nuits_precedees_de(nuits, sport, FENETRE_SPORT)),
        ) if o is not None
    ]

    return {
        "days": days,
        "targetHours": reglages.target_hours,
        "nightsCount": len(nuits),
        "avgDurationMin": round(statistics.mean(n.duration_min for n in nuits)) if nuits else None,
        "avgQuality": round(statistics.mean(qualites), 1) if qualites else None,
        "nightsOnTarget": sum(1 for n in nuits if n.duration_min >= cible_min),
        "avgBedtime": coucher_moyen,
        # Écart-type des heures de coucher, en minutes : plus il est bas, plus
        # les couchers sont réguliers.
        "bedtimeStdMin": round(statistics.pstdev(couchers)) if len(couchers) >= 2 else None,
        "perNight": [
            {"dateKey": n.date_key, "durationMin": round(n.duration_min), "quality": n.quality,
             "bedtimeMin": (_minutes_depuis_midi(n.started_at, fuseau) + 12 * 60) % 1440}
            for n in reversed(nuits)
        ],
        "observations": observations,
    }
