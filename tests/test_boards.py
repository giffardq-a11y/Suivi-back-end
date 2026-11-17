"""Tableaux communs : création, invitations, droits, plafond, lien d'écran,
reprise des anciens liens (migration 0028)."""
import hashlib
import uuid
from datetime import datetime, timezone

from app import models
from app.database import SessionLocal, engine
from app.services.reprise_tableaux import reprendre


def _creer(client, h, nom="Famille"):
    r = client.post("/boards", json={"name": nom}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _inviter(client, h, board_id, email):
    return client.post(f"/boards/{board_id}/invite", json={"email": email}, headers=h)


def _lien(client, h, board_id):
    r = client.post(f"/boards/{board_id}/link", headers=h)
    assert r.status_code == 201, r.text
    return f"/board/{r.json()['token']}"


def test_inviter_accepter_et_affichage(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    email_b, _, h_b, _ = nouveau_compte()
    email_c, _, h_c, _ = nouveau_compte()
    tableau = _creer(client, h_a)
    assert tableau["isOwner"] and [m["isOwner"] for m in tableau["members"]] == [True]
    chemin = _lien(client, h_a, tableau["id"])

    for email in (email_b, email_c):
        assert _inviter(client, h_a, tableau["id"], email).status_code == 200
    # Le créateur voit les invitations en attente, avec l'e-mail qu'il a saisi.
    vu = client.get("/boards", headers=h_a).json()["boards"][0]
    assert sorted(m.get("email", "") for m in vu["members"] if m["status"] == "pending") == sorted([email_b, email_c])

    # En attente : pas sur l'écran.
    assert len(client.get(chemin).json()["people"]) == 1
    invitation = client.get("/boards", headers=h_b).json()["invitations"][0]
    assert invitation["name"] == "Famille" and client.get("/boards", headers=h_b).json()["boards"] == []
    assert client.post(f"/boards/{tableau['id']}/accept", headers=h_b).status_code == 200

    public = client.get(chemin)
    assert len(public.json()["people"]) == 2
    assert email_b not in public.text and email_c not in public.text

    # Un membre ne voit ni les invitations en attente ni les e-mails.
    vu_b = client.get("/boards", headers=h_b).json()["boards"][0]
    assert not vu_b["isOwner"] and all(m["status"] == "accepted" and "email" not in m for m in vu_b["members"])

    # C refuse (même route que quitter) ; B quitte.
    membre_c = client.get("/boards", headers=h_c).json()["invitations"][0]["memberId"]
    assert client.delete(f"/boards/{tableau['id']}/members/{membre_c}", headers=h_c).status_code == 204
    moi_b = next(m["id"] for m in vu_b["members"] if m["isMe"])
    assert client.delete(f"/boards/{tableau['id']}/members/{moi_b}", headers=h_b).status_code == 204
    assert len(client.get(chemin).json()["people"]) == 1


def test_droits_du_createur(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    email_b, _, h_b, _ = nouveau_compte()
    _, _, h_x, _ = nouveau_compte()
    tableau = _creer(client, h_a)
    _inviter(client, h_a, tableau["id"], email_b)
    client.post(f"/boards/{tableau['id']}/accept", headers=h_b)

    # Membre : ni lien, ni invitation, ni suppression, ni retrait d'un autre.
    createur_id = tableau["members"][0]["id"]
    email_c, _, h_c, _ = nouveau_compte()
    _inviter(client, h_a, tableau["id"], email_c)
    autre = next(m["id"] for m in client.get("/boards", headers=h_a).json()["boards"][0]["members"] if m.get("email") == email_c)
    assert client.delete(f"/boards/{tableau['id']}/members/{autre}", headers=h_b).status_code == 404
    assert client.delete(f"/boards/{tableau['id']}/members/{createur_id}", headers=h_b).status_code == 404
    assert client.post(f"/boards/{tableau['id']}/link", headers=h_b).status_code == 403
    assert _inviter(client, h_b, tableau["id"], "x@example.com").status_code == 403
    assert client.delete(f"/boards/{tableau['id']}", headers=h_b).status_code == 403
    # Étranger : le tableau n'existe pas pour lui.
    assert client.post(f"/boards/{tableau['id']}/link", headers=h_x).status_code == 404
    assert client.post(f"/boards/{tableau['id']}/accept", headers=h_x).status_code == 404
    createur = next(m["id"] for m in tableau["members"])
    assert client.delete(f"/boards/{tableau['id']}/members/{createur}", headers=h_x).status_code == 404
    # Le créateur ne quitte pas son tableau, il le supprime.
    assert client.delete(f"/boards/{tableau['id']}/members/{createur}", headers=h_a).status_code == 400
    assert client.delete(f"/boards/{tableau['id']}", headers=h_a).status_code == 204
    assert client.get("/boards", headers=h_b).json()["boards"] == []


def test_plafond_de_six_et_invitations(client, nouveau_compte):
    email_a, _, h_a, _ = nouveau_compte()
    tableau = _creer(client, h_a)
    assert _inviter(client, h_a, tableau["id"], email_a).status_code == 400
    assert _inviter(client, h_a, tableau["id"], "personne-inconnue@example.com").status_code == 404
    emails = [nouveau_compte()[0] for _ in range(6)]
    for email in emails[:5]:
        assert _inviter(client, h_a, tableau["id"], email).status_code == 200
    assert _inviter(client, h_a, tableau["id"], emails[0]).status_code == 200  # déjà invité : sans effet
    r = _inviter(client, h_a, tableau["id"], emails[5])
    assert r.status_code == 400 and "6" in r.json()["detail"]
    assert client.post("/boards", json={"name": "  "}, headers=h_a).status_code == 400


def test_createur_en_premier_sur_l_ecran(client, nouveau_compte):
    _, _, h_a, a = nouveau_compte()
    email_b, _, h_b, b = nouveau_compte()
    db = SessionLocal()
    try:
        db.query(models.User).filter(models.User.id == a).update({"display_name": "Créatrice"})
        db.query(models.User).filter(models.User.id == b).update({"display_name": "Invité"})
        db.commit()
    finally:
        db.close()
    tableau = _creer(client, h_a)
    _inviter(client, h_a, tableau["id"], email_b)
    client.post(f"/boards/{tableau['id']}/accept", headers=h_b)
    # Le créateur repasse en dernier par date d'acceptation : il reste en tête.
    db = SessionLocal()
    try:
        db.query(models.BoardMember).filter(models.BoardMember.user_id == a).update(
            {"accepted_at": datetime(2100, 1, 1, tzinfo=timezone.utc)})
        db.commit()
    finally:
        db.close()
    noms = [p["name"] for p in client.get(_lien(client, h_a, tableau["id"])).json()["people"]]
    assert noms == ["Créatrice", "Invité"]


def test_lien_rendu_une_seule_fois(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    tableau = _creer(client, h)
    chemin = _lien(client, h, tableau["id"])
    liste = client.get("/boards", headers=h)
    assert chemin.split("/")[-1] not in liste.text and liste.json()["boards"][0]["link"]["enabled"] is True


def test_reprise_des_anciens_liens(client, nouveau_compte):
    """Migration 0028 : un lien board_shares devient « Mon tableau » avec le
    même jeton ; le proche lié qui avait aussi un lien y devient membre."""
    _, _, _, a = nouveau_compte()
    _, _, _, b = nouveau_compte()
    _, _, _, c = nouveau_compte()
    _, _, _, d = nouveau_compte()  # proche de c, sans lien à lui : pas repris
    jetons = {u: f"ancien-{uuid.uuid4()}" for u in (a, b, c)}
    db = SessionLocal()
    try:
        for u, jeton in jetons.items():
            db.add(models.BoardShare(user_id=u, token_hash=hashlib.sha256(jeton.encode()).hexdigest(),
                                     created_at=datetime.now(timezone.utc)))
        db.add(models.PartnerLink(requester_id=a, recipient_id=b, status="accepted", scopes=[]))
        db.add(models.PartnerLink(requester_id=c, recipient_id=d, status="accepted", scopes=[]))
        db.query(models.User).filter(models.User.id == b).update({"display_name": "Bea"})
        db.commit()
    finally:
        db.close()

    with engine.begin() as conn:
        assert reprendre(conn) == 3
    with engine.begin() as conn:
        assert reprendre(conn) == 0  # rejouable

    ecran_a = client.get(f"/board/{jetons[a]}").json()
    # Sans nom affiché (nom = début de l'e-mail) : « Mon tableau ».
    assert ecran_a["name"] == "Mon tableau" and len(ecran_a["people"]) == 2
    assert client.get(f"/board/{jetons[b]}").json()["name"] == "Tableau de Bea"
    assert len(client.get(f"/board/{jetons[c]}").json()["people"]) == 1


# --- « Chacun pour soi » : chaque membre choisit ses cases, tableau par tableau ---

def _deux_membres(client, nouveau_compte):
    _, _, h_a, id_a = nouveau_compte()
    email_b, _, h_b, id_b = nouveau_compte()
    tableau = _creer(client, h_a)
    assert _inviter(client, h_a, tableau["id"], email_b).status_code == 200
    assert client.post(f"/boards/{tableau['id']}/accept", headers=h_b).status_code == 200
    return h_a, h_b, tableau["id"], _lien(client, h_a, tableau["id"])


def _moi(client, h, board_id):
    return next(b for b in client.get("/boards", headers=h).json()["boards"] if b["id"] == board_id)


def test_cases_par_defaut_toutes_affichees_puis_masquage_pour_soi_seul(client, nouveau_compte):
    h_a, h_b, board_id, chemin = _deux_membres(client, nouveau_compte)
    cases = _moi(client, h_b, board_id)["myCategories"]
    assert [c["key"] for c in cases] == ["sport", "nutrition", "addictions", "hydratation", "sommeil", "habitudes",
                                         "habitudes_detail"]
    # Toutes les cases affichées, sauf le détail des habitudes (à activer soi-même).
    assert all(c["shown"] for c in cases[:-1]) and not cases[-1]["shown"] and cases[0]["label"] == "Sport"

    avant = client.get(chemin).json()["people"]
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": ["nutrition", "nutrition", "sommeil"]}, headers=h_b)
    assert r.status_code == 200, r.text
    assert {c["key"] for c in r.json()["myCategories"] if not c["shown"]} == {"nutrition", "sommeil"}

    apres = client.get(chemin).json()["people"]
    cats_a = {c["key"] for c in apres[0]["today"]["categories"]}
    cats_b = {c["key"] for c in apres[1]["today"]["categories"]}
    assert "nutrition" in cats_a and "sommeil" in cats_a  # le créateur n'est pas touché
    assert not {"nutrition", "sommeil"} & cats_b
    assert apres[0]["pointsMax"] == avant[0]["pointsMax"]
    assert apres[1]["pointsMax"] == avant[1]["pointsMax"] - 14
    assert len(apres[1]["week"]) == len(avant[1]["week"])
    # Le créateur ne voit pas les cases de l'autre comme les siennes.
    assert all(c["shown"] for c in _moi(client, h_a, board_id)["myCategories"] if c["key"] != "habitudes_detail")


def test_cases_independantes_par_tableau(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    un = _creer(client, h, "Un")["id"]
    deux = _creer(client, h, "Deux")["id"]
    assert client.put(f"/boards/{un}/categories", json={"hidden": ["sport"]}, headers=h).status_code == 200
    assert client.put(f"/boards/{deux}/categories", json={"hidden": ["hydratation"]}, headers=h).status_code == 200
    assert [c["key"] for c in _moi(client, h, un)["myCategories"] if not c["shown"]] == ["sport"]
    assert [c["key"] for c in _moi(client, h, deux)["myCategories"] if not c["shown"]] == ["hydratation"]
    chemin = _lien(client, h, un)
    assert "sport" not in {c["key"] for c in client.get(chemin).json()["people"][0]["today"]["categories"]}


def test_cases_droits_non_membre_et_invite_en_attente(client, nouveau_compte):
    h_a, _, board_id, _ = _deux_membres(client, nouveau_compte)
    _, _, h_x, _ = nouveau_compte()
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport"]}, headers=h_x)
    assert r.status_code == 404 and r.json()["detail"] == "Tableau introuvable."
    email_y, _, h_y, _ = nouveau_compte()
    assert _inviter(client, h_a, board_id, email_y).status_code == 200
    assert client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport"]}, headers=h_y).status_code == 403
    assert client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport"]}).status_code in (401, 403)


def test_cases_cle_inconnue_et_tout_masquer(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    board_id = _creer(client, h)["id"]
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": ["cycle"]}, headers=h)
    assert r.status_code == 400 and "cycle" in r.json()["detail"]
    tout = ["sport", "nutrition", "addictions", "hydratation", "sommeil", "habitudes"]
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": tout}, headers=h)
    assert r.status_code == 400 and "au moins une case" in r.json()["detail"]
    assert all(c["shown"] for c in _moi(client, h, board_id)["myCategories"] if c["key"] != "habitudes_detail")


def test_cases_module_inactif_absent_et_tout_masquer_relatif_aux_modules(client, nouveau_compte_avec_modules):
    _, _, h, _ = nouveau_compte_avec_modules(["sport", "hydratation"])
    board_id = _creer(client, h)["id"]
    assert [c["key"] for c in _moi(client, h, board_id)["myCategories"]] == ["sport", "hydratation"]
    # Les cases des modules actifs sont toutes masquées : refusé, même si d'autres clés valides sont données.
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport", "hydratation"]}, headers=h)
    assert r.status_code == 400
    assert client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport", "sommeil"]}, headers=h).status_code == 200


def test_serie_nulle_quand_le_socle_est_masque(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    board_id = _creer(client, h)["id"]
    chemin = _lien(client, h, board_id)
    assert isinstance(client.get(chemin).json()["people"][0]["streakDays"], int)
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": ["sport", "nutrition", "addictions"]}, headers=h)
    assert r.status_code == 200
    moi = client.get(chemin).json()["people"][0]
    assert moi["streakDays"] is None
    assert {c["key"] for c in moi["today"]["categories"]} == {"hydratation", "sommeil"}


def test_colonne_cases_masquees_apres_migration_0029():
    from sqlalchemy import inspect
    assert "hidden_categories" in {c["name"] for c in inspect(engine).get_columns("board_members")}
