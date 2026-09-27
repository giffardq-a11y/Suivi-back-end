"""Suppression de compte (depuis l'app et depuis le web) et page de
réinitialisation du mot de passe.

Google Play exige les deux chemins de suppression : un bouton dans l'app, et
une page web publique pour qui n'a plus l'app. La page web ne supprime rien
sur la seule saisie d'une adresse : elle envoie un lien de confirmation à
usage unique (30 min) à cette adresse, et répond la même chose que le compte
existe ou non.

Pages en HTML autonome (pas de script externe), servies par le backend :
    /compte/suppression                 demande
    /compte/suppression/confirmer       confirmation (lien reçu par e-mail)
    /compte/mot-de-passe                nouveau mot de passe (lien reçu par e-mail)
"""
import html
import logging
import os

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..security import hash_password, verify_password
from ..services.compte import consommer_jeton, creer_jeton, supprimer_utilisateur
from ..services.email import envoyer_email

router = APIRouter(tags=["compte"])
log = logging.getLogger("suivi.compte")

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")


@router.delete("/me", status_code=204)
def delete_me(payload: schemas.DeleteAccountRequest, db: Session = Depends(get_db),
              user: models.User = Depends(get_current_user)):
    """Supprime le compte et toutes ses données. Le mot de passe est redemandé :
    un téléphone déverrouillé ne doit pas suffire à tout effacer."""
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Mot de passe incorrect.")
    compte = supprimer_utilisateur(db, user.id)
    log.info("Compte supprimé depuis l'app : %s lignes", sum(compte.values()))


# ---------- Pages web ----------

STYLE = """
:root{--bg:#f5ead8;--card:#fff;--text:#201e1d;--muted:#6b6255;--accent:#9c5424;--danger:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#0d0c12;--card:#1e1a26;--text:#f2f0f5;--muted:#9491a0;--accent:#ff8a2d;--danger:#ff6b5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}
main{max-width:480px;margin:0 auto;padding:32px 16px}h1{font-size:24px;margin:0 0 16px}
.card{background:var(--card);border-radius:16px;padding:20px}p{margin:0 0 12px}.muted{color:var(--muted);font-size:14px}
label{display:block;font-weight:600;margin:12px 0 4px}input{width:100%;padding:12px;border-radius:10px;border:1px solid var(--muted);font:inherit;background:transparent;color:var(--text)}
button{margin-top:16px;width:100%;padding:12px;border:0;border-radius:999px;background:var(--accent);color:#fff;font:600 16px system-ui}
button.danger{background:var(--danger)}ul{padding-left:20px}
"""


def _page(titre: str, corps: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(titre)} · Suivi</title><style>{STYLE}</style></head>
<body><main><h1>{html.escape(titre)}</h1><div class="card">{corps}</div></main></body></html>""")


CE_QUI_EST_SUPPRIME = """<ul class="muted">
<li>ton compte et ton profil (poids, objectifs, réglages) ;</li>
<li>consommations, habitudes, journal, cycle, repas, plan et stock alimentaire ;</li>
<li>séances de sport, cartes de révision, partages avec un proche ;</li>
<li>connexions aux agendas et à Health Connect.</li></ul>
<p class="muted">La suppression est définitive et immédiate. Rien n'est conservé.</p>"""


@router.get("/compte/suppression", response_class=HTMLResponse)
def page_demande_suppression():
    return _page("Supprimer mon compte Suivi", f"""
<p>Indique l'adresse e-mail de ton compte. Tu recevras un lien de confirmation
(valable 30 minutes) : rien n'est supprimé avant que tu aies cliqué dessus.</p>
<p>Tu peux aussi supprimer ton compte directement dans l'app : Paramètres → Supprimer mon compte.</p>
{CE_QUI_EST_SUPPRIME}
<form method="post" action="/compte/suppression">
<label for="email">Adresse e-mail</label>
<input id="email" name="email" type="email" required autocomplete="email">
<button type="submit">Recevoir le lien de confirmation</button></form>""")


