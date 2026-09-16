"""Cartes de révision (danois) affichées pendant les temps de repos d'une
séance de muscu.

Mémorisation espacée par boîtes (Leitner) : une carte sue monte d'une boîte
et revient plus tard, une carte ratée redescend en boîte 1 et revient dans la
foulée. Les intervalles sont volontairement simples et lisibles — pas de
SM-2/Anki ici, l'usage visé est une poignée de cartes entre deux séries.

Au-delà de DAILY_REVIEW_TARGET cartes revues dans la journée, les habitudes
liées à l'activité "danish_review" se cochent toutes seules (même mécanisme
que mark_sport_habits_done_today pour le sport).
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import aware, is_same_day, now_utc

router = APIRouter(prefix="/flashcards", tags=["flashcards"])

DAILY_REVIEW_TARGET = 10
BOX_INTERVALS_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 21, 6: 60}
MAX_BOX = max(BOX_INTERVALS_DAYS)


class ReviewIn(BaseModel):
    cardId: str
    known: bool
    context: str | None = "repos_muscu"


class CardIn(BaseModel):
    front: str
    back: str
    hint: str | None = None
    category: str | None = None


class ImportIn(BaseModel):
    # Texte collé (une carte par ligne, "français ; danois") ou liste de cartes.
    text: str | None = None
    cards: list[CardIn] | None = None
    category: str | None = None


def _visible_cards(db: Session, user: models.User):
    return db.query(models.FlashCard).filter(
        or_(models.FlashCard.user_id.is_(None), models.FlashCard.user_id == user.id)
    )


def _reviewed_today(db: Session, user: models.User) -> int:
    now = now_utc()
    events = (
        db.query(models.FlashCardEvent)
        .filter(models.FlashCardEvent.user_id == user.id)
        .order_by(models.FlashCardEvent.occurred_at.desc())
        .limit(500)
        .all()
    )
    return len({e.card_id for e in events if is_same_day(e.occurred_at, now)})


def _mark_danish_habits(db: Session, user: models.User) -> bool:
    """Coche les habitudes liées aux révisions si le seuil du jour est atteint."""
    if _reviewed_today(db, user) < DAILY_REVIEW_TARGET:
        return False
    now = now_utc()
    marked = False
    habits = (
        db.query(models.Habit)
        .filter(models.Habit.user_id == user.id, models.Habit.linked_activity == "danish_review")
        .all()
    )
    for h in habits:
        if not any(is_same_day(l.occurred_at, now) for l in h.logs):
            db.add(models.HabitLog(habit_id=h.id, occurred_at=now))
            marked = True
    if marked:
        db.commit()
    return marked


def _serialize(card: models.FlashCard, review: models.FlashCardReview | None) -> dict:
    return {
        "id": card.id,
        "front": card.front,
        "back": card.back,
        "hint": card.hint,
        "category": card.category,
        "box": review.box if review else 0,
        "own": card.user_id is not None,
    }


@router.get("/next")
def next_cards(
    count: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Prochaines cartes à réviser : d'abord celles dont l'échéance est passée
    (les plus en retard), puis des cartes jamais vues. Le lot est récupéré en
    une fois au début de la séance, pour réviser même sans réseau en salle."""
    now = now_utc()
    cards = _visible_cards(db, user).all()
    reviews = {
        r.card_id: r
        for r in db.query(models.FlashCardReview).filter(models.FlashCardReview.user_id == user.id).all()
    }

    due, jamais_vues = [], []
    for c in cards:
        r = reviews.get(c.id)
        if r is None:
            jamais_vues.append(c)
        elif aware(r.due_at) <= now:
            due.append((aware(r.due_at), c, r))

    due.sort(key=lambda t: t[0])
    lot = [_serialize(c, r) for _d, c, r in due[:count]]
    for c in jamais_vues[: count - len(lot)]:
        lot.append(_serialize(c, None))

    return {
        "cards": lot,
        "due_total": len(due),
        "never_seen_total": len(jamais_vues),
        "reviewed_today": _reviewed_today(db, user),
        "daily_target": DAILY_REVIEW_TARGET,
    }


