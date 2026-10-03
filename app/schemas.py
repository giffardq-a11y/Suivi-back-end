from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import CravingOutcome, EntryType, Mood


# ---------- Auth ----------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = ""
    # Modules cochés à l'onboarding ; absent (ancienne version de l'app) =
    # tous les modules.
    modules: Optional[List[str]] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    refresh_token: str


# ---------- Entries (log rapide) ----------

class EntryCreate(BaseModel):
    substance_id: Optional[str] = None
    type: EntryType = EntryType.CONSUMPTION
    quantity: float = 1
    context: Optional[str] = None
    mood: Optional[Mood] = None
    occurred_at: Optional[datetime] = None
    price: Optional[float] = None


class EntryOut(BaseModel):
    id: str
    substance_id: Optional[str]
    type: EntryType
    quantity: float
    context: Optional[str]
    mood: Optional[Mood]
    occurred_at: datetime
    price: Optional[float] = None

    class Config:
        from_attributes = True


# ---------- Dashboard ----------

class StreakOut(BaseModel):
    substance_id: str
    label: str
    category: str
    days: int
    personal_best_days: int
    today_count: float = 0


class SavingsOut(BaseModel):
    total: float
    delta_week: float
    currency: str = "EUR"


class HabitTodayOut(BaseModel):
    id: str
    label: str
    target: Optional[str]
    done_today: bool
    # Une habitude visée 2 fois par semaine ne se lit pas en « fait / pas fait
    # aujourd'hui » : l'Accueil a besoin de la progression de la semaine.
    # Nombres décimaux : en mode volume, ce sont des km, des litres... (2,5 km
    # cette semaine sur 20,5) ; en entier, le tableau de bord tombait en 500
    # dès la première validation fractionnaire.
    done_this_week: float = 0
    weekly_target: float = 7
    weekly: bool = False
    days_of_week: Optional[str] = None
    # Bouton + optimiste de la carte : il doit savoir s'il ajoute une séance
    # ou une quantité (mode volume, séance type `session_quantity`).
    tracking_mode: str = "sessions"
    session_quantity: Optional[float] = None
    # Carte d'habitude (Accueil) : unité du volume, 7 pastilles lundi →
    # dimanche ('done'|'today'|'missed'|'off'|'todo'), série et semaine du
    # plan (habitude progressive à durée explicite).
    unit: Optional[str] = None
    week_days: List[str] = []
    streak: int = 0
    streak_unit: str = "days"
    plan_week: Optional[int] = None
    plan_weeks: Optional[int] = None


class PlannedWorkoutOut(BaseModel):
    id: str
    label: str
    scheduled_time: Optional[str] = None
    done_today: bool = False


class CalorieBalanceOut(BaseModel):
    budget: int
    consumed: int
    burned: int
    net: int
    remaining: int
    meals_logged: int = 0


class GoalSummaryOut(BaseModel):
    active_count: int
    top_goal_label: Optional[str] = None
    top_goal_percent: Optional[float] = None


class RewardBudgetOut(BaseModel):
    multiplier: float
    reward_budget: float
    available_balance: float


class DashboardOut(BaseModel):
    display_name: str
    enabled_modules: List[str] = []
    date: str
    streaks: List[StreakOut]
    savings: SavingsOut
    habits_today: List[HabitTodayOut]
    planned_workouts: List[PlannedWorkoutOut] = []
    calorie_balance: Optional[CalorieBalanceOut] = None
    goals_summary: GoalSummaryOut
    reward_budget: RewardBudgetOut
    thought_of_the_day: str
    # Constats faits à l'ouverture de l'Accueil (journées sans tabac/alcool,
    # paliers de santé, habitudes cochées automatiquement) : toast mobile
    # « +X XP » si personnage_hooks.resumer() y trouve quelque chose, sinon
    # None (voir services/personnage_hooks.py).
    personnage: Optional[dict] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8)


class DeleteAccountRequest(BaseModel):
    password: str


# ---------- Sessions d'aide au craving (routers/cravings.py) ----------

def _texte_ou_none(valeur):
    """Trim ; chaîne vide → None."""
    if isinstance(valeur, str):
        valeur = valeur.strip()
        return valeur or None
    return valeur


def _declencheur(valeur):
    """Déclencheur en liste libre : trim + minuscules, pour que « Stress » et
    « stress » comptent ensemble dans les statistiques."""
    valeur = _texte_ou_none(valeur)
    return valeur.lower() if isinstance(valeur, str) else valeur


class CravingStart(BaseModel):
    substance_id: str
    intensity_start: int = Field(ge=1, le=10)
    trigger: Optional[str] = Field(default=None, max_length=40)
    # Durée de report prévue (minuteur), 10 min par défaut, 2 h au plus.
    planned_seconds: int = Field(default=600, ge=1, le=7200)

    _trigger = field_validator("trigger", mode="before")(_declencheur)


class CravingUpdate(BaseModel):
    """Fin ou mise à jour d'une session. Tout est optionnel ; une session
    terminée garde son issue (voir routers/cravings.py)."""
    outcome: Optional[CravingOutcome] = None
    intensity_end: Optional[int] = Field(default=None, ge=1, le=10)
    note: Optional[str] = Field(default=None, max_length=2000)
    trigger: Optional[str] = Field(default=None, max_length=40)
    # Cédé : créer aussi l'entrée de consommation (même service que
    # POST /entries) et la lier à la session.
    log_entry: bool = False
    quantity: int = Field(default=1, ge=1, le=100)

    _trigger = field_validator("trigger", mode="before")(_declencheur)
    _note = field_validator("note", mode="before")(_texte_ou_none)


class CravingOut(BaseModel):
    id: str
    substance_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    planned_seconds: int
    intensity_start: int
    intensity_end: Optional[int] = None
    trigger: Optional[str] = None
    outcome: CravingOutcome
    note: Optional[str] = None
    entry_id: Optional[str] = None
    # ended_at − started_at en secondes ; null tant que la session est en cours.
    duration_seconds: Optional[int] = None


class DeclencheurCompte(BaseModel):
    nom: str
    nombre: int


class CravingStats(BaseModel):
    substance_id: Optional[str] = None
    jours: int
    total: int
    resistes: int
    cedes: int
    abandonnes: int
    en_cours: int
    # resistes / (resistes + cedes), de 0 à 1 ; null sans session tranchée.
    taux_resistance: Optional[float] = None
    intensite_moyenne_debut: Optional[float] = None
    intensite_moyenne_fin: Optional[float] = None
    duree_moyenne_secondes: Optional[float] = None
    top_declencheurs: List[DeclencheurCompte]
    # Heure locale (fuseau de l'utilisateur) : 24 cases, 0 h → 23 h.
    par_heure: List[int]
    # Jour local : 7 cases, lundi → dimanche.
    par_jour_semaine: List[int]


class CravingSuggestion(BaseModel):
    substance_id: str
    raison: Optional[str] = None
    derniers_resistes: int
