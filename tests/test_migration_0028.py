"""Migration 0028 jouée pour de vrai (Alembic) sur une base arrêtée en 0027
qui contient déjà des liens board_shares et un lien « proche »."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = r'''
import datetime, hashlib, json, uuid
import sqlalchemy as sa
from alembic import command
from app.migrate import _alembic_config
from app.database import engine

cfg = _alembic_config()
command.upgrade(cfg, "0027")
now = datetime.datetime.now(datetime.timezone.utc)
with engine.begin() as c:
    obligatoires = [r for r in c.execute(sa.text("PRAGMA table_info(users)")).all()
                    if r[3] and r[4] is None and r[1] not in ("id", "email")]
    for u in ("ua", "ub"):
        valeurs = {}
        for r in obligatoires:
            t = str(r[2]).upper()
            valeurs[r[1]] = ("UTC" if r[1] == "timezone" else 0 if ("INT" in t or "BOOL" in t)
                             else "[]" if "JSON" in t else now if "DATE" in t else "x")
        noms = ",".join(["id", "email", *valeurs])
        params = ",".join([":id", ":email", *(":" + k for k in valeurs)])
        c.execute(sa.text(f"INSERT INTO users ({noms}) VALUES ({params})"), {"id": u, "email": u + "@ex.com", **valeurs})
        c.execute(sa.text("INSERT INTO board_shares (id, user_id, token_hash, created_at) VALUES (:i, :u, :t, :n)"),
                  {"i": str(uuid.uuid4()), "u": u, "t": hashlib.sha256(("jeton-" + u).encode()).hexdigest(), "n": now})
    c.execute(sa.text("INSERT INTO partner_links (id, requester_id, recipient_id, status, scopes, created_at) "
                      "VALUES ('pl', 'ua', 'ub', 'accepted', '[]', :n)"), {"n": now})
command.upgrade(cfg, "head")
command.upgrade(cfg, "head")  # rejouer ne change rien
with engine.begin() as c:
    print(json.dumps({
        "boards": c.execute(sa.text("SELECT count(*) FROM boards WHERE token_hash IS NOT NULL")).scalar(),
        "membres": c.execute(sa.text("SELECT count(*) FROM board_members WHERE status = 'accepted'")).scalar(),
        "jeton": c.execute(sa.text("SELECT count(*) FROM boards WHERE token_hash = :t"),
                           {"t": hashlib.sha256(b"jeton-ua").hexdigest()}).scalar(),
    }))
'''


def test_montee_0027_vers_0028_avec_des_liens():
    racine = Path(__file__).resolve().parent.parent
    base = Path(tempfile.mkdtemp(prefix="suivi-mig-")) / "m.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{base}", "PYTHONPATH": str(racine)}
    r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=racine, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    import json
    resultat = json.loads(r.stdout.strip().splitlines()[-1])
    # Deux tableaux repris avec leur jeton, chacun avec les deux proches.
    assert resultat == {"boards": 2, "membres": 4, "jeton": 1}