@router.post("/review", status_code=201)
def review_card(
    payload: ReviewIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _visible_cards(db, user).filter(models.FlashCard.id == payload.cardId).first()
    if not card:
        raise HTTPException(status_code=404, detail="Carte introuvable")

    now = now_utc()
    review = (
        db.query(models.FlashCardReview)
        .filter(models.FlashCardReview.user_id == user.id, models.FlashCardReview.card_id == card.id)
        .first()
    )
    if review is None:
        review = models.FlashCardReview(user_id=user.id, card_id=card.id, box=1, due_at=now)
        db.add(review)

    # Les valeurs par défaut des colonnes ne s'appliquent qu'à l'écriture :
    # sur une ligne tout juste créée, les compteurs sont encore None.
    if payload.known:
        review.box = min(MAX_BOX, (review.box or 1) + 1)
        review.times_known = (review.times_known or 0) + 1
    else:
        review.box = 1
        review.times_again = (review.times_again or 0) + 1
    review.last_reviewed_at = now
    # Boîte 1 : on la revoit dans la même séance (10 min plus tard).
    jours = BOX_INTERVALS_DAYS[review.box]
    review.due_at = now + (timedelta(days=jours) if jours else timedelta(minutes=10))

    db.add(models.FlashCardEvent(
        user_id=user.id, card_id=card.id, known=payload.known,
        context=payload.context, occurred_at=now,
    ))
    db.commit()

    habit_marked = _mark_danish_habits(db, user)
    revues = _reviewed_today(db, user)
    return {
        "ok": True,
        "box": review.box,
        "next_due_at": review.due_at,
        "reviewed_today": revues,
        "daily_target": DAILY_REVIEW_TARGET,
        "habit_marked": habit_marked,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    cards = _visible_cards(db, user).all()
    reviews = db.query(models.FlashCardReview).filter(models.FlashCardReview.user_id == user.id).all()
    par_boite = {b: 0 for b in BOX_INTERVALS_DAYS}
    due = 0
    for r in reviews:
        par_boite[r.box] = par_boite.get(r.box, 0) + 1
        if aware(r.due_at) <= now:
            due += 1
    return {
        "total_cards": len(cards),
        "own_cards": sum(1 for c in cards if c.user_id),
        "seen_cards": len(reviews),
        "due_now": due + (len(cards) - len(reviews)),
        "by_box": par_boite,
        "reviewed_today": _reviewed_today(db, user),
        "daily_target": DAILY_REVIEW_TARGET,
    }


@router.get("")
def list_cards(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    cards = _visible_cards(db, user).order_by(models.FlashCard.front).all()
    return [
        {"id": c.id, "front": c.front, "back": c.back, "category": c.category,
         "source": c.source, "own": c.user_id is not None}
        for c in cards
    ]


def _parse_lignes(texte: str) -> list[tuple[str, str]]:
    """Accepte "français ; danois", "français<TAB>danois", "français - danois"
    et "français, danois" — l'export de mots de Duolingo et les listes faites
    à la main ne se ressemblent jamais tout à fait."""
    paires = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        for sep in ("\t", ";", " - ", " – ", " = ", ","):
            if sep in ligne:
                gauche, _, droite = ligne.partition(sep)
                if gauche.strip() and droite.strip():
                    paires.append((gauche.strip(), droite.strip()))
                break
    return paires


@router.post("/import", status_code=201)
def import_cards(
    payload: ImportIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    entrees: list[tuple[str, str, str | None]] = []
    if payload.cards:
        entrees += [(c.front, c.back, c.hint) for c in payload.cards]
    if payload.text:
        entrees += [(f, b, None) for f, b in _parse_lignes(payload.text)]
    if not entrees:
        raise HTTPException(status_code=400, detail="Aucune carte reconnue (format attendu : « français ; danois » par ligne)")

    existantes = {(c.front.lower(), c.back.lower()) for c in _visible_cards(db, user).all()}
    ajoutees = 0
    for front, back, hint in entrees:
        if (front.lower(), back.lower()) in existantes:
            continue
        db.add(models.FlashCard(
            user_id=user.id, front=front, back=back, hint=hint,
            category=payload.category or "import", source="import",
        ))
        existantes.add((front.lower(), back.lower()))
        ajoutees += 1
    db.commit()
    return {"ok": True, "recues": len(entrees), "ajoutees": ajoutees, "doublons": len(entrees) - ajoutees}


@router.post("", status_code=201)
def add_card(
    payload: CardIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = models.FlashCard(
        user_id=user.id, front=payload.front, back=payload.back,
        hint=payload.hint, category=payload.category, source="manuel",
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return {"ok": True, "id": card.id}


@router.delete("/{card_id}", status_code=204)
def delete_card(
    card_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = (
        db.query(models.FlashCard)
        .filter(models.FlashCard.id == card_id, models.FlashCard.user_id == user.id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="Carte introuvable (les cartes fournies avec l'app ne se suppriment pas)")
    db.query(models.FlashCardReview).filter(models.FlashCardReview.card_id == card.id).delete()
    db.query(models.FlashCardEvent).filter(models.FlashCardEvent.card_id == card.id).delete()
    db.delete(card)
    db.commit()
