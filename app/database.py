import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Spec §8 : Postgres en prod (Neon, variable DATABASE_URL sur Render).
# SQLite par défaut ici pour que le dev tourne sans aucune infra externe —
# changer DATABASE_URL suffit, le code ORM ne change pas.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./suivi.db")
# Certains hébergeurs donnent encore l'ancien préfixe "postgres://", que
# SQLAlchemy 2 refuse.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    # Neon met la base en veille et coupe les connexions inactives : on
    # vérifie chaque connexion du pool avant de s'en servir.
    pool_pre_ping=not IS_SQLITE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
