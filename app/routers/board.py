"""Tableau partagé : un lien en lecture seule pour un écran (TV du salon).

- POST   /board/share   (connecté) crée le lien ou le remplace ; le jeton
                        n'est renvoyé qu'ici, une seule fois.
- GET    /board/share   (connecté) dit si un lien est actif.
- DELETE /board/share   (connecté) coupe l'accès.
- GET    /board/{jeton} (public) renvoie l'état du tableau.

Le lien public ne donne que des données agrégées (catégories du jour : sport,
nutrition, alcool et tabac, hydratation, sommeil, habitudes ; points ; pesées), jamais l'e-mail ni le détail des consommations ou des repas. Le
proche lié (voir routers/partner.py) n'apparaît sur le tableau que s'il a
lui-même activé un lien de partage : accepter un lien « proche » ne vaut pas
accord pour un affichage sans connexion.
"""
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services import board, limite
from ..services.common import now_utc, to_ms

router = APIRouter(prefix="/board", tags=["board"])

LECTURE_PAR_IP = (240, 15 * 60)  # la page /tableau relit toutes les 30 min : très loin de la limite


def _hacher(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _partage(db: Session, user_id: str) -> models.BoardShare | None:
    return db.query(models.BoardShare).filter(models.BoardShare.user_id == user_id).first()


@router.post("/share", status_code=201)
def creer_partage(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    jeton = secrets.token_urlsafe(32)
    ligne = _partage(db, user.id)
    if ligne is None:
        ligne = models.BoardShare(user_id=user.id, token_hash=_hacher(jeton), created_at=now_utc())
        db.add(ligne)
    else:
        # Remplacement : l'ancien lien cesse de fonctionner tout de suite.
        ligne.token_hash = _hacher(jeton)
        ligne.created_at = now_utc()
        ligne.last_read_at = None
    db.commit()
    return {"token": jeton, "path": f"/board/{jeton}"}


@router.get("/share")
def lire_partage(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    ligne = _partage(db, user.id)
    if ligne is None:
        return {"enabled": False, "createdAt": None, "lastReadAt": None}
    return {"enabled": True, "createdAt": to_ms(ligne.created_at), "lastReadAt": to_ms(ligne.last_read_at)}


@router.delete("/share", status_code=204)
def supprimer_partage(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    ligne = _partage(db, user.id)
    if ligne is not None:
        db.delete(ligne)
        db.commit()
    return Response(status_code=204)


@router.get("/{jeton}")
def lire_tableau(jeton: str, request: Request, response: Response, db: Session = Depends(get_db)):
    limite.verifier(f"board:{limite.ip_client(request)}", *LECTURE_PAR_IP)
    ligne = db.query(models.BoardShare).filter(models.BoardShare.token_hash == _hacher(jeton)).first()
    if ligne is None:
        raise HTTPException(status_code=404, detail="Lien de tableau inconnu ou désactivé.")
    proprietaire = db.query(models.User).filter(models.User.id == ligne.user_id).first()
    if proprietaire is None:
        raise HTTPException(status_code=404, detail="Lien de tableau inconnu ou désactivé.")

    personnes = [board.etat_personne(db, proprietaire)]
    lien = (
        db.query(models.PartnerLink)
        .filter(
            or_(models.PartnerLink.requester_id == proprietaire.id, models.PartnerLink.recipient_id == proprietaire.id),
            models.PartnerLink.status == "accepted",
        )
        .first()
    )
    if lien is not None:
        autre_id = lien.recipient_id if lien.requester_id == proprietaire.id else lien.requester_id
        if _partage(db, autre_id) is not None:
            autre = db.query(models.User).filter(models.User.id == autre_id).first()
            if autre is not None:
                personnes.append(board.etat_personne(db, autre))

    ligne.last_read_at = now_utc()
    db.commit()

    # Lu par une page hors navigateur classique (appli TV) : pas de cookie ni
    # d'en-tête d'autorisation en jeu, le jeton est dans l'adresse.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-store"
    return {"generatedAt": to_ms(now_utc()), "people": personnes}
