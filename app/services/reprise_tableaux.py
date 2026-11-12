"""Reprise des anciens liens de tableau (board_shares) en tableaux communs.

Appelée par la migration 0028, testée à part (tests/test_boards.py). Chaque
ligne board_shares devient un tableau « Tableau de <nom> » (« Mon tableau »
sans nom affiché : un proche repris verrait sinon deux « Mon tableau ») dont
le propriétaire est membre accepté, avec le même hachage de jeton : un écran déjà en favori
continue de fonctionner. Avant, ce lien affichait aussi le proche lié
(partner_links acceptés) quand il avait lui-même créé son lien ; ce proche
devient membre accepté, pour que l'écran garde ses deux colonnes (il avait
déjà donné son accord en créant son lien).

Rejouable : une ligne déjà reprise (boards.legacy_share_id) est ignorée, un
membre déjà présent n'est pas ajouté deux fois.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

NOM = "Mon tableau"


def _nom(conn, user_id: str) -> str:
    """Même règle que services/board.nom_affiche : jamais le début de l'e-mail."""
    ligne = conn.execute(sa.text("SELECT display_name, email FROM users WHERE id = :u"), {"u": user_id}).first()
    if ligne is None:
        return NOM
    nom = (ligne[0] or "").strip()
    if not nom or nom.lower() == (ligne[1] or "").split("@")[0].lower():
        return NOM
    return f"Tableau de {nom}"[:40]


def _membre(conn, board_id: str, user_id: str, quand) -> None:
    deja = conn.execute(
        sa.text("SELECT 1 FROM board_members WHERE board_id = :b AND user_id = :u"), {"b": board_id, "u": user_id},
    ).first()
    if deja is None:
        conn.execute(sa.text(
            "INSERT INTO board_members (id, board_id, user_id, status, invited_by, created_at, accepted_at) "
            "VALUES (:id, :b, :u, 'accepted', NULL, :q, :q)"
        ), {"id": str(uuid.uuid4()), "b": board_id, "u": user_id, "q": quand})


def reprendre(conn) -> int:
    """Renvoie le nombre de tableaux créés."""
    maintenant = datetime.now(timezone.utc)
    crees = 0
    tableau_de: dict[str, str] = {}  # user_id -> board_id repris
    for share_id, user_id, token_hash, created_at, last_read_at in conn.execute(sa.text(
            "SELECT id, user_id, token_hash, created_at, last_read_at FROM board_shares")).all():
        existant = conn.execute(
            sa.text("SELECT id FROM boards WHERE legacy_share_id = :s OR token_hash = :t"), {"s": share_id, "t": token_hash},
        ).first()
        if existant is not None:
            tableau_de[user_id] = existant[0]
            continue
        board_id = str(uuid.uuid4())
        conn.execute(sa.text(
            "INSERT INTO boards (id, name, owner_id, token_hash, link_created_at, last_read_at, legacy_share_id, created_at) "
            "VALUES (:id, :n, :o, :t, :c, :l, :s, :m)"
        ), {"id": board_id, "n": _nom(conn, user_id), "o": user_id, "t": token_hash, "c": created_at or maintenant,
            "l": last_read_at, "s": share_id, "m": maintenant})
        _membre(conn, board_id, user_id, maintenant)
        tableau_de[user_id] = board_id
        crees += 1

    for a, b in conn.execute(sa.text(
            "SELECT requester_id, recipient_id FROM partner_links WHERE status = 'accepted'")).all():
        if a in tableau_de and b in tableau_de:
            _membre(conn, tableau_de[a], b, maintenant)
            _membre(conn, tableau_de[b], a, maintenant)
    return crees
