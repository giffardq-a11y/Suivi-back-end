from dotenv import load_dotenv
load_dotenv()  # doit s'exécuter avant tout import qui lit os.environ (integrations.py, security.py)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import (
    auth, dashboard, entries, habits, meal_photo, integrations, food_search, recipes,
    bad_habits, goals, substances, profile, cycle, training, diet, journal_stats, settings,
    partner,
)

# Pour ce flow de validation : création des tables au démarrage.
# En prod, remplacer par Alembic (migrations versionnées).
Base.metadata.create_all(bind=engine)
from sqlalchemy import text

# Ajoute les colonnes de Habit introduites après la création initiale de la
# table — nécessaire car create_all() ne modifie jamais une table
# existante. Idempotent : chaque ALTER échoue silencieusement si la colonne
# existe déjà (cas normal à partir du 2e redémarrage).
def _ensure_habit_columns():
    statements = [
        "ALTER TABLE habits ADD COLUMN weekly_target INTEGER DEFAULT 7",
        "ALTER TABLE habits ADD COLUMN linked_activity VARCHAR",
        "ALTER TABLE habits ADD COLUMN scheduled_time VARCHAR",
        "ALTER TABLE habits ADD COLUMN notifications_enabled BOOLEAN DEFAULT false",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()  # colonne déjà existante — normal

_ensure_habit_columns()

# Idem pour les colonnes "habitude progressive" ajoutées à Habit (voir
# services/habit_progress.py) — table déjà existante.
def _ensure_progressive_habit_columns():
    statements = [
        "ALTER TABLE habits ADD COLUMN note VARCHAR",
        "ALTER TABLE habits ADD COLUMN habit_type VARCHAR",
        "ALTER TABLE habits ADD COLUMN progressive_rhythm VARCHAR",
        "ALTER TABLE habits ADD COLUMN progressive_start_value FLOAT",
        "ALTER TABLE habits ADD COLUMN progressive_target_value FLOAT",
        "ALTER TABLE habits ADD COLUMN progressive_start_date TIMESTAMPTZ",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()

_ensure_progressive_habit_columns()

# Même principe pour les colonnes ajoutées à Substance (addSubstance —
# habitudes/objectifs restants, voir routers/substances.py) : la table
# `substances` existe déjà (compte de démo) donc create_all() ne les
# ajoutera pas toute seule.
def _ensure_substance_columns():
    statements = [
        "ALTER TABLE substances ADD COLUMN unit VARCHAR",
        "ALTER TABLE substances ADD COLUMN note VARCHAR",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()

_ensure_substance_columns()

# Idem pour les colonnes ajoutées à Goal (objectifs "liés" à une métrique
# réelle de l'app, voir routers/goals.py) — table déjà existante.
def _ensure_goal_columns():
    statements = [
        "ALTER TABLE goals ADD COLUMN linked_type VARCHAR",
        "ALTER TABLE goals ADD COLUMN linked_habit_id VARCHAR",
        "ALTER TABLE goals ADD COLUMN linked_exercise_name VARCHAR",
        "ALTER TABLE goals ADD COLUMN linked_metric VARCHAR",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()

_ensure_goal_columns()

# Idem pour le prix d'une consommation et la note d'une habitude cochée,
# saisis depuis l'Accueil mais jusqu'ici perdus côté serveur.
def _ensure_entry_and_habit_log_columns():
    statements = [
        "ALTER TABLE consumption_entries ADD COLUMN price FLOAT",
        "ALTER TABLE habit_logs ADD COLUMN note VARCHAR",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()

_ensure_entry_and_habit_log_columns()

# Crée le compte de démo automatiquement s'il n'existe pas encore — utile
# sur un hébergeur dont le plan gratuit n'inclut pas d'accès shell (ex.
# Render Free), où lancer `python -m app.seed` manuellement n'est pas
# possible. `seed.run()` est déjà idempotent (ne fait rien si le compte
# existe déjà), donc sans danger à chaque redémarrage du serveur.
from . import seed as _seed
_seed.run()

# Modèles de séance par défaut (Push/Pull/Legs/Dos/Pectoraux), proposés à
# tout le monde — voir WorkoutTemplate.user_id nullable dans models.py.
# Idempotent : ne seede qu'une fois (si aucun modèle "système" n'existe).
def _ensure_default_workout_templates():
    from .database import SessionLocal
    from . import models as _models

    db = SessionLocal()
    try:
        exists = db.query(_models.WorkoutTemplate).filter(_models.WorkoutTemplate.user_id.is_(None)).first()
        if exists:
            return
        defaults = [
            ("Push", [
                {"id": "ex-bench", "name": "Développé couché", "sets": [{"reps": 10, "weight": 40}, {"reps": 8, "weight": 45}, {"reps": 6, "weight": 50}], "restSeconds": 90},
                {"id": "ex-shoulder", "name": "Développé épaules", "sets": [{"reps": 10, "weight": 20}, {"reps": 10, "weight": 22}], "restSeconds": 75},
                {"id": "ex-triceps", "name": "Extension triceps", "sets": [{"reps": 12, "weight": 15}, {"reps": 12, "weight": 15}], "restSeconds": 60},
            ]),
            ("Pull", [
                {"id": "ex-row", "name": "Rowing barre", "sets": [{"reps": 10, "weight": 40}, {"reps": 8, "weight": 45}], "restSeconds": 90},
                {"id": "ex-curl", "name": "Curl biceps", "sets": [{"reps": 12, "weight": 14}, {"reps": 10, "weight": 16}], "restSeconds": 60},
            ]),
            ("Legs", [
                {"id": "ex-squat", "name": "Squat", "sets": [{"reps": 12, "weight": 60}, {"reps": 10, "weight": 70}, {"reps": 8, "weight": 80}], "restSeconds": 120},
                {"id": "ex-lunges", "name": "Fentes", "sets": [{"reps": 12, "weight": 20}, {"reps": 12, "weight": 20}], "restSeconds": 60},
            ]),
            ("Dos", [
                {"id": "ex-deadlift", "name": "Soulevé de terre", "sets": [{"reps": 8, "weight": 60}, {"reps": 6, "weight": 70}], "restSeconds": 120},
                {"id": "ex-pullup", "name": "Tractions", "sets": [{"reps": 8, "weight": 0}, {"reps": 6, "weight": 0}], "restSeconds": 90},
            ]),
            ("Pectoraux", [
                {"id": "ex-bench2", "name": "Développé couché", "sets": [{"reps": 10, "weight": 40}, {"reps": 8, "weight": 45}], "restSeconds": 90},
                {"id": "ex-flyes", "name": "Écarté couché", "sets": [{"reps": 12, "weight": 10}, {"reps": 12, "weight": 10}], "restSeconds": 60},
            ]),
        ]
        for name, exercises in defaults:
            db.add(_models.WorkoutTemplate(user_id=None, name=name, exercises=exercises))
        db.commit()
    finally:
        db.close()

_ensure_default_workout_templates()

app = FastAPI(title="Suivi — API", version="0.1.0")

# CORS ouvert pour le dev de l'app mobile (Expo Go / simulateur).
# À restreindre à l'origine réelle en prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(entries.router)
app.include_router(habits.router)
app.include_router(meal_photo.router)
app.include_router(integrations.router)
app.include_router(food_search.router)
app.include_router(recipes.router)
app.include_router(bad_habits.router)
app.include_router(goals.router)
app.include_router(substances.router)
app.include_router(profile.router)
app.include_router(cycle.router)
app.include_router(training.router)
app.include_router(diet.router)
app.include_router(journal_stats.router)
app.include_router(settings.router)
app.include_router(partner.router)


@app.get("/health")
def health():
    return {"status": "ok"}
