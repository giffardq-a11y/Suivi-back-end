FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run injecte PORT (8080). Le schéma est migré au démarrage (app/migrate.py).
# SEED_DEMO=0 : pas de compte de démo en ligne.
ENV SEED_DEMO=0
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
