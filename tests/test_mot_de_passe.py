"""Mot de passe oublié : jeton à usage unique, réponse identique que le
compte existe ou non, limite de demandes."""
from datetime import timedelta

from app import models
from app.database import SessionLocal
from app.services.common import now_utc


def _jeton(emails):
    return emails[-1]["texte"].split("token=")[1].split()[0]


def test_reinitialisation_par_la_page_web(client, nouveau_compte, emails):
    email, ancien, _, _ = nouveau_compte()
    assert client.post("/auth/forgot-password", json={"email": "inconnu@example.com"}).status_code == 202
    assert emails == []
    assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
    jeton = _jeton(emails)

    assert "Nouveau mot de passe" in client.get(f"/compte/mot-de-passe?token={jeton}").text
    r = client.post("/compte/mot-de-passe",
                    data={"token": jeton, "password": "nouveau-mdp-1", "confirmation": "nouveau-mdp-1"})
    assert "Mot de passe changé" in r.text

    assert client.post("/auth/login", json={"email": email, "password": ancien}).status_code == 401
    assert client.post("/auth/login", json={"email": email, "password": "nouveau-mdp-1"}).status_code == 200
    # Usage unique.
    assert client.post("/auth/reset-password", json={"token": jeton, "password": "encore-un-autre"}).status_code == 400


def test_api_reset_et_jeton_expire(client, nouveau_compte, emails):
    email, _, _, user_id = nouveau_compte()
    client.post("/auth/forgot-password", json={"email": email})
    jeton = _jeton(emails)
    assert client.post("/auth/reset-password", json={"token": jeton, "password": "court"}).status_code == 422

    db = SessionLocal()
    for j in db.query(models.AccountToken).filter(models.AccountToken.user_id == user_id).all():
        j.expires_at = now_utc() - timedelta(minutes=1)
    db.commit()
    db.close()
    assert client.post("/auth/reset-password", json={"token": jeton, "password": "assez-long-1"}).status_code == 400
    assert client.post("/auth/reset-password", json={"token": "n-importe-quoi", "password": "assez-long-1"}).status_code == 400


def test_limite_de_demandes(client, nouveau_compte, emails):
    email, _, _, _ = nouveau_compte()
    for _ in range(5):
        assert client.post("/auth/forgot-password", json={"email": email}).status_code == 202
    assert len(emails) == 3
