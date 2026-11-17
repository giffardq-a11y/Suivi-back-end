"""Détail des habitudes sur le tableau commun : au choix de chaque membre,
désactivé par défaut ; nom, fait ou non, progression de la semaine."""


def _tableau_avec_lien(client, h):
    r = client.post("/boards", json={"name": "Maison"}, headers=h)
    assert r.status_code == 201, r.text
    board = r.json()
    jeton = client.post(f"/boards/{board['id']}/link", headers=h).json()["token"]
    return board, f"/board/{jeton}"


def _habitude(client, h, **corps):
    r = client.post("/habits", json=corps, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _choisir(client, h, board_id, hidden):
    r = client.put(f"/boards/{board_id}/categories", json={"hidden": hidden}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_desactive_par_defaut_puis_active_par_le_membre(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    _habitude(client, h, label="Méditer", weekly_target=7, note="note-tres-privee")
    board, chemin = _tableau_avec_lien(client, h)

    detail = next(c for c in board["myCategories"] if c["key"] == "habitudes_detail")
    assert detail["shown"] is False and detail["label"] == "Détail des habitudes"
    moi = client.get(chemin).json()["people"][0]
    assert "habits" not in moi  # seul le résumé « Habitudes x / y »

    vu = _choisir(client, h, board["id"], [])  # rien de masqué : détail activé
    assert next(c for c in vu["myCategories"] if c["key"] == "habitudes_detail")["shown"] is True
    r = client.get(chemin)
    assert r.json()["people"][0]["habits"][0]["label"] == "Méditer"
    assert "note-tres-privee" not in r.text  # jamais la note

    vu = _choisir(client, h, board["id"], ["habitudes_detail"])
    assert "habits" not in client.get(chemin).json()["people"][0]


def test_ordre_fait_et_progression(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    lire = _habitude(client, h, label="Lire", weekly_target=7)
    mediter = _habitude(client, h, label="Méditer", weekly_target=7, target="10 min")
    _habitude(client, h, label="Nager", weekly_target=3)  # hebdomadaire, jamais due un jour libre
    course = _habitude(client, h, label="Course", tracking_mode="volume", weekly_volume_target=20.5,
                       session_quantity=5, unit="km")
    assert client.post(f"/habits/{mediter}/log", json={}, headers=h).status_code == 201
    assert client.post(f"/habits/{course}/log", json={"quantity": 2.5}, headers=h).status_code == 201
    board, chemin = _tableau_avec_lien(client, h)
    _choisir(client, h, board["id"], [])

    liste = client.get(chemin).json()["people"][0]["habits"]
    par_nom = {x["label"]: x for x in liste}
    # Prévue non faite d'abord, puis les faites, puis les non prévues.
    assert liste[0]["label"] == "Lire" and liste[-1]["label"] == "Nager"
    assert par_nom["Lire"]["done"] is False and par_nom["Lire"]["progress"] == "0 / 7 sem."
    assert par_nom["Méditer"]["done"] is True and par_nom["Méditer"]["progress"] == "10 min · 1 / 7 sem."
    assert par_nom["Course"]["progress"].endswith("2.5 / 20.5 km")
    # Même progression que l'onglet Habitudes.
    carte = next(x for x in client.get("/habits", headers=h).json() if x["id"] == lire)
    assert carte["done_this_week"] == 0


def test_case_habitudes_masquee_et_plafond(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    for i in range(8):
        _habitude(client, h, label=f"Habitude {i}", weekly_target=7)
    board, chemin = _tableau_avec_lien(client, h)
    _choisir(client, h, board["id"], [])
    moi = client.get(chemin).json()["people"][0]
    assert len(moi["habits"]) == 6 and moi["habitsMore"] == 2

    # Case « habitudes » masquée : pas de détail, même activé.
    _choisir(client, h, board["id"], ["habitudes"])
    moi = client.get(chemin).json()["people"][0]
    assert "habits" not in moi and "habitudes" not in {c["key"] for c in moi["today"]["categories"]}


def test_choix_propre_a_chaque_membre(client, nouveau_compte):
    _, _, h_a, _ = nouveau_compte()
    email_b, _, h_b, _ = nouveau_compte()
    _habitude(client, h_b, label="Yoga", weekly_target=7)
    board, chemin = _tableau_avec_lien(client, h_a)
    client.post(f"/boards/{board['id']}/invite", json={"email": email_b}, headers=h_a)
    client.post(f"/boards/{board['id']}/accept", headers=h_b)

    # Le créateur active son détail : celui de B reste fermé.
    _choisir(client, h_a, board["id"], [])
    a, b = client.get(chemin).json()["people"]
    assert "habits" in a and "habits" not in b
    _choisir(client, h_b, board["id"], [])
    assert client.get(chemin).json()["people"][1]["habits"][0]["label"] == "Yoga"
