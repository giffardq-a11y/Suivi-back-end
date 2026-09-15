from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field

from .models import EntryType, Mood


# ---------- Auth ----------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = ""


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


class SavingsOut(BaseModel):
    total: float
    delta_week: float
    currency: str = "EUR"


class HabitTodayOut(BaseModel):
    id: str
    label: str
    target: Optional[str]
    done_today: bool


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
    date: str
    streaks: List[StreakOut]
    savings: SavingsOut
    habits_today: List[HabitTodayOut]
    goals_summary: GoalSummaryOut
    reward_budget: RewardBudgetOut
    thought_of_the_day: str