@router.post("/compte/suppression", response_class=HTMLResponse)
def demande_suppression(email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email.strip().lower()).first() \
        or db.query(models.User).filter(models.User.email == email.strip()).first()
    if user is not None:
        jeton = creer_jeton(db, user, "delete_account")
        if jeton is not None:
            lien = f"{BACKEND_BASE_URL}/compte/suppression/confirmer?token={jeton}"
            try:
                envoyer_email(
                    user.email, "Suivi : confirmer la suppression de ton compte",
                    "Bonjour,\n\nTu as demandé la suppression de ton compte Suivi et de toutes ses données.\n"
                    f"Pour confirmer, ouvre ce lien (valable 30 minutes, une seule fois) :\n{lien}\n\n"
                    "Si tu n'as rien demandé, ignore ce message : ton compte reste intact.\n",
                )
            except Exception:
                log.exception("Échec d'envoi du lien de suppression")
    # Même réponse que le compte existe ou non.
    return _page("Vérifie ta boîte mail", """
<p>Si un compte existe avec cette adresse, un e-mail vient de partir avec un lien de confirmation.</p>
<p class="muted">Pense à regarder dans les indésirables. Le lien expire dans 30 minutes.</p>""")


@router.get("/compte/suppression/confirmer", response_class=HTMLResponse)
def page_confirmer_suppression(token: str = "", db: Session = Depends(get_db)):
    if consommer_jeton(db, token, "delete_account", marquer=False) is None:
        return _page("Lien expiré", "<p>Ce lien n'est plus valable. Refais une demande depuis la page de suppression.</p>")
    return _page("Confirmer la suppression", f"""
{CE_QUI_EST_SUPPRIME}
<form method="post" action="/compte/suppression/confirmer">
<input type="hidden" name="token" value="{html.escape(token)}">
<button type="submit" class="danger">Supprimer définitivement mon compte</button></form>""")


@router.post("/compte/suppression/confirmer", response_class=HTMLResponse)
def confirmer_suppression(token: str = Form(...), db: Session = Depends(get_db)):
    user = consommer_jeton(db, token, "delete_account")
    if user is None:
        return _page("Lien expiré", "<p>Ce lien n'est plus valable. Refais une demande depuis la page de suppression.</p>")
    compte = supprimer_utilisateur(db, user.id)
    log.info("Compte supprimé depuis le web : %s lignes", sum(compte.values()))
    return _page("Compte supprimé", "<p>Ton compte et toutes ses données ont été supprimés.</p>")


@router.get("/compte/mot-de-passe", response_class=HTMLResponse)
def page_mot_de_passe(token: str = "", db: Session = Depends(get_db)):
    if consommer_jeton(db, token, "reset_password", marquer=False) is None:
        return _page("Lien expiré", "<p>Ce lien n'est plus valable. Refais une demande depuis l'app : "
                                    "écran de connexion → Mot de passe oublié.</p>")
    return _page("Nouveau mot de passe", f"""
<form method="post" action="/compte/mot-de-passe">
<input type="hidden" name="token" value="{html.escape(token)}">
<label for="p1">Nouveau mot de passe (8 caractères minimum)</label>
<input id="p1" name="password" type="password" minlength="8" required autocomplete="new-password">
<label for="p2">Confirme-le</label>
<input id="p2" name="confirmation" type="password" minlength="8" required autocomplete="new-password">
<button type="submit">Enregistrer</button></form>""")


@router.post("/compte/mot-de-passe", response_class=HTMLResponse)
def enregistrer_mot_de_passe(token: str = Form(...), password: str = Form(...),
                             confirmation: str = Form(...), db: Session = Depends(get_db)):
    if len(password) < 8 or password != confirmation:
        return _page("Nouveau mot de passe", "<p>Les deux mots de passe doivent être identiques et faire au moins "
                                             "8 caractères.</p><p><a href=\"javascript:history.back()\">Revenir</a></p>")
    user = consommer_jeton(db, token, "reset_password")
    if user is None:
        return _page("Lien expiré", "<p>Ce lien n'est plus valable. Refais une demande depuis l'app.</p>")
    user.password_hash = hash_password(password)
    db.commit()
    return _page("Mot de passe changé", "<p>C'est fait : reconnecte-toi dans l'app avec ton nouveau mot de passe.</p>")
