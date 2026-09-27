"""Suppression de compte : aucune ligne de l'utilisateur ne doit survivre,
dans aucune table, et les données des autres comptes restent intactes.

Le remplissage est générique : une ligne par table (colonnes obligatoires
remplies selon leur type, clés étrangères chaînées), pour chaque utilisateur.
Une table ajoutée plus tard est donc couverte sans toucher à ce test.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from app.database import Base, SessionLocal
from app.services.compte import _condition, tables_orphelines


def _valeur(colonne):
    t = colonne.type
    if isinstance(t, sa.Enum):
        return list(t.enum_class)[0] if t.enum_class else t.enums[0]
    if isinstance(t, sa.Boolean):
        return False
    if isinstance(t, (sa.Integer, sa.Float)):
        return 1
    if isinstance(t, sa.DateTime):
        return datetime.now(timezone.utc)
    if isinstance(t, sa.Date):
        return datetime.now(timezone.utc).date()
    if isinstance(t, sa.JSON):
        return []
    return f"test-{uuid.uuid4()}"


def _remplir(db, user_id: str) -> None:
    ids: dict[str, str] = {"users": user_id}
    for table in Base.metadata.sorted_tables:
        if table.name == "users":
            continue
        ligne = {}
        for col in table.columns:
            fk = next(iter(col.foreign_keys), None)
            if fk is not None:
                ligne[col.name] = ids.get(fk.column.table.name)
            elif col.primary_key or (not col.nullable and col.default is None and col.server_default is None):
                ligne[col.name] = _valeur(col)
        db.execute(table.insert().values(**ligne))
        ids[table.name] = ligne.get("id")
    db.commit()


def _lignes_de(db, user_id: str) -> dict[str, int]:
    conditions: dict = {}
    resultat = {}
    for table in Base.metadata.sorted_tables:
        cond = (table.c.id == user_id) if table.name == "users" else _condition(table, user_id, conditions)
        if cond is not None:
            n = db.execute(sa.select(sa.func.count()).select_from(table).where(cond)).scalar()
            if n:
                resultat[table.name] = n
    return resultat


def test_toute_table_liee_aux_utilisateurs_est_couverte():
    assert tables_orphelines() == []


def test_delete_me_supprime_tout_et_rien_d_autre(client, nouveau_compte):
    email_a, mdp_a, h_a, id_a = nouveau_compte()
    _, _, _, id_b = nouveau_compte()
    db = SessionLocal()
    _remplir(db, id_a)
    _remplir(db, id_b)
    avant_b = _lignes_de(db, id_b)
    tables_liees = {t.name for t in Base.metadata.sorted_tables if t.foreign_keys} | {"users"}
    assert set(_lignes_de(db, id_a)) == tables_liees

    assert client.request("DELETE", "/me", json={"password": "faux"}, headers=h_a).status_code == 403
    assert client.request("DELETE", "/me", json={"password": mdp_a}, headers=h_a).status_code == 204

    db.expire_all()
    assert _lignes_de(db, id_a) == {}
    assert _lignes_de(db, id_b) == avant_b
    db.close()
    # Le jeton d'accès encore en circulation ne donne plus accès à rien.
    assert client.get("/diet/pantry", headers=h_a).status_code == 401
    assert client.post("/auth/login", json={"email": email_a, "password": mdp_a}).status_code == 401


def test_suppression_par_la_page_web(client, nouveau_compte, emails):
    email, mdp, h, _ = nouveau_compte()
    page = client.get("/compte/suppression")
    assert page.status_code == 200 and "Supprimer mon compte" in page.text

    # Réponse identique pour une adresse inconnue, et aucun e-mail envoyé.
    inconnu = client.post("/compte/suppression", data={"email": "personne@example.com"})
    connu = client.post("/compte/suppression", data={"email": email})
    assert inconnu.text == connu.text
    assert len(emails) == 1 and emails[0]["to"] == email

    jeton = emails[0]["texte"].split("token=")[1].split()[0]
    assert "Supprimer définitivement" in client.get(f"/compte/suppression/confirmer?token={jeton}").text
    # Ouvrir le lien ne supprime rien : il faut confirmer.
    assert client.get("/diet/pantry", headers=h).status_code == 200

    fin = client.post("/compte/suppression/confirmer", data={"token": jeton})
    assert "Compte supprimé" in fin.text
    assert client.post("/auth/login", json={"email": email, "password": mdp}).status_code == 401
    # Jeton à usage unique.
    assert "Lien expiré" in client.post("/compte/suppression/confirmer", data={"token": jeton}).text
