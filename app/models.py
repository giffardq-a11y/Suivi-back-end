import enum
import uuid

from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, ForeignKey, Enum, Integer, Text, JSON
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
    # Substance "perso" ajoutée par l'utilisateur (addSubstance) — pas de
    # champ dédié en base, category=OTHER + ces 2 colonnes suffisent (voir
    # buildSettings/customSubstances côté mock, fusionné ici avec Substance
    # plutôt que dupliqué dans une table à part).
    unit = Column(String, nullable=True)
    note = Column(String, nullable=True)

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
    # Prix réellement payé (saisi dans le log rapide de l'Accueil), sinon
    # quantité × unit_cost de la substance au moment de l'entrée.
    price = Column(Float, nullable=True)

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
    # Ajoutés pour porter côté serveur ce que mockData.js gérait déjà en
    # mémoire (voir state.habits) : le nombre de fois/semaine visé sert à
    # calculer `percent` à partir des HabitLog réels, plutôt que de le
    # stocker (ce qui se désynchroniserait des vrais logs).
    weekly_target = Column(Integer, nullable=False, default=7)
    linked_activity = Column(String, nullable=True)  # 'sport_session' | 'calorie_deficit' | null
    scheduled_time = Column(String, nullable=True)    # 'HH:MM'
    notifications_enabled = Column(Boolean, nullable=False, default=False)
    note = Column(String, nullable=True)
    # Habitude "progressive" (paliers évolutifs, voir services/habit_progress.py)
    # — habit_type identifie le formatteur à utiliser ('sport'|'meditation'|
    # 'hydratation'|'sommeil'), les 3 autres colonnes restent NULL si
    # l'habitude n'est pas progressive.
    habit_type = Column(String, nullable=True)
    progressive_rhythm = Column(String, nullable=True)  # 'lent' | 'normal' | 'rapide'
    progressive_start_value = Column(Float, nullable=True)
    progressive_target_value = Column(Float, nullable=True)
    progressive_start_date = Column(DateTime(timezone=True), nullable=True)
    # Durée de la montée en charge en semaines : sans elle, on retombe sur les
    # rythmes prédéfinis (lent/normal/rapide = 8/4/2 semaines). Sert aux plans
    # à progression explicite (ex. +0,5 km par semaine pendant 15 semaines).
    progressive_weeks = Column(Integer, nullable=True)
    # Unité affichée après la valeur du palier ("km / semaine", "pompes /
    # semaine"...) quand habit_type ne correspond à aucun format connu.
    progressive_unit = Column(String, nullable=True)

    user = relationship("User", back_populates="habits")
    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")


class Reward(Base):
    """Récompense personnelle (le catalogue fourni avec l'app, lui, reste écrit
    dans routers/goals.py). `cost` nul = prix pas encore fixé : la récompense
    s'affiche mais ne peut pas être échangée tant qu'elle n'a pas de prix —
    cas des récompenses importées d'un plan, qui n'en portent pas."""
    __tablename__ = "rewards"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)
    cost = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FlashCard(Base):
    """Carte de révision (danois), affichée pendant les temps de repos d'une
    séance de muscu. `user_id` nul = carte du jeu fourni avec l'app, partagée
    par tout le monde ; sinon carte ajoutée ou importée par l'utilisateur."""
    __tablename__ = "flash_cards"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    language = Column(String, nullable=False, default="da")
    front = Column(String, nullable=False)   # français
    back = Column(String, nullable=False)    # danois
    hint = Column(String, nullable=True)     # prononciation ou exemple
    category = Column(String, nullable=True)
    source = Column(String, nullable=False, default="integre")  # integre | import | manuel
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FlashCardReview(Base):
    """État de mémorisation espacée d'une carte pour un utilisateur (système
    de boîtes : une carte sue monte d'une boîte et revient plus tard, une
    carte ratée redescend en boîte 1 et revient le jour même)."""
    __tablename__ = "flash_card_reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("flash_cards.id"), nullable=False)
    box = Column(Integer, nullable=False, default=1)
    due_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    times_known = Column(Integer, nullable=False, default=0)
    times_again = Column(Integer, nullable=False, default=0)


