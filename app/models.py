import enum
import uuid

from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, ForeignKey, Enum, Integer, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class SubstanceCategory(str, enum.Enum):
    """Extension non présente telle quelle dans Spec Backend §2 (Substance n'a
    pas de champ 'type' fixe) : la carte Accueil affiche deux compteurs
    dédiés (alcool / tabac), il faut donc un moyen de les identifier. On
    ajoute cette catégorie plutôt que de deviner par le libellé."""
    ALCOHOL = "alcohol"
    TOBACCO = "tobacco"
    OTHER = "other"


class EntryType(str, enum.Enum):
    CONSUMPTION = "consumption"
    CRAVING_RESISTED = "craving_resisted"
    REPLACEMENT = "replacement"


class Mood(str, enum.Enum):
    LOW = "bas"
    NEUTRAL = "neutre"
    POSITIVE = "positif"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False, default="")
    timezone = Column(String, nullable=False, default="Europe/Paris")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    substances = relationship("Substance", back_populates="user", cascade="all, delete-orphan")
    habits = relationship("Habit", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    entries = relationship("ConsumptionEntry", back_populates="user", cascade="all, delete-orphan")
    reward_purchases = relationship("RewardPurchase", back_populates="user", cascade="all, delete-orphan")


class Substance(Base):
    __tablename__ = "substances"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)
    category = Column(Enum(SubstanceCategory), nullable=False, default=SubstanceCategory.OTHER)
    unit_cost = Column(Float, nullable=False, default=0)
    currency = Column(String, nullable=False, default="EUR")
    # Fréquence habituelle estimée (conso/jour) — spec §3.3 : déduite d'un
    # historique de référence ou saisie manuelle. On stocke la valeur
    # retenue (saisie ou calculée une fois) pour ne pas la recalculer
    # à chaque requête sur un historique qui, par définition, s'arrête
    # au jour de l'arrêt.
    usual_frequency_per_day = Column(Float, nullable=False, default=1.0)

    user = relationship("User", back_populates="substances")
    entries = relationship("ConsumptionEntry", back_populates="substance", cascade="all, delete-orphan")


class ConsumptionEntry(Base):
    __tablename__ = "consumption_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    substance_id = Column(String, ForeignKey("substances.id"), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    quantity = Column(Float, nullable=False, default=1)
    context = Column(String, nullable=True)
    mood = Column(Enum(Mood), nullable=True)
    type = Column(Enum(EntryType), nullable=False, default=EntryType.CONSUMPTION)

    user = relationship("User", back_populates="entries")
    substance = relationship("Substance", back_populates="entries")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    target = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True)

    user = relationship("User", back_populates="habits")
    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    habit_id = Column(String, ForeignKey("habits.id"), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    habit = relationship("Habit", back_populates="logs")


class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)
    target_value = Column(Float, nullable=False)
    current_value = Column(Float, nullable=False, default=0)
    weight = Column(Integer, nullable=False, default=1)  # 1-3, spec §2
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="goals")


class RewardPurchase(Base):
    __tablename__ = "reward_purchases"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    reward_item_label = Column(String, nullable=False)
    cost_at_purchase = Column(Float, nullable=False)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reward_purchases")


class ExternalIntegration(Base):
    """Connexion OAuth à un service tiers (calendrier pour l'instant —
    Google Calendar, Outlook). Un token en clair en base est acceptable
    pour ce projet de démo ; en production, chiffrer access_token/
    refresh_token au repos (ex. via une clé KMS) plutôt que de les stocker
    tels quels."""
    __tablename__ = "external_integrations"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    provider = Column(String, nullable=False)  # 'google_calendar' | 'microsoft_calendar'
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    connected_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
