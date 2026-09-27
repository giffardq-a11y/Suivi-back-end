"""Module Humeur et journal : humeur en un geste, envies (« J'ai une envie »),
journal de gratitude, statistiques.

Une envie est « résistée » s'il n'y a pas eu de consommation de la même
substance dans les 2 h qui suivent (de n'importe quelle substance si l'envie
n'en précise pas). C'est calculé à chaque lecture à partir des
ConsumptionEntry : pendant les 2 h l'envie est « en cours », et une
consommation saisie après coup (oubli, saisie du lendemain) corrige le
résultat au lieu de laisser un « résisté » figé à tort.

Les jours sont découpés en UTC comme le reste de l'app (date_key) ; seules
les heures des envies sont exprimées dans le fuseau de l'utilisateur.
"""
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.common import aware, date_key, from_ms, fuseau_utilisateur, now_utc, start_of_week, to_ms

router = APIRouter(tags=["mood"])

FENETRE_ENVIE = timedelta(hours=2)
BON_JOUR = 4       # humeur moyenne du jour >= 4
MAUVAIS_JOUR = 2   # humeur moyenne du jour <= 2
TOP_TAGS = 5


def _tags_propres(v: list[str] | None) -> list[str]:
    """Tags en minuscules, sans doublon ni vide, dans l'ordre de saisie."""
    vus = []
    for t in v or []:
        t = t.strip().lower()
        if t and t not in vus:
            vus.append(t)
    if len(vus) > 20:
        raise ValueError("20 tags au plus")
    return vus


class MoodIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = []
    note: str | None = None
    occurredAtMs: int | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        return _tags_propres(v)


class CravingIn(BaseModel):
    intensity: int = Field(ge=1, le=5)
    substanceId: str | None = None
    trigger: list[str] = []
    note: str | None = None
    occurredAtMs: int | None = None

    @field_validator("trigger")
    @classmethod
    def _declencheurs(cls, v):
        return _tags_propres(v)


class GratitudeIn(BaseModel):
    items: list[str]
    dateKey: str | None = None  # 'YYYY-MM-DD', défaut : aujourd'hui

    @field_validator("items")
    @classmethod
    def _lignes(cls, v):
        lignes = [x.strip() for x in v if x and x.strip()]
        if not 1 <= len(lignes) <= 3:
            raise ValueError("1 à 3 lignes")
        return lignes

    @field_validator("dateKey")
    @classmethod
    def _date(cls, v):
        if v is not None:
            datetime.strptime(v, "%Y-%m-%d")
        return v


# ---------- Humeur ----------

def _serialiser_humeur(e: models.MoodEntry) -> dict:
    return {"id": e.id, "occurredAt": to_ms(e.occurred_at), "mood": e.mood, "energy": e.energy,
            "tags": e.tags or [], "note": e.note}


def _humeurs(db: Session, user: models.User, depuis: datetime | None = None) -> list[models.MoodEntry]:
    lignes = db.query(models.MoodEntry).filter(models.MoodEntry.user_id == user.id).all()
    if depuis is not None:
        lignes = [e for e in lignes if aware(e.occurred_at) >= depuis]
    return sorted(lignes, key=lambda e: aware(e.occurred_at), reverse=True)