class FlashCardEvent(Base):
    """Une révision = une ligne. Sert à compter les cartes revues dans la
    journée (habitude Danois cochée au-delà d'un seuil) et les statistiques."""
    __tablename__ = "flash_card_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("flash_cards.id"), nullable=False)
    known = Column(Boolean, nullable=False, default=True)
    context = Column(String, nullable=True)  # 'repos_muscu' | 'libre'
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    habit_id = Column(String, ForeignKey("habits.id"), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note = Column(String, nullable=True)  # "comment ça s'est passé ?" (Accueil)

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
    # Objectif "lié" à une vraie métrique de l'app plutôt qu'à une valeur
    # tapée à la main (voir computeLinkedGoalProgress côté mock) : la
    # progression est alors recalculée à la lecture, jamais stockée.
    linked_type = Column(String, nullable=True)  # 'habit_streak' | 'weight_target' | 'body_fat_target' | 'strength_pr'
    linked_habit_id = Column(String, nullable=True)
    linked_exercise_name = Column(String, nullable=True)
    # Incrémenté par toute séance de sport enregistrée (course/muscu/autre) —
    # voir incrementSessionGoals côté mock.
    linked_metric = Column(String, nullable=True)  # 'sport_sessions'

    user = relationship("User", back_populates="goals")


class RewardPurchase(Base):
    __tablename__ = "reward_purchases"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    reward_item_label = Column(String, nullable=False)
    cost_at_purchase = Column(Float, nullable=False)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reward_purchases")


# ---------------------------------------------------------------------------
# Modèles ajoutés pour brancher les écrans restants (voir SUIVI_RECAP.md) sur
# le vrai backend. Tous nouveaux (pas de colonne ajoutée à une table
# existante) donc `Base.metadata.create_all()` suffit à les créer — pas
# d'ALTER TABLE idempotent nécessaire comme pour Habit (voir main.py).
# Requêtés directement par user_id dans les routers plutôt que via une
# relationship() sur User, pour ne pas toucher à la classe User existante.
# ---------------------------------------------------------------------------


class BadHabit(Base):
    """Habitude "à perdre" — distincte de Substance (pas de coût/économies),
    juste un label + date de dernière occurrence (spec §3.6 bis)."""
    __tablename__ = "bad_habits"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)
    note = Column(String, nullable=True)
    last_occurrence_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Profile(Base):
    """Profil physique 1:1 avec User — sert la suggestion de budget
    calorique (Mifflin-St Jeor) et le poids/objectif cible."""
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    age = Column(Integer, nullable=True)
    height_cm = Column(Float, nullable=True)
    sex = Column(String, nullable=True)  # 'homme' | 'femme' | 'autre'
    activity_level = Column(String, nullable=True)  # cf ACTIVITY_FACTORS
    goal_type = Column(String, nullable=True)  # 'maintien' | 'perte' | 'prise'
    goal_rate_kg_per_month = Column(Float, nullable=True)
    weight_goal_kg = Column(Float, nullable=True)
    daily_calorie_budget = Column(Integer, nullable=False, default=2000)
    suggested_habits_selected = Column(JSON, nullable=False, default=list)
    meal_photo_provider = Column(String, nullable=False, default="gemini_fatsecret")


class WeightEntry(Base):
    __tablename__ = "weight_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    weight_kg = Column(Float, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note = Column(String, nullable=True)
    # Pesées remontées par une balance connectée via Health Connect.
    source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)


class BodyFatEntry(Base):
    __tablename__ = "body_fat_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    percent = Column(Float, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note = Column(String, nullable=True)


class CycleSettings(Base):
    """Réglages de suivi de cycle, 1:1 avec User — opt-in (enabled=False
    par défaut)."""
    __tablename__ = "cycle_settings"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=False)
    avg_cycle_length_days = Column(Integer, nullable=False, default=28)
    avg_period_length_days = Column(Integer, nullable=False, default=5)
    contraception_enabled = Column(Boolean, nullable=False, default=False)
    contraception_method = Column(String, nullable=True)
    contraception_reminder_time = Column(String, nullable=True)


class CycleLog(Base):
    """Un log = des règles en cours ou passées. end_date NULL = en cours."""
    __tablename__ = "cycle_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=True)


class CycleFlowEntry(Base):
    __tablename__ = "cycle_flow_entries"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    date_key = Column(String, nullable=False)  # 'YYYY-MM-DD'
    intensity = Column(String, nullable=False)  # 'leger' | 'moyen' | 'abondant'


class Meal(Base):
    __tablename__ = "meals"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)
    calories = Column(Integer, nullable=False)
    type = Column(String, nullable=False)  # petit-dejeuner | dejeuner | diner | collation
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Run(Base):
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    distance_km = Column(Float, nullable=False)
    duration_min = Column(Float, nullable=False)
    calories_burned = Column(Integer, nullable=False, default=0)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Import automatique depuis la montre (Health Connect) : `source` dit d'où
    # vient la séance, `external_id` est l'identifiant côté montre — c'est lui
    # qui évite de créer un doublon à chaque synchronisation.
    source = Column(String, nullable=True)       # 'health_connect' | None (saisie manuelle)
    external_id = Column(String, nullable=True)
    heart_rate_avg = Column(Integer, nullable=True)
    heart_rate_max = Column(Integer, nullable=True)


