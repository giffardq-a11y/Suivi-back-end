"""Module Budget : dépenses saisies à la main, catégories avec limite
mensuelle, cagnottes alimentées par l'argent économisé sur l'alcool et le tabac.

Aucune donnée bancaire (ni compte, ni carte) : saisie manuelle uniquement.

L'argent économisé vient de services/savings.compute_savings (le même calcul
que l'Accueil et les objectifs d'économies). Ce total est une estimation
recalculée à chaque lecture à partir des séries sans consommation : il peut
baisser après une rechute. Ce qui est déjà versé dans une cagnotte y reste ;
seul le montant encore disponible au versement est plafonné à zéro.

Montants en une seule devise, comme services/savings.py : pas de conversion.
Les mois sont découpés en UTC, comme les jours dans le reste de l'app.
"""
import re
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import personnage_hooks
from ..services.common import aware, from_ms, now_utc, to_ms
from ..services.savings import compute_savings
from .goals import REWARDS_CATALOG

router = APIRouter(tags=["budget"])

CATEGORIES_PAR_DEFAUT = [
    ("courses", "Courses", "🛒"),
    ("restaurants", "Restaurants", "🍽️"),
    ("transport", "Transport", "🚌"),
    ("logement", "Logement", "🏠"),
    ("loisirs", "Loisirs", "🎉"),
    ("sante", "Santé", "💊"),
    ("abonnements", "Abonnements", "📱"),
    ("autre", "Autre", "📦"),
]
SOURCES_CAGNOTTE = ("manual", "sobriety_savings")
CLE_VALIDE = re.compile(r"^[a-z0-9_]{1,32}$")
MOIS_VALIDE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------- Schémas ----------

class ExpenseIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    categoryKey: str
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    note: str | None = None
    occurredAtMs: int | None = None


class CategoryIn(BaseModel):
    key: str
    label: str = Field(min_length=1, max_length=60)
    icon: str | None = None
    monthlyLimit: float | None = Field(default=None, ge=0)

    @field_validator("key")
    @classmethod
    def _cle(cls, v):
        if not CLE_VALIDE.match(v):
            raise ValueError("clé attendue : minuscules, chiffres et _, 32 caractères au plus")
        return v


class CategoriesIn(BaseModel):
    categories: list[CategoryIn] = Field(min_length=1, max_length=30)

    @field_validator("categories")
    @classmethod
    def _uniques(cls, v):
        cles = [c.key for c in v]
        if len(cles) != len(set(cles)):
            raise ValueError("clés de catégorie en double")
        return v


class PotIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    targetAmount: float = Field(gt=0, le=10_000_000)
    source: str = "manual"
    rewardId: str | None = None

    @field_validator("source")
    @classmethod
    def _source(cls, v):
        if v not in SOURCES_CAGNOTTE:
            raise ValueError("source : 'manual' ou 'sobriety_savings'")
        return v


class TransferIn(BaseModel):
    # Absent avec source 'sobriety_savings' = verser tout ce qui est disponible.
    amount: float | None = Field(default=None, gt=0, le=10_000_000)
    source: str | None = None

    @field_validator("source")
    @classmethod
    def _source(cls, v):
        if v is not None and v not in SOURCES_CAGNOTTE:
            raise ValueError("source : 'manual' ou 'sobriety_savings'")
        return v


# ---------- Outils ----------

