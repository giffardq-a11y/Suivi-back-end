from dotenv import load_dotenv
load_dotenv()  # doit s'exécuter avant tout import qui lit os.environ (integrations.py, security.py)

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

import os

from .migrate import run_migrations
from .routers import (
    auth, dashboard, entries, habits, meal_photo, integrations, food_search, recipes,
    bad_habits, goals, substances, profile, cycle, training, diet, journal_stats, settings,
    partner, flashcards, health_sync,
)

# Schéma à jour avant tout accès à la base (migrations Alembic, voir
# app/migrate.py et migrations/versions/). Remplace l'ancien
# create_all() + ALTER TABLE silencieux au démarrage.
run_migrations()

# Compte de démo (demo@example.com / motdepasse123, voir seed.py) :
# pratique en local, mais un compte au mot de passe public n'a rien à
# faire sur le serveur en ligne. Render définit RENDER=true : désactivé
# par défaut là-bas, forçable des deux côtés avec SEED_DEMO=1 / 0.
if os.environ.get("SEED_DEMO", "0" if os.environ.get("RENDER") else "1") == "1":
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


# Jeu de cartes français -> danois fourni avec l'app (révision pendant les
# temps de repos, voir routers/flashcards.py). Idempotent.
def _ensure_danish_deck():
    from .database import SessionLocal
    from .danish_deck import seed_builtin_deck

    db = SessionLocal()
    try:
        seed_builtin_deck(db)
    finally:
        db.close()


_ensure_danish_deck()

app = FastAPI(title="Suivi — API", version="0.1.0")

# CORS ouvert pour le dev de l'app mobile (Expo Go / simulateur).
# À restreindre à l'origine réelle en prod.
import logging

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_log = logging.getLogger("uvicorn.error")


@app.exception_handler(RequestValidationError)
async def log_validation_error(request, exc: RequestValidationError):
    """Un 422 ne disait pas quel champ posait problème, ce qui rendait un
    refus d'inscription impossible à diagnostiquer à distance. On journalise
    le champ et le type d'erreur — jamais la valeur envoyée (mot de passe,
    e-mail), qui n'a rien à faire dans des logs."""
    champs = [
        {"champ": ".".join(str(p) for p in e.get("loc", [])), "type": e.get("type"), "message": e.get("msg")}
        for e in exc.errors()
    ]
    _log.warning("422 sur %s : %s", request.url.path, champs)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


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
app.include_router(flashcards.router)
app.include_router(health_sync.router)


@app.get("/health")
def health():
    return {"status": "ok"}
