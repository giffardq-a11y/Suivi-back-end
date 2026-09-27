"""Lot B de l'audit : jetons de rafraîchissement (rotation, réutilisation,
déconnexion), limites de tentatives, state OAuth, chiffrement des jetons
OAuth, CORS, cloisonnement des données entre comptes."""
from sqlalchemy import text

from app import models
from app.database import SessionLocal
from app.security import create_oauth_state, decode_oauth_state, _create_token
from app.services import limite
from app.services.chiffrement import chiffrer_restants
from datetime import timedelta


def _connexion(client, email, mdp="motdepasse123"):
    r = client.post("/auth/login", json={"email": email, "password": mdp})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Jetons de rafraîchissement ----------

def test_rotation_et_detection_de_reutilisation(client, nouveau_compte):
    email, _, _, _ = nouveau_compte()
    r1 = _connexion(client, email)["refresh_token"]

    r2 = client.post("/auth/refresh", json={"refresh_token": r1})
    assert r2.status_code == 200
    r2 = r2.json()["refresh_token"]
    assert r2 != r1

    # r1 a déjà été échangé : le présenter à nouveau = vol probable.
    assert client.post("/auth/refresh", json={"refresh_token": r1}).status_code == 401
    # ... et toute la famille est révoquée, y compris r2.
    assert client.post("/auth/refresh", json={"refresh_token": r2}).status_code == 401