def _mois(month: str | None) -> tuple[str, datetime, datetime]:
    """('YYYY-MM', début inclus, fin exclue) en UTC ; mois courant par défaut."""
    if month is None:
        month = now_utc().strftime("%Y-%m")
    elif not MOIS_VALIDE.match(month):
        raise HTTPException(status_code=422, detail="Mois attendu au format YYYY-MM")
    annee, m = int(month[:4]), int(month[5:])
    debut = datetime(annee, m, 1, tzinfo=timezone.utc)
    fin = datetime(annee + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    return month, debut, fin


def _categories(db: Session, user: models.User) -> list[models.BudgetCategory]:
    lignes = (
        db.query(models.BudgetCategory)
        .filter(models.BudgetCategory.user_id == user.id)
        .order_by(models.BudgetCategory.position)
        .all()
    )
    if lignes:
        return lignes
    try:
        for i, (cle, libelle, icone) in enumerate(CATEGORIES_PAR_DEFAUT):
            db.add(models.BudgetCategory(user_id=user.id, key=cle, label=libelle, icon=icone, position=i))
        db.commit()
    except IntegrityError:
        # Première lecture en parallèle : l'autre requête a déjà créé les catégories.
        db.rollback()
    return (
        db.query(models.BudgetCategory)
        .filter(models.BudgetCategory.user_id == user.id)
        .order_by(models.BudgetCategory.position)
        .all()
    )


def _serialiser_categorie(c: models.BudgetCategory) -> dict:
    return {"key": c.key, "label": c.label, "icon": c.icon, "monthlyLimit": c.monthly_limit}


def _serialiser_depense(e: models.Expense) -> dict:
    return {"id": e.id, "occurredAt": to_ms(e.occurred_at), "amount": e.amount, "currency": e.currency,
            "categoryKey": e.category_key, "note": e.note}


def _depenses_du_mois(db: Session, user: models.User, debut: datetime, fin: datetime) -> list[models.Expense]:
    lignes = db.query(models.Expense).filter(models.Expense.user_id == user.id).all()
    return sorted((e for e in lignes if debut <= aware(e.occurred_at) < fin),
                  key=lambda e: aware(e.occurred_at), reverse=True)


def _economies(db: Session, user: models.User) -> dict:
    total, _delta = compute_savings(db, user)
    verse = sum(
        t.amount for t in db.query(models.SavingsTransfer).filter(
            models.SavingsTransfer.user_id == user.id, models.SavingsTransfer.source == "sobriety_savings")
    )
    return {"total": round(total, 2), "transferred": round(verse, 2), "available": round(max(0.0, total - verse), 2)}


def _recompense(db: Session, user: models.User, reward_id: str | None) -> dict | None:
    if not reward_id:
        return None
    catalogue = next((r for r in REWARDS_CATALOG if r["id"] == reward_id), None)
    if catalogue:
        return {"id": catalogue["id"], "label": catalogue["label"], "cost": catalogue["cost"]}
    perso = db.query(models.Reward).filter(models.Reward.id == reward_id, models.Reward.user_id == user.id).first()
    return {"id": perso.id, "label": perso.label, "cost": perso.cost} if perso else None


def _serialiser_cagnotte(db: Session, user: models.User, p: models.SavingsPot) -> dict:
    recompense = _recompense(db, user, p.reward_id)
    return {
        "id": p.id, "label": p.label, "targetAmount": p.target_amount, "currentAmount": round(p.current_amount, 2),
        "percent": min(100, round(100 * p.current_amount / p.target_amount)) if p.target_amount else 0,
        "source": p.source, "createdAt": to_ms(p.created_at), "achievedAt": to_ms(p.achieved_at),
        "reward": recompense,
        # La récompense se « paie » toujours par POST /rewards/{id}/purchase
        # (routers/goals.py) ; la cagnotte dit seulement si elle suffit.
        "rewardFunded": bool(recompense and recompense["cost"] is not None
                             and p.current_amount >= recompense["cost"]),
    }


# ---------- Dépenses ----------

@router.get("/expenses")
def list_expenses(
    month: str | None = Query(None, description="'YYYY-MM', mois courant par défaut"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _, debut, fin = _mois(month)
    return [_serialiser_depense(e) for e in _depenses_du_mois(db, user, debut, fin)]


@router.post("/expenses", status_code=201)
def add_expense(
    payload: ExpenseIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.categoryKey not in {c.key for c in _categories(db, user)}:
        raise HTTPException(status_code=400, detail="Catégorie inconnue")
    e = models.Expense(
        user_id=user.id, amount=round(payload.amount, 2), currency=payload.currency.upper(),
        category_key=payload.categoryKey, note=payload.note,
        occurred_at=from_ms(payload.occurredAtMs) if payload.occurredAtMs is not None else now_utc(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _serialiser_depense(e)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    e = db.query(models.Expense).filter(models.Expense.id == expense_id, models.Expense.user_id == user.id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="Dépense introuvable")
    db.delete(e)
    db.commit()


# ---------- Catégories ----------

@router.get("/budget/categories")
def get_categories(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_serialiser_categorie(c) for c in _categories(db, user)]


@router.put("/budget/categories")
def put_categories(
    payload: CategoriesIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Remplace la liste entière (ordre compris) : l'écran de réglage envoie
    tout ce qu'il affiche. Une catégorie absente est retirée ; ses dépenses
    passées restent, comptées sous leur clé dans le résumé du mois."""
    existantes = {c.key: c for c in _categories(db, user)}
    voulues = {c.key for c in payload.categories}
    for cle, c in existantes.items():
        if cle not in voulues:
            db.delete(c)
    for i, c in enumerate(payload.categories):
        ligne = existantes.get(c.key)
        if ligne is None:
            ligne = models.BudgetCategory(user_id=user.id, key=c.key)
            db.add(ligne)
        ligne.label, ligne.icon, ligne.monthly_limit, ligne.position = c.label.strip(), c.icon, c.monthlyLimit, i
    db.commit()
    return [_serialiser_categorie(c) for c in _categories(db, user)]


# ---------- Cagnottes ----------

@router.get("/savings-pots")
def list_pots(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    cagnottes = (
        db.query(models.SavingsPot)
        .filter(models.SavingsPot.user_id == user.id)
        .order_by(models.SavingsPot.created_at)
        .all()
    )
    return {"pots": [_serialiser_cagnotte(db, user, p) for p in cagnottes], "sobrietySavings": _economies(db, user)}


@router.post("/savings-pots", status_code=201)
def add_pot(
    payload: PotIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.rewardId and _recompense(db, user, payload.rewardId) is None:
        raise HTTPException(status_code=404, detail="Récompense introuvable")
    p = models.SavingsPot(user_id=user.id, label=payload.label.strip(), target_amount=payload.targetAmount,
                          current_amount=0, source=payload.source, reward_id=payload.rewardId, created_at=now_utc())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialiser_cagnotte(db, user, p)


@router.post("/savings-pots/{pot_id}/transfer", status_code=201)
def transfer_to_pot(
    pot_id: str,
    payload: TransferIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p = db.query(models.SavingsPot).filter(models.SavingsPot.id == pot_id, models.SavingsPot.user_id == user.id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Cagnotte introuvable")
    source = payload.source or p.source
    montant = payload.amount
    if source == "sobriety_savings":
        disponible = _economies(db, user)["available"]
        if montant is None:
            montant = disponible
        if montant <= 0:
            raise HTTPException(status_code=400, detail="Aucune économie disponible à verser pour l'instant.")
        if montant > disponible + 0.005:
            raise HTTPException(status_code=400, detail=f"Seulement {disponible:.2f} d'économies disponibles.")
    elif montant is None:
        raise HTTPException(status_code=422, detail="Montant requis pour un versement manuel")

    montant = round(montant, 2)
    db.add(models.SavingsTransfer(user_id=user.id, pot_id=p.id, amount=montant, source=source, occurred_at=now_utc()))
    atteint_avant = p.achieved_at is not None
    p.current_amount = round((p.current_amount or 0) + montant, 2)
    if not atteint_avant and p.current_amount >= p.target_amount:
        p.achieved_at = now_utc()
    db.commit()
    db.refresh(p)
    resultat = None
    if not atteint_avant and p.achieved_at is not None:
        resultat = personnage_hooks.evenement(db, user, "savings_pot_achieved", p.id, {"targetAmount": p.target_amount})
    return {
        **_serialiser_cagnotte(db, user, p), "transferred": montant, "sobrietySavings": _economies(db, user),
        "personnage": personnage_hooks.resumer([resultat]),
    }


# ---------- Résumé du mois ----------

@router.get("/budget/summary")
def budget_summary(
    month: str | None = Query(None, description="'YYYY-MM', mois courant par défaut"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    mois, debut, fin = _mois(month)
    categories = _categories(db, user)
    depenses = _depenses_du_mois(db, user, debut, fin)

    par_cle: dict[str, float] = {}
    for e in depenses:
        par_cle[e.category_key] = par_cle.get(e.category_key, 0.0) + e.amount

    lignes = []
    for c in categories:
        depense = round(par_cle.pop(c.key, 0.0), 2)
        lignes.append({
            "key": c.key, "label": c.label, "icon": c.icon, "spent": depense, "limit": c.monthly_limit,
            "remaining": round(c.monthly_limit - depense, 2) if c.monthly_limit is not None else None,
            "percent": round(100 * depense / c.monthly_limit) if c.monthly_limit else None,
            "archived": False,
        })
    # Dépenses d'une catégorie retirée depuis : comptées, mais signalées.
    for cle, montant in sorted(par_cle.items()):
        lignes.append({"key": cle, "label": cle, "icon": None, "spent": round(montant, 2), "limit": None,
                       "remaining": None, "percent": None, "archived": True})

    total = round(sum(e.amount for e in depenses), 2)
    limites = [c.monthly_limit for c in categories if c.monthly_limit is not None]
    # Budget total = somme des limites posées. Aucune limite : pas de budget,
    # donc ni « sous » ni « au-dessus ».
    budget_total = round(sum(limites), 2) if limites else None
    mois_termine = now_utc() >= fin
    sous_budget = total <= budget_total if budget_total is not None else None
    resultat = None
    if mois_termine and sous_budget:
        # Constaté à la lecture, une fois le mois fini ; dédoublonné par le
        # Personnage sur (source, 'YYYY-MM'), voir services/personnage_hooks.py.
        resultat = personnage_hooks.evenement(db, user, "budget_month_under", mois, {"spent": total, "budget": budget_total})

    devises = Counter(e.currency for e in depenses)
    return {
        "month": mois,
        "currency": devises.most_common(1)[0][0] if devises else "EUR",
        "totalSpent": total,
        "totalBudget": budget_total,
        "remaining": round(budget_total - total, 2) if budget_total is not None else None,
        "underBudget": sous_budget,
        "monthComplete": mois_termine,
        "expensesCount": len(depenses),
        "byCategory": lignes,
        "personnage": personnage_hooks.resumer([resultat]),
    }
