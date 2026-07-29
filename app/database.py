import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Spec §8 : Postgres en prod. SQLite par défaut ici pour que ce flow tourne
# sans aucune infra externe — changer DATABASE_URL suffit, le code ORM ne
# change pas (pas de SQL brut spécifique à un moteur dans ce projet).
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./suivi.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
