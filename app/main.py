from dotenv import load_dotenv
load_dotenv()  # doit s'exécuter avant tout import qui lit os.environ (integrations.py, security.py)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import auth, dashboard, entries, habits, meal_photo, integrations, food_search, recipes

# Pour ce flow de validation : création des tables au démarrage.
# En prod, remplacer par Alembic (migrations versionnées).
Base.metadata.create_all(bind=engine)

# Crée le compte de démo automatiquement s'il n'existe pas encore — utile
# sur un hébergeur dont le plan gratuit n'inclut pas d'accès shell (ex.
# Render Free), où lancer `python -m app.seed` manuellement n'est pas
# possible. `seed.run()` est déjà idempotent (ne fait rien si le compte
# existe déjà), donc sans danger à chaque redémarrage du serveur.
from . import seed as _seed
_seed.run()

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


@app.get("/health")
def health():
    return {"status": "ok"}
