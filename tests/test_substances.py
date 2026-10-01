"""Recatégorisation d'une consommation personnalisée en alcool/tabac.

Un compte créé avant la distinction alcohol/tobacco a pu suivre l'alcool et
le tabac comme des consommations "autre" (category=other) : elles sont alors
invisibles pour les compteurs de streak/économies de l'Accueil, filtrés par
catégorie (voir dashboard_helpers.py). PUT /substances/{id} permet de les
recatégoriser sans perdre leur historique."""


def test_recategorise_autre_en_alcool(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    # Simule un compte où l'alcool a toujours été suivi comme une
    # consommation personnalisée (category=other) : pas de "alcohol"
    # existant à côté -- celui créé par défaut à l'inscription est retiré.
    defaut = next(s for s in client.get("/substances", headers=h).json() if s["category"] == "alcohol")
    assert client.delete(f"/substances/{defaut['id']}", headers=h).status_code == 204

    autre = client.post("/substances", json={"label": "Alcool", "unit": "verre"}, headers=h).json()

    r = client.put(f"/substances/{autre['id']}", json={"category": "alcohol"}, headers=h)
    assert r.status_code == 200, r.text

    substances = client.get("/substances", headers=h).json()
    maj = next(s for s in substances if s["id"] == autre["id"])
    assert maj["category"] == "alcohol"
    assert maj["label"] == "Alcool"  # rien d'autre ne bouge


def test_refuse_deux_substances_alcool(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    # Le compte a déjà un "alcohol" (créé par défaut à l'inscription).
    autre = client.post("/substances", json={"label": "Vin"}, headers=h).json()

    r = client.put(f"/substances/{autre['id']}", json={"category": "alcohol"}, headers=h)
    assert r.status_code == 409


def test_recategorise_avec_categorie_invalide(client, nouveau_compte):
    _, _, h, _ = nouveau_compte()
    autre = client.post("/substances", json={"label": "Test"}, headers=h).json()
    r = client.put(f"/substances/{autre['id']}", json={"category": "whisky"}, headers=h)
    assert r.status_code == 422
