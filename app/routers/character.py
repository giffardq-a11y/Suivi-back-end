"""Module Personnage : création, lecture, apparence, changement de classe,
historique des points (cahier : mobile/docs/tanren-rpg/PROMPT-module-personnage.md
§9, première version sans boutique, équipement, coffres ni quêtes).

Le moteur (XP, stats, paliers) est dans services/stats.py ; la configuration
(univers, classes, noms de stats, rangs) dans app/data/personnage/config.json.
Les illustrations sont servies en statique par main.py :
/static/personnages/{univers}/{classe}_r{rang}.webp (Anime seulement pour
l'instant, les autres univers ne sont pas encore « disponibles »).

Convention de l'app : les dates exposées sont des millisecondes epoch.
"""
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks, stats
from ..services.common import aware, date_key, now_utc, to_ms

router = APIRouter(prefix="/character", tags=["character"])

NOM_MAX = 30
APPARENCE_MAX_CARACTERES = 4000


def _verifier_apparence(v: dict | None) -> dict | None:
    if v is not None and len(json.dumps(v)) > APPARENCE_MAX_CARACTERES:
        raise ValueError(f"apparence trop volumineuse (plus de {APPARENCE_MAX_CARACTERES} caractères)")
    return v


class CharacterIn(BaseModel):
    universe: str
    class_key: str
    name: str
    appearance: dict | None = None

    @field_validator("name")
    @classmethod
    def _nom(cls, v):
        v = v.strip()
        if not 1 <= len(v) <= NOM_MAX:
            raise ValueError(f"le nom fait de 1 à {NOM_MAX} caractères")
        return v

    @field_validator("appearance")
    @classmethod
    def _apparence(cls, v):
        return _verifier_apparence(v)


class AppearanceIn(BaseModel):
    appearance: dict

    @field_validator("appearance")
    @classmethod
    def _apparence(cls, v):
        return _verifier_apparence(v)


class ClassIn(BaseModel):
    class_key: str


def _classe_valide(universe: str, class_key: str) -> dict:
    u = stats.univers(universe)
    if u is None:
        raise HTTPException(status_code=422, detail=f"Univers inconnu : {universe}")
    if not u["disponible"]:
        raise HTTPException(status_code=422, detail=f"L'univers {u['nom']} n'est pas encore disponible.")
    c = stats.classe(universe, class_key)
    if c is None:
        raise HTTPException(status_code=422, detail=f"Classe inconnue dans l'univers {u['nom']} : {class_key}")
    return c


def _changement_disponible_le(perso: models.Character):
    """None = changement possible tout de suite (jamais changé : le premier
    est gratuit) ; sinon date à partir de laquelle il le redevient."""
    if perso.class_changed_at is None:
        return None
    return aware(perso.class_changed_at) + timedelta(days=stats.config()["changement_classe"]["delai_jours"])


def _serialiser(db: Session, perso: models.Character) -> dict:
    c = stats.classe(perso.universe, perso.class_key) or {"nom": perso.class_key, "archetype": None}
    arch = stats.archetype(perso)
    niveau, xp_niveau, xp_prochain = stats.niveau_pour_xp(perso.total_xp or 0)
    # Le niveau stocké ne redescend jamais ; s'il dépasse celui que donne
    # l'XP (barème changé), la barre repart de zéro plutôt que de mentir.
    if (perso.level or 1) > niveau:
        xp_niveau, xp_prochain = 0, stats.cout_niveau(perso.level)
    rang = stats.rang_pour_niveau(perso.level or 1)
    disponible = _changement_disponible_le(perso)
    return {
        "universe": perso.universe,
        "class_key": perso.class_key,
        "class_name": c["nom"],
        "archetype": c["archetype"],
        "archetype_name": arch["nom"],
        "passive": arch["passif"].get("libelle"),
        "name": perso.name,
        "appearance": perso.appearance or {},
        "level": perso.level,
        "total_xp": perso.total_xp,
        "xp_niveau": xp_niveau,
        "xp_prochain": xp_prochain,
        "rank": rang["rang"],
        "rank_name": rang["nom"],
        "shards": perso.shards,
        "stats": stats.valeurs_stats(db, perso),
        "image": f"/static/personnages/{perso.universe}/{perso.class_key}_r{rang['rang']}.webp",
        "class_change_available_at": to_ms(disponible),
        "created_at": to_ms(perso.created_at),
    }


def _mon_personnage(db: Session, user: models.User) -> models.Character:
    perso = stats.personnage(db, user)
    if perso is None:
        raise HTTPException(status_code=404, detail="Pas encore de personnage.")
    return perso


