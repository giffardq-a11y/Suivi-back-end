"""Crée un compte de démo avec des données réalistes.

Usage : python -m app.seed
"""
from datetime import datetime, timedelta, timezone

from .database import SessionLocal
from . import models
from .security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "motdepasse123"


def run():
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter(models.User.email == DEMO_EMAIL).first()
        if existing:
            print(f"Le compte de démo existe déjà : {DEMO_EMAIL}")
            return

        now = datetime.now(timezone.utc)

        user = models.User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Alex",
            created_at=now - timedelta(days=120),
        )
        db.add(user)
        db.flush()

        alcool = models.Substance(
            user_id=user.id, label="Alcool — 1 verre",
            category=models.SubstanceCategory.ALCOHOL,
            unit_cost=6.0, currency="EUR", usual_frequency_per_day=1.2,
            unit="1 verre",
        )
        tabac = models.Substance(
            user_id=user.id, label="Tabac — 1 cigarette",
            category=models.SubstanceCategory.TOBACCO,
            unit_cost=0.6, currency="EUR", usual_frequency_per_day=8,
            unit="1 cigarette",
        )
        db.add_all([alcool, tabac])
        db.flush()

        # Dernière conso d'alcool il y a 12 jours, dernière cigarette il y a 5 jours.
        db.add(models.ConsumptionEntry(
            user_id=user.id, substance_id=alcool.id,
            type=models.EntryType.CONSUMPTION,
            occurred_at=now - timedelta(days=12),
        ))
        db.add(models.ConsumptionEntry(
            user_id=user.id, substance_id=tabac.id,
            type=models.EntryType.CONSUMPTION,
            occurred_at=now - timedelta(days=5),
        ))
        # Une rechute plus ancienne pour donner du sens au "record personnel".
        db.add(models.ConsumptionEntry(
            user_id=user.id, substance_id=alcool.id,
            type=models.EntryType.CONSUMPTION,
            occurred_at=now - timedelta(days=40),
        ))

        habits = [
            models.Habit(user_id=user.id, key="sport", label="30 min de sport", target="5x / semaine", active=True),
            models.Habit(user_id=user.id, key="meditation", label="Méditation", target="10 min / jour", active=True),
            models.Habit(user_id=user.id, key="hydratation", label="Hydratation", target="2L / jour", active=True),
            models.Habit(user_id=user.id, key="sommeil", label="Sommeil", target="7h minimum", active=True),
        ]
        db.add_all(habits)
        db.flush()

        # Une habitude déjà cochée aujourd'hui pour voir l'état "complété".
        db.add(models.HabitLog(habit_id=habits[0].id, occurred_at=now))

        goals = [
            models.Goal(
                user_id=user.id, label="Zéro alcool", target_value=90, current_value=12,
                weight=2, started_at=now - timedelta(days=12),
            ),
            models.Goal(
                user_id=user.id, label="7 jours sans tabac", target_value=7, current_value=7,
                weight=1, started_at=now - timedelta(days=5), completed_at=now - timedelta(days=1),
            ),
        ]
        db.add_all(goals)

        db.commit()
        print(f"Compte de démo créé : {DEMO_EMAIL} / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    from .migrate import run_migrations

    run_migrations()
    run()