@router.get("/mood")
def list_mood(
    days: int | None = Query(None, ge=1, le=3660, description="Limiter aux N derniers jours"),
    tag: str | None = None,
    q: str | None = Query(None, description="Recherche dans les notes et les tags"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    lignes = _humeurs(db, user, depuis=now_utc() - timedelta(days=days) if days else None)
    if tag:
        lignes = [e for e in lignes if tag.strip().lower() in (e.tags or [])]
    if q:
        cherche = q.strip().lower()
        lignes = [e for e in lignes if cherche in (e.note or "").lower() or any(cherche in t for t in e.tags or [])]
    return [_serialiser_humeur(e) for e in lignes]


@router.post("/mood", status_code=201)
def add_mood(
    payload: MoodIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    e = models.MoodEntry(
        user_id=user.id, mood=payload.mood, energy=payload.energy, tags=payload.tags, note=payload.note,
        occurred_at=from_ms(payload.occurredAtMs) if payload.occurredAtMs is not None else now_utc(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    personnage_hooks.evenement(db, user, "mood_entry", e.id, {"kind": "mood", "dateKey": date_key(aware(e.occurred_at))})
    return _serialiser_humeur(e)


@router.delete("/mood/{entry_id}", status_code=204)
def delete_mood(
    entry_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    e = db.query(models.MoodEntry).filter(models.MoodEntry.id == entry_id, models.MoodEntry.user_id == user.id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="Humeur introuvable")
    db.delete(e)
    db.commit()


# ---------- Envies ----------

def _consommations(db: Session, user: models.User) -> list[models.ConsumptionEntry]:
    return (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id,
                models.ConsumptionEntry.type == models.EntryType.CONSUMPTION)
        .all()
    )


def _statut_envie(envie: models.CravingEntry, consommations: list, maintenant: datetime) -> str:
    """'consumed' | 'resisted' | 'pending' (fenêtre de 2 h pas encore écoulée)."""
    debut = aware(envie.occurred_at)
    fin = debut + FENETRE_ENVIE
    for c in consommations:
        if envie.substance_id and c.substance_id != envie.substance_id:
            continue
        if debut <= aware(c.occurred_at) <= fin:
            return "consumed"
    return "resisted" if maintenant >= fin else "pending"


def _serialiser_envie(e: models.CravingEntry, statut: str, libelles: dict) -> dict:
    return {
        "id": e.id, "occurredAt": to_ms(e.occurred_at), "intensity": e.intensity,
        "substanceId": e.substance_id, "substanceLabel": libelles.get(e.substance_id),
        "trigger": e.triggers or [], "note": e.note,
        "status": statut,
        # None tant que les 2 h ne sont pas écoulées : on ne sait pas encore.
        "resisted": {"resisted": True, "consumed": False}.get(statut),
    }


def _envies_avec_statut(db: Session, user: models.User, depuis: datetime | None = None):
    maintenant = now_utc()
    consommations = _consommations(db, user)
    envies = db.query(models.CravingEntry).filter(models.CravingEntry.user_id == user.id).all()
    if depuis is not None:
        envies = [e for e in envies if aware(e.occurred_at) >= depuis]
    envies.sort(key=lambda e: aware(e.occurred_at), reverse=True)
    return [(e, _statut_envie(e, consommations, maintenant)) for e in envies]


def _signaler_resistees(db: Session, user: models.User, envies) -> None:
    """Une envie résistée ne se constate qu'après coup : on la signale à
    chaque lecture où elle apparaît résistée. Le module Personnage
    dédoublonne par (source, source_id), voir services/personnage_hooks.py.
    Limite connue : une consommation saisie très en retard (après une
    lecture) peut faire repasser une envie déjà signalée en « cédée » ; le
    Personnage ne reprend pas les points. Faible enjeu (spi +3), à revoir si
    le Personnage prévoit des retraits."""
    for e, statut in envies:
        if statut == "resisted":
            personnage_hooks.evenement(db, user, "craving_resisted", e.id,
                                       {"dateKey": date_key(aware(e.occurred_at)), "intensity": e.intensity})


def _libelles_substances(db: Session, user: models.User) -> dict:
    return {s.id: s.label for s in db.query(models.Substance).filter(models.Substance.user_id == user.id).all()}


@router.get("/cravings")
def list_cravings(
    days: int | None = Query(None, ge=1, le=3660),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    envies = _envies_avec_statut(db, user, depuis=now_utc() - timedelta(days=days) if days else None)
    _signaler_resistees(db, user, envies)
    libelles = _libelles_substances(db, user)
    return [_serialiser_envie(e, statut, libelles) for e, statut in envies]


@router.post("/cravings", status_code=201)
def add_craving(
    payload: CravingIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    libelles = _libelles_substances(db, user)
    if payload.substanceId and payload.substanceId not in libelles:
        raise HTTPException(status_code=404, detail="Substance introuvable")
    e = models.CravingEntry(
        user_id=user.id, intensity=payload.intensity, substance_id=payload.substanceId,
        triggers=payload.trigger, note=payload.note,
        occurred_at=from_ms(payload.occurredAtMs) if payload.occurredAtMs is not None else now_utc(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    statut = _statut_envie(e, _consommations(db, user), now_utc())
    # Pas de signalement ici, même pour une envie saisie après coup (déjà
    # « résistée ») : la consommation correspondante est souvent saisie dans
    # la foulée, juste après. Le signalement se fait à la lecture (GET).
    return _serialiser_envie(e, statut, libelles)


# ---------- Gratitude ----------

def _serialiser_gratitude(g: models.GratitudeEntry) -> dict:
    return {"id": g.id, "dateKey": g.date_key, "items": g.items or []}


@router.get("/gratitude")
def list_gratitude(
    days: int | None = Query(None, ge=1, le=3660),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    lignes = db.query(models.GratitudeEntry).filter(models.GratitudeEntry.user_id == user.id).all()
    if days:
        limite = date_key(now_utc() - timedelta(days=days))
        lignes = [g for g in lignes if g.date_key >= limite]
    return [_serialiser_gratitude(g) for g in sorted(lignes, key=lambda g: g.date_key, reverse=True)]


@router.post("/gratitude", status_code=201)
def save_gratitude(
    payload: GratitudeIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    jour = payload.dateKey or date_key(now_utc())
    g = (
        db.query(models.GratitudeEntry)
        .filter(models.GratitudeEntry.user_id == user.id, models.GratitudeEntry.date_key == jour)
        .first()
    )
    if g is None:
        g = models.GratitudeEntry(user_id=user.id, date_key=jour, items=payload.items)
        db.add(g)
    else:
        g.items = payload.items
    db.commit()
    db.refresh(g)
    # Le journal compte comme l'humeur pour le Personnage (« humeur ou
    # journal » : spi +1, 1 par jour, plafond géré côté Personnage).
    personnage_hooks.evenement(db, user, "mood_entry", g.id, {"kind": "gratitude", "dateKey": jour})
    return _serialiser_gratitude(g)


# ---------- Statistiques ----------

def _moyenne(valeurs) -> float | None:
    valeurs = list(valeurs)
    return round(sum(valeurs) / len(valeurs), 2) if valeurs else None


@router.get("/mood/stats")
def mood_stats(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    depuis = now_utc() - timedelta(days=days)
    humeurs = _humeurs(db, user, depuis=depuis)

    # Moyenne par semaine (lundi = début, comme le reste de l'app).
    par_semaine: dict[str, list[int]] = {}
    for e in humeurs:
        par_semaine.setdefault(date_key(start_of_week(aware(e.occurred_at))), []).append(e.mood)
    semaines = [{"weekStart": k, "avgMood": _moyenne(v), "entries": len(v)} for k, v in sorted(par_semaine.items())]

    # Bons et mauvais jours : moyenne des humeurs du jour, puis tags de ces jours-là.
    par_jour: dict[str, list[models.MoodEntry]] = {}
    for e in humeurs:
        par_jour.setdefault(date_key(aware(e.occurred_at)), []).append(e)
    moyenne_jour = {j: sum(e.mood for e in es) / len(es) for j, es in par_jour.items()}
    tags_bons, tags_mauvais = Counter(), Counter()
    for j, es in par_jour.items():
        cible = tags_bons if moyenne_jour[j] >= BON_JOUR else tags_mauvais if moyenne_jour[j] <= MAUVAIS_JOUR else None
        if cible is not None:
            for e in es:
                cible.update(e.tags or [])

    # Envies : heure locale, et bilan résistées / cédées / en cours.
    fuseau = fuseau_utilisateur(user)
    envies = _envies_avec_statut(db, user, depuis=depuis)
    par_heure = [0] * 24
    for e, _ in envies:
        par_heure[aware(e.occurred_at).astimezone(fuseau).hour] += 1
    statuts = Counter(statut for _, statut in envies)

    # Humeur et consommation : moyenne des jours notés, selon qu'il y a eu
    # une consommation ce jour-là ou non. Un jour sans humeur notée ne compte
    # dans aucun des deux groupes.
    jours_conso = {date_key(aware(c.occurred_at)) for c in _consommations(db, user) if aware(c.occurred_at) >= depuis}
    avec = [m for j, m in moyenne_jour.items() if j in jours_conso]
    sans = [m for j, m in moyenne_jour.items() if j not in jours_conso]

    return {
        "days": days,
        "entries": len(humeurs),
        "avgMood": _moyenne(e.mood for e in humeurs),
        "avgEnergy": _moyenne(e.energy for e in humeurs if e.energy is not None),
        "weekly": semaines,
        "goodDays": sum(1 for m in moyenne_jour.values() if m >= BON_JOUR),
        "badDays": sum(1 for m in moyenne_jour.values() if m <= MAUVAIS_JOUR),
        "topTagsGoodDays": [{"tag": t, "count": n} for t, n in tags_bons.most_common(TOP_TAGS)],
        "topTagsBadDays": [{"tag": t, "count": n} for t, n in tags_mauvais.most_common(TOP_TAGS)],
        "cravings": {
            "total": len(envies),
            "resisted": statuts.get("resisted", 0),
            "consumed": statuts.get("consumed", 0),
            "pending": statuts.get("pending", 0),
            "byHour": par_heure,
        },
        "moodVsConsumption": {
            "daysWithConsumption": len(avec),
            "daysWithoutConsumption": len(sans),
            "avgMoodWithConsumption": _moyenne(avec),
            "avgMoodWithoutConsumption": _moyenne(sans),
        },
    }