class OtherSportLog(Base):
    __tablename__ = "other_sport_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sport_label = Column(String, nullable=False)
    duration_min = Column(Float, nullable=False)
    intensity = Column(String, nullable=True)  # 'faible' | 'moyenne' | 'forte'
    distance_km = Column(Float, nullable=True)
    calories_burned = Column(Integer, nullable=False, default=0)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    heart_rate_avg = Column(Integer, nullable=True)
    heart_rate_max = Column(Integer, nullable=True)


class WorkoutTemplate(Base):
    """Modèle de séance de muscu. `exercises` en JSON plutôt que normalisé
    (table à part) : structure imbriquée (exercices → séries) éditée en bloc
    depuis l'app, jamais interrogée finement côté serveur — voir la même
    logique pour StrengthSession.exercises ci-dessous."""
    __tablename__ = "workout_templates"

    id = Column(String, primary_key=True, default=gen_uuid)
    # NULL = modèle par défaut proposé à tout le monde (voir les 5 modèles
    # seedés dans main.py) plutôt que créé par un utilisateur particulier.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    exercises = Column(JSON, nullable=False, default=list)
    scheduled_time = Column(String, nullable=True)
    notifications_enabled = Column(Boolean, nullable=False, default=False)


class StrengthSession(Base):
    __tablename__ = "strength_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    template_id = Column(String, nullable=True)
    template_name = Column(String, nullable=True)
    mode = Column(String, nullable=False, default="quick_duration")
    duration_min = Column(Float, nullable=False, default=0)
    calories_burned = Column(Integer, nullable=False, default=0)
    exercises = Column(JSON, nullable=False, default=list)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    heart_rate_avg = Column(Integer, nullable=True)
    heart_rate_max = Column(Integer, nullable=True)


class SleepLog(Base):
    """Nuit remontée par la montre (Health Connect). Une nuit = une ligne,
    rattachée au jour du RÉVEIL (dormir de 23h à 7h compte pour le lendemain,
    comme le fait Samsung Health)."""
    __tablename__ = "sleep_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    date_key = Column(String, nullable=False)  # 'YYYY-MM-DD' du réveil
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    duration_min = Column(Float, nullable=False)
    source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)


class DailySteps(Base):
    """Pas d'une journée, écrasés à chaque synchronisation (le total du jour
    en cours augmente au fil des heures)."""
    __tablename__ = "daily_steps"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    date_key = Column(String, nullable=False)  # 'YYYY-MM-DD'
    steps = Column(Integer, nullable=False, default=0)
    source = Column(String, nullable=True)


class HabitReschedule(Base):
    """Report d'un rappel d'habitude pour aujourd'hui — une des 3 voies de
    résolution d'un rappel (avec logHabit et HabitSkipReason)."""
    __tablename__ = "habit_reschedules"

    id = Column(String, primary_key=True, default=gen_uuid)
    habit_id = Column(String, ForeignKey("habits.id"), nullable=False)
    date_key = Column(String, nullable=False)  # 'YYYY-MM-DD'
    new_time = Column(String, nullable=False)


class HabitSkipReason(Base):
    __tablename__ = "habit_skip_reasons"

    id = Column(String, primary_key=True, default=gen_uuid)
    habit_id = Column(String, ForeignKey("habits.id"), nullable=False)
    date_key = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ReportSettings(Base):
    """Préférences du récap quotidien (envoi WhatsApp), 1:1 avec User."""
    __tablename__ = "report_settings"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    auto_send = Column(Boolean, nullable=False, default=True)
    whatsapp_number = Column(String, nullable=True)
    send_time = Column(String, nullable=False, default="20:00")
    reminder_enabled = Column(Boolean, nullable=False, default=True)
    reminder_minutes_before = Column(Integer, nullable=False, default=30)


class PartnerLink(Base):
    """Partage avec un proche — vrai lien à double sens entre 2 comptes
    (remplace l'ancien modèle Partner, à user unique, qui ne reliait pas
    de vrais comptes). requester envoie l'invitation par email vers un
    compte existant ; recipient doit l'accepter pour que status passe à
    'accepted'. Si les deux comptes s'invitent mutuellement (recipient
    avait déjà envoyé une invitation en attente à requester), l'invitation
    est acceptée automatiquement — voir routers/partner.py."""
    __tablename__ = "partner_links"

    id = Column(String, primary_key=True, default=gen_uuid)
    requester_id = Column(String, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # 'pending' | 'accepted'
    scopes = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    accepted_at = Column(DateTime(timezone=True), nullable=True)


class PartnerReminder(Base):
    """Message d'encouragement envoyé par l'un des deux comptes liés à
    l'autre — remplace les 2 rappels de démo en dur côté mock par de vrais
    messages échangés entre comptes réels."""
    __tablename__ = "partner_reminders"

    id = Column(String, primary_key=True, default=gen_uuid)
    link_id = Column(String, ForeignKey("partner_links.id"), nullable=False)
    from_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    text = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


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
