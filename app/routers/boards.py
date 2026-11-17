"""Tableaux communs : créer un tableau, y inviter des proches, gérer son lien
d'écran. Séparé de « Mon proche » (routers/partner.py), qui ne sert qu'à
partager ses progrès avec une personne.

- GET    /boards                          mes tableaux et les invitations reçues
- POST   /boards                          créer un tableau {name}
- DELETE /boards/{id}                     supprimer (créateur)
- POST   /boards/{id}/invite              inviter un compte Tanren par e-mail (créateur)
- POST   /boards/{id}/accept              accepter une invitation (invité)
- DELETE /boards/{id}/members/{membre}    retirer (créateur), quitter ou refuser (soi-même)
- POST   /boards/{id}/link                créer ou remplacer le lien d'écran (créateur) :
                                          le jeton n'est renvoyé qu'ici, une seule fois
- DELETE /boards/{id}/link                couper le lien (créateur)
- PUT    /boards/{id}/categories          choisir MES cases affichées sur ce tableau
                                          {hidden: [clés]} (membre accepté, pour
                                          lui seul : personne ne règle les cases d'un autre)

Le lien s'ouvre sur /tableau#jeton (routers/tableau.py), qui lit
GET /board/{jeton} (routers/board.py). Seuls les membres acceptés y
apparaissent : accepter l'invitation vaut accord pour s'afficher sur l'écran
de ce tableau. Les invitations en attente ne sont visibles que du créateur et
de l'invité ; l'e-mail d'un membre n'est montré qu'au créateur, pour ses
invitations en attente (il l'a saisi lui-même).
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import limite
from ..services.board import LIBELLES, categories_actives, hacher_jeton, nom_affiche
from ..services.common import now_utc, to_ms

router = APIRouter(prefix="/boards", tags=["board"])

MAX_PERSONNES = 6           # créateur et invitations en attente compris : lisible sur une TV
MAX_TABLEAUX = 10           # par créateur
LONGUEUR_NOM = 40
INVITATIONS_PAR_COMPTE = (30, 60 * 60)
# Case à part de « Ce que j'affiche » : le détail des habitudes (nom, fait ou
# non, progression), désactivé par défaut et réglé par le membre lui-même.
# Stocké dans board_members.show_habit_details, pas dans hidden_categories.
DETAIL_HABITUDES = "habitudes_detail"
LIBELLE_DETAIL_HABITUDES = "Détail des habitudes"


class CorpsTableau(BaseModel):
    name: str


class CorpsInvitation(BaseModel):
    email: str


class CorpsCases(BaseModel):
    hidden: list[str]


def _tableau(db: Session, board_id: str) -> models.Board:
    tableau = db.query(models.Board).filter(models.Board.id == board_id).first()
    if tableau is None:
        raise HTTPException(status_code=404, detail="Tableau introuvable.")
    return tableau


def _membres(db: Session, board_id: str) -> list[models.BoardMember]:
    return (db.query(models.BoardMember).filter(models.BoardMember.board_id == board_id)
            .order_by(models.BoardMember.created_at.asc()).all())


def _mon_appartenance(db: Session, board_id: str, user_id: str) -> models.BoardMember | None:
    return db.query(models.BoardMember).filter(
        models.BoardMember.board_id == board_id, models.BoardMember.user_id == user_id).first()


def _du_createur(db: Session, board_id: str, user: models.User) -> models.Board:
    tableau = _tableau(db, board_id)
    if tableau.owner_id != user.id:
        # Même réponse qu'un tableau inconnu pour qui n'en est pas membre.
        if _mon_appartenance(db, board_id, user.id) is None:
            raise HTTPException(status_code=404, detail="Tableau introuvable.")
        raise HTTPException(status_code=403, detail="Seul le créateur du tableau peut faire cela.")
    return tableau


def _decrire(db: Session, tableau: models.Board, user: models.User) -> dict:
    createur = tableau.owner_id == user.id
    membres = []
    for m in _membres(db, tableau.id):
        if m.status != "accepted" and not createur:
            continue
        personne = db.query(models.User).filter(models.User.id == m.user_id).first()
        if personne is None:
            continue
        ligne = {
            "id": m.id, "name": nom_affiche(personne), "status": m.status,
            "isOwner": m.user_id == tableau.owner_id, "isMe": m.user_id == user.id,
        }
        if createur and m.status == "pending":
            ligne["email"] = personne.email
        membres.append(ligne)
    mon = _mon_appartenance(db, tableau.id, user.id)
    cachees = set(mon.hidden_categories or []) if mon is not None and mon.status == "accepted" else set()
    mes_cases = [
        {"key": cle, "label": LIBELLES[cle], "shown": cle not in cachees}
        for cle in categories_actives(user)
    ] if mon is not None and mon.status == "accepted" else []
    if mes_cases and "habitudes" in categories_actives(user):
        mes_cases.append({"key": DETAIL_HABITUDES, "label": LIBELLE_DETAIL_HABITUDES,
                          "shown": bool(mon.show_habit_details)})
    return {
        "id": tableau.id, "name": tableau.name, "isOwner": createur, "members": membres,
        "myCategories": mes_cases,
        "link": {"enabled": tableau.token_hash is not None, "createdAt": to_ms(tableau.link_created_at),
                 "lastReadAt": to_ms(tableau.last_read_at)},
    }


@router.get("")
def lister(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    tableaux, invitations = [], []
    lignes = (db.query(models.BoardMember, models.Board)
              .join(models.Board, models.Board.id == models.BoardMember.board_id)
              .filter(models.BoardMember.user_id == user.id)
              .order_by(models.Board.created_at.asc()).all())
    for membre, tableau in lignes:
        if membre.status == "accepted":
            tableaux.append(_decrire(db, tableau, user))
        else:
            createur = db.query(models.User).filter(models.User.id == tableau.owner_id).first()
            invitations.append({
                "boardId": tableau.id, "memberId": membre.id, "name": tableau.name,
                "ownerName": nom_affiche(createur) if createur else None,
            })
    return {"boards": tableaux, "invitations": invitations}


@router.post("", status_code=201)
def creer(corps: CorpsTableau, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    nom = corps.name.strip()
    if not nom or len(nom) > LONGUEUR_NOM:
        raise HTTPException(status_code=400, detail=f"Donne un nom de 1 à {LONGUEUR_NOM} caractères.")
    if db.query(models.Board).filter(models.Board.owner_id == user.id).count() >= MAX_TABLEAUX:
        raise HTTPException(status_code=400, detail=f"{MAX_TABLEAUX} tableaux au plus.")
    tableau = models.Board(name=nom, owner_id=user.id, created_at=now_utc())
    db.add(tableau)
    db.flush()
    db.add(models.BoardMember(board_id=tableau.id, user_id=user.id, status="accepted",
                              created_at=now_utc(), accepted_at=now_utc()))
    db.commit()
    return _decrire(db, tableau, user)


@router.delete("/{board_id}", status_code=204)
def supprimer(board_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    tableau = _du_createur(db, board_id, user)
    db.query(models.BoardMember).filter(models.BoardMember.board_id == tableau.id).delete()
    db.delete(tableau)
    db.commit()
    return Response(status_code=204)


@router.post("/{board_id}/invite")
def inviter(board_id: str, corps: CorpsInvitation, db: Session = Depends(get_db),
            user: models.User = Depends(get_current_user)):
    limite.verifier(f"boards-invite:{user.id}", *INVITATIONS_PAR_COMPTE)
    tableau = _du_createur(db, board_id, user)
    email = corps.email.strip().lower()
    if email == user.email.lower():
        raise HTTPException(status_code=400, detail="Tu fais déjà partie de ce tableau.")
    cible = db.query(models.User).filter(models.User.email == email).first()
    if cible is None:
        raise HTTPException(status_code=404, detail="Aucun compte Tanren n’est associé à cet email.")
    if _mon_appartenance(db, tableau.id, cible.id) is not None:
        return _decrire(db, tableau, user)  # déjà invité ou membre : rien à faire
    if len(_membres(db, tableau.id)) >= MAX_PERSONNES:
        raise HTTPException(status_code=400, detail=f"{MAX_PERSONNES} personnes au plus par tableau.")
    db.add(models.BoardMember(board_id=tableau.id, user_id=cible.id, status="pending",
                              invited_by=user.id, created_at=now_utc()))
    db.commit()
    return _decrire(db, tableau, user)


@router.post("/{board_id}/accept")
def accepter(board_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    membre = _mon_appartenance(db, board_id, user.id)
    if membre is None:
        raise HTTPException(status_code=404, detail="Invitation introuvable.")
    if membre.status != "accepted":
        membre.status = "accepted"
        membre.accepted_at = now_utc()
        db.commit()
    return _decrire(db, _tableau(db, board_id), user)


@router.delete("/{board_id}/members/{member_id}", status_code=204)
def retirer(board_id: str, member_id: str, db: Session = Depends(get_db),
            user: models.User = Depends(get_current_user)):
    tableau = _tableau(db, board_id)
    membre = db.query(models.BoardMember).filter(
        models.BoardMember.id == member_id, models.BoardMember.board_id == tableau.id).first()
    if membre is None or (membre.user_id != user.id and tableau.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    if membre.user_id == tableau.owner_id:
        raise HTTPException(status_code=400, detail="Le créateur ne peut pas quitter son tableau : supprime-le.")
    db.delete(membre)
    db.commit()
    return Response(status_code=204)


@router.post("/{board_id}/link", status_code=201)
def creer_lien(board_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    tableau = _du_createur(db, board_id, user)
    jeton = secrets.token_urlsafe(32)
    # Remplacement : l'ancien lien cesse de fonctionner tout de suite.
    tableau.token_hash = hacher_jeton(jeton)
    tableau.link_created_at = now_utc()
    tableau.last_read_at = None
    db.commit()
    return {"token": jeton}


@router.delete("/{board_id}/link", status_code=204)
def couper_lien(board_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    tableau = _du_createur(db, board_id, user)
    tableau.token_hash = None
    tableau.link_created_at = None
    tableau.last_read_at = None
    db.commit()
    return Response(status_code=204)


@router.put("/{board_id}/categories")
def choisir_mes_cases(board_id: str, corps: CorpsCases, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    """Remplace la liste des cases que l'appelant masque sur ce tableau. Il n'y
    a aucune route pour régler les cases d'un autre membre, pas même pour le créateur."""
    tableau = _tableau(db, board_id)
    membre = _mon_appartenance(db, board_id, user.id)
    if membre is None:
        raise HTTPException(status_code=404, detail="Tableau introuvable.")
    if membre.status != "accepted":
        raise HTTPException(status_code=403, detail="Accepte d'abord l'invitation à ce tableau.")
    inconnues = sorted(set(corps.hidden) - set(LIBELLES) - {DETAIL_HABITUDES})
    if inconnues:
        raise HTTPException(status_code=400, detail=f"Case inconnue : {', '.join(inconnues)}.")
    # Doublons retirés, ordre gardé ; le détail des habitudes n'est pas une case du calcul.
    masquees = [cle for cle in dict.fromkeys(corps.hidden) if cle != DETAIL_HABITUDES]
    if not [cle for cle in categories_actives(user) if cle not in masquees]:
        raise HTTPException(status_code=400, detail="Garde au moins une case affichée, ou quitte le tableau.")
    membre.hidden_categories = masquees
    membre.show_habit_details = DETAIL_HABITUDES not in corps.hidden
    db.commit()
    return _decrire(db, tableau, user)