@router.get("/config")
def get_config(user: models.User = Depends(get_current_user)):
    conf = stats.config()
    return {
        "stats": conf["stats"],
        "universes": [
            {
                "key": cle, "name": u["nom"], "available": u["disponible"],
                "stats": [{"key": s, "label": u["stats"][s]} for s in conf["stats"]],
                "classes": [
                    {"key": c["cle"], "name": c["nom"], "archetype": c["archetype"],
                     "archetype_name": conf["archetypes"][c["archetype"]]["nom"],
                     "passive": conf["archetypes"][c["archetype"]]["passif"]["libelle"]}
                    for c in u["classes"]
                ],
            }
            for cle, u in conf["univers"].items()
        ],
        "archetypes": {
            cle: {"name": a["nom"], "coefficients": a["coefficients"], "base": a["base"],
                  "passive": a["passif"]["libelle"]}
            for cle, a in conf["archetypes"].items()
        },
        "ranks": [{"rank": r["rang"], "name": r["nom"], "min_level": r["niveau_min"]} for r in conf["rangs"]],
        "class_change_days": conf["changement_classe"]["delai_jours"],
    }


@router.get("")
def get_character(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _mon_personnage(db, user)
    # Journées sans, paliers de santé : constatés avant d'afficher les stats.
    personnage_hooks.constater(db, user)
    return _serialiser(db, _mon_personnage(db, user))


@router.post("", status_code=201)
def create_character(
    payload: CharacterIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _classe_valide(payload.universe, payload.class_key)
    if stats.personnage(db, user) is not None:
        raise HTTPException(status_code=409, detail="Personnage déjà créé.")
    try:
        db.add(models.Character(
            user_id=user.id, universe=payload.universe, class_key=payload.class_key,
            name=payload.name, appearance=payload.appearance, created_at=now_utc(),
        ))
        db.commit()
    except IntegrityError:
        # Deux créations simultanées : la seconde bute sur l'unicité de user_id.
        db.rollback()
        raise HTTPException(status_code=409, detail="Personnage déjà créé.")
    # Historique existant rejoué à travers les mêmes règles (idempotent).
    # Un échec ne fait pas échouer la création : il sera repris au besoin.
    personnage_hooks.rattrapage(db, user)
    return _serialiser(db, _mon_personnage(db, user))


@router.put("/appearance")
def update_appearance(
    payload: AppearanceIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    perso = _mon_personnage(db, user)
    perso.appearance = payload.appearance
    db.commit()
    return _serialiser(db, _mon_personnage(db, user))


@router.put("/class")
def change_class(
    payload: ClassIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Premier changement gratuit, puis un tous les 30 jours. Les points sont
    conservés, seules les valeurs affichées changent (coefficients de la
    nouvelle classe). Même univers : le changement d'univers viendra avec les
    autres univers."""
    perso = _mon_personnage(db, user)
    _classe_valide(perso.universe, payload.class_key)
    if payload.class_key == perso.class_key:
        raise HTTPException(status_code=400, detail="C'est déjà ta classe.")
    disponible = _changement_disponible_le(perso)
    if disponible is not None and now_utc() < disponible:
        raise HTTPException(status_code=409, detail={
            "message": f"Prochain changement de classe possible le {disponible.date().isoformat()}.",
            "available_at": to_ms(disponible),
            "available_date": disponible.date().isoformat(),
        })
    perso.class_key = payload.class_key
    perso.class_changed_at = now_utc()
    db.commit()
    return _serialiser(db, _mon_personnage(db, user))


@router.get("/events")
def get_events(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Points et XP gagnés par jour et par stat (graphique d'historique)."""
    _mon_personnage(db, user)
    debut = date_key(now_utc() - timedelta(days=days - 1))
    evenements = db.query(models.StatEvent).filter(
        models.StatEvent.user_id == user.id, models.StatEvent.date_key >= debut,
    ).all()
    cumul: dict[tuple[str, str], dict] = {}
    for e in evenements:
        ligne = cumul.setdefault((e.date_key, e.stat), {"date": e.date_key, "stat": e.stat, "points": 0.0, "xp": 0})
        ligne["points"] += e.points or 0
        ligne["xp"] += e.xp or 0
    lignes = sorted(cumul.values(), key=lambda l: (l["date"], stats.stats_cles().index(l["stat"])
                                                   if l["stat"] in stats.stats_cles() else 99))
    for l in lignes:
        l["points"] = round(l["points"], 2)
    return {"days": days, "from": debut, "events": lignes}
