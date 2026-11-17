"""Tableau commun, lecture publique pour un écran (TV du salon, PC).

- GET /board/{jeton} (public) renvoie le nom du tableau et l'état de chacun de
  ses membres acceptés, le créateur d'abord.

Les tableaux, leurs membres et leur lien se gèrent dans routers/boards.py ;
la page qui affiche ce JSON est /tableau#jeton (routers/tableau.py).

Le lien public ne donne que des données agrégées (catégories du jour : sport,
nutrition, alcool et tabac, hydratation, sommeil, habitudes ; points ; série),
jamais l'e-mail ni le détail des consommations ou des repas. N'apparaissent que
les membres qui ont accepté l'invitation à ce tableau : être lié comme
« proche » (routers/partner.py) ne suffit pas.

Chaque membre choisit, pour ce tableau, lesquelles de ses cases s'affichent
(PUT /boards/{id}/categories, routers/boards.py) : les cases masquées n'entrent
ni dans les catégories, ni dans les points, ni dans la semaine, ni dans la
série. Sans case du socle affichée, « streakDays » vaut null.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services import board, limite
from ..services.common import now_utc, to_ms

router = APIRouter(prefix="/board", tags=["board"])

LECTURE_PAR_IP = (240, 15 * 60)  # la page /tableau relit toutes les 30 min : très loin de la limite


@router.get("/{jeton}")
def lire_tableau(jeton: str, request: Request, response: Response, db: Session = Depends(get_db)):
    limite.verifier(f"board:{limite.ip_client(request)}", *LECTURE_PAR_IP)
    tableau = db.query(models.Board).filter(models.Board.token_hash == board.hacher_jeton(jeton)).first()
    if tableau is None:
        raise HTTPException(status_code=404, detail="Lien de tableau inconnu ou désactivé.")

    membres = (db.query(models.BoardMember)
               .filter(models.BoardMember.board_id == tableau.id, models.BoardMember.status == "accepted")
               .order_by(models.BoardMember.accepted_at.asc()).all())
    membres = sorted(membres, key=lambda m: m.user_id != tableau.owner_id)  # le créateur d'abord (tri stable)
    personnes = []
    for membre in membres:
        personne = db.query(models.User).filter(models.User.id == membre.user_id).first()
        if personne is not None:
            personnes.append(board.etat_personne(db, personne, masquees=frozenset(membre.hidden_categories or []),
                                                 detail_habitudes=bool(membre.show_habit_details)))

    tableau.last_read_at = now_utc()
    db.commit()

    # Lu par une page hors navigateur classique (appli TV) : pas de cookie ni
    # d'en-tête d'autorisation en jeu, le jeton est dans l'adresse.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-store"
    return {"generatedAt": to_ms(now_utc()), "name": tableau.name, "people": personnes}
