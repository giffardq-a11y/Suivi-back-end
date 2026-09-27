"""Base SQLite neuve par session de test, e-mails capturés, aucun appel
réseau. Lancer depuis backend/ :

    venv/Scripts/python -m pytest
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

_DOSSIER = tempfile.mkdtemp(prefix="suivi-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DOSSIER) / 'test.db'}"
os.environ["SEED_DEMO"] = "0"
os.environ["EMAIL_PROVIDER"] = "console"
os.environ.pop("RENDER", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def emails(monkeypatch):
    """Liste des e-mails « envoyés » pendant le test."""
    envoyes = []

    def faux(destinataire, sujet, texte, html=None):
        envoyes.append({"to": destinataire, "sujet": sujet, "texte": texte})

    import app.routers.auth as auth
    import app.routers.compte as compte
    monkeypatch.setattr(auth, "envoyer_email", faux)
    monkeypatch.setattr(compte, "envoyer_email", faux)
    return envoyes


_compteur = [0]


@pytest.fixture
def nouveau_compte(client):
    """Fabrique de comptes : renvoie (email, mot de passe, en-têtes, user_id)."""
    def creer():
        _compteur[0] += 1
        email = f"test{_compteur[0]}-{os.getpid()}@example.com"
        r = client.post("/auth/signup", json={"email": email, "password": "motdepasse123"})
        assert r.status_code == 201, r.text
        corps = r.json()
        return email, "motdepasse123", {"Authorization": f"Bearer {corps['access_token']}"}, corps["user"]["id"]
    return creer


@pytest.fixture
def evenements(monkeypatch):
    """Événements envoyés au (futur) module Personnage pendant le test, sous
    la forme (source, source_id). Voir app/services/personnage_hooks.py."""
    from app.services import personnage_hooks

    recus = []
    monkeypatch.setattr(personnage_hooks, "evenement",
                        lambda db, user, source, source_id, payload=None: recus.append((source, source_id)))
    return recus