def test_deconnexion_revoque_le_jeton_de_l_appareil(client, nouveau_compte):
    email, _, _, _ = nouveau_compte()
    appareil_a = _connexion(client, email)["refresh_token"]
    appareil_b = _connexion(client, email)["refresh_token"]
    assert client.post("/auth/logout", json={"refresh_token": appareil_a}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": appareil_a}).status_code == 401
    # L'autre appareil reste connecté.
    assert client.post("/auth/refresh", json={"refresh_token": appareil_b}).status_code == 200
    # Déconnexion avec un jeton invalide : silencieuse.
    assert client.post("/auth/logout", json={"refresh_token": "n-importe-quoi"}).status_code == 204


def test_ancien_jeton_sans_jti_accepte_une_derniere_fois(client, nouveau_compte):
    _, _, _, user_id = nouveau_compte()
    ancien = _create_token(user_id, timedelta(days=30), "refresh")  # format d'avant la rotation
    r = client.post("/auth/refresh", json={"refresh_token": ancien})
    assert r.status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 200


def test_jeton_d_acces_refuse_comme_refresh(client, nouveau_compte):
    email, _, _, _ = nouveau_compte()
    acces = _connexion(client, email)["access_token"]
    assert client.post("/auth/refresh", json={"refresh_token": acces}).status_code == 401


def test_nouveau_mot_de_passe_ferme_toutes_les_sessions(client, nouveau_compte, emails):
    email, _, _, _ = nouveau_compte()
    session = _connexion(client, email)["refresh_token"]
    client.post("/auth/forgot-password", json={"email": email})
    jeton = emails[-1]["texte"].split("token=")[1].split()[0]
    assert client.post("/auth/reset-password", json={"token": jeton, "password": "tout-nouveau-1"}).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": session}).status_code == 401


# ---------- Limites de tentatives ----------

def test_limite_par_compte_vise(client, nouveau_compte):
    email, _, _, _ = nouveau_compte()
    maximum, _ = limite.CONNEXION_PAR_COMPTE
    for _ in range(maximum):
        assert client.post("/auth/login", json={"email": email, "password": "mauvais"}).status_code == 401
    bloque = client.post("/auth/login", json={"email": email, "password": "motdepasse123"})
    assert bloque.status_code == 429 and "Retry-After" in bloque.headers


def test_limite_par_ip_et_ip_lue_a_droite(client):
    maximum, _ = limite.CONNEXION_PAR_IP
    # Une IP falsifiée à gauche ne permet pas de contourner la limite : seule
    # la dernière adresse (posée par le proxy) compte.
    for i in range(maximum):
        r = client.post("/auth/login", json={"email": f"x{i}@example.com", "password": "p"},
                        headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"})
        assert r.status_code == 401
    r = client.post("/auth/login", json={"email": "y@example.com", "password": "p"},
                    headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert r.status_code == 429
    # Une autre adresse réelle n'est pas bloquée.
    r = client.post("/auth/login", json={"email": "y@example.com", "password": "p"},
                    headers={"X-Forwarded-For": "203.0.113.8"})
    assert r.status_code == 401


# ---------- OAuth ----------

def test_state_oauth_signe_et_lie_au_fournisseur(client, nouveau_compte, monkeypatch):
    _, _, h, user_id = nouveau_compte()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-test")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-test")
    url = client.get("/integrations/google_calendar/authorize", headers=h).json()["authorize_url"]
    assert f"state={user_id}" not in url

    state = create_oauth_state(user_id, "google_calendar")
    assert decode_oauth_state(state, "google_calendar") == user_id
    # L'ancien format (user_id en clair) et un state d'un autre fournisseur sont refusés.
    assert client.get(f"/integrations/google_calendar/callback?code=x&state={user_id}").status_code == 400
    autre = create_oauth_state(user_id, "microsoft_calendar")
    assert client.get(f"/integrations/google_calendar/callback?code=x&state={autre}").status_code == 400


def test_jetons_oauth_chiffres_au_repos(nouveau_compte, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _, _, _, user_id = nouveau_compte()
    db = SessionLocal()
    db.add(models.ExternalIntegration(user_id=user_id, provider="google_calendar",
                                      access_token="acces-secret", refresh_token="refresh-secret"))
    db.commit()
    brut = db.execute(text("SELECT access_token, refresh_token FROM external_integrations WHERE user_id = :u"),
                      {"u": user_id}).one()
    assert brut[0].startswith("enc1:") and "acces-secret" not in brut[0]
    assert brut[1].startswith("enc1:")
    db.expire_all()
    lu = db.query(models.ExternalIntegration).filter_by(user_id=user_id).one()
    assert (lu.access_token, lu.refresh_token) == ("acces-secret", "refresh-secret")

    # Une ligne écrite en clair avant le chiffrement est chiffrée au démarrage.
    db.execute(text("UPDATE external_integrations SET access_token = 'en-clair' WHERE user_id = :u"), {"u": user_id})
    db.commit()
    assert chiffrer_restants(db) >= 1
    brut = db.execute(text("SELECT access_token FROM external_integrations WHERE user_id = :u"), {"u": user_id}).scalar()
    assert brut.startswith("enc1:")
    db.expire_all()
    assert db.query(models.ExternalIntegration).filter_by(user_id=user_id).one().access_token == "en-clair"
    db.close()


# ---------- CORS ----------

def test_cors_limite_aux_origines_connues(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:8090", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8090"
    ko = client.options("/health", headers={"Origin": "https://site-malveillant.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in ko.headers


# ---------- Cloisonnement ----------

def test_un_compte_ne_touche_pas_aux_donnees_d_un_autre(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    _, _, h_b, _ = nouveau_compte()

    item = client.post("/diet/pantry/items", headers=h_a, json={"label": "Pâtes", "location": "placard"})
    assert item.status_code == 201
    item_id = client.get("/diet/pantry", headers=h_a).json()["emplacements"]["placard"][0]["id"]
    habitude = client.post("/habits", headers=h_a, json={"label": "Lire"}).json()
    mauvaise = client.post("/bad-habits", headers=h_a, json={"label": "Grignoter"}).json()
    recompense = client.post("/rewards", headers=h_a, json={"label": "Cinéma", "cost": 10}).json()

    # B ne voit rien de A.
    assert client.get("/diet/pantry", headers=h_b).json()["nb_articles"] == 0
    assert all(h["id"] != habitude["id"] for h in client.get("/habits", headers=h_b).json())

    # B ne peut ni modifier ni supprimer les objets de A.
    assert client.put(f"/diet/pantry/items/{item_id}", headers=h_b,
                      json={"label": "Volé", "location": "placard"}).status_code == 404
    client.delete(f"/diet/pantry/items/{item_id}", headers=h_b)
    client.delete(f"/habits/{habitude['id']}", headers=h_b)
    client.delete(f"/bad-habits/{mauvaise['id']}", headers=h_b)
    client.delete(f"/rewards/{recompense['id']}", headers=h_b)

    # Tout est intact chez A.
    assert client.get("/diet/pantry", headers=h_a).json()["nb_articles"] == 1
    assert any(h["id"] == habitude["id"] for h in client.get("/habits", headers=h_a).json())
    assert any(b["id"] == mauvaise["id"] for b in client.get("/bad-habits", headers=h_a).json())
    ids_recompenses = str(client.get("/rewards", headers=h_a).json())
    assert recompense["id"] in ids_recompenses
