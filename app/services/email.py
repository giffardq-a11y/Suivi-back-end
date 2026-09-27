"""Envoi d'e-mails transactionnels (mot de passe oublié, suppression de compte).

Fournisseur choisi par variable d'environnement, sans toucher au code :

    EMAIL_PROVIDER   brevo | resend | console (défaut : console)
    EMAIL_API_KEY    clé API du fournisseur
    EMAIL_FROM       adresse d'expédition (vérifiée chez le fournisseur)
    EMAIL_FROM_NAME  nom affiché (défaut : Tanren)

- Brevo : envoi possible depuis une adresse simplement vérifiée, sans nom de
  domaine à soi ; offre gratuite 300 e-mails/jour ; serveurs en UE.
- Resend : exige un nom de domaine vérifié (DNS) pour écrire à n'importe qui.
- console : n'envoie rien, écrit le message dans le log — pour le
  développement local. Sur Render (RENDER=true), refuse de faire semblant :
  un lien de réinitialisation qui ne part nulle part est une panne silencieuse.
"""
import logging
import os

import httpx

log = logging.getLogger("suivi.email")


class EmailNonConfigure(RuntimeError):
    pass


def envoyer_email(destinataire: str, sujet: str, texte: str, html: str | None = None) -> None:
    fournisseur = os.environ.get("EMAIL_PROVIDER", "console").lower()
    cle = os.environ.get("EMAIL_API_KEY", "")
    expediteur = os.environ.get("EMAIL_FROM", "")
    nom = os.environ.get("EMAIL_FROM_NAME", "Tanren")

    if fournisseur == "console":
        if os.environ.get("RENDER"):
            raise EmailNonConfigure("EMAIL_PROVIDER non configuré sur le serveur.")
        log.warning("E-MAIL (non envoyé, EMAIL_PROVIDER=console) à %s — %s\n%s", destinataire, sujet, texte)
        print(f"\n=== E-MAIL à {destinataire} : {sujet}\n{texte}\n===\n", flush=True)
        return
    if not cle or not expediteur:
        raise EmailNonConfigure("EMAIL_API_KEY et EMAIL_FROM sont requis.")

    if fournisseur == "brevo":
        reponse = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": cle, "accept": "application/json"},
            json={
                "sender": {"email": expediteur, "name": nom},
                "to": [{"email": destinataire}],
                "subject": sujet,
                "textContent": texte,
                **({"htmlContent": html} if html else {}),
            },
            timeout=20,
        )
    elif fournisseur == "resend":
        reponse = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {cle}"},
            json={
                "from": f"{nom} <{expediteur}>",
                "to": [destinataire],
                "subject": sujet,
                "text": texte,
                **({"html": html} if html else {}),
            },
            timeout=20,
        )
    else:
        raise EmailNonConfigure(f"EMAIL_PROVIDER inconnu : {fournisseur}")

    if reponse.status_code >= 300:
        log.error("Échec d'envoi %s (%s) : %s", fournisseur, reponse.status_code, reponse.text[:300])
        raise RuntimeError(f"Échec d'envoi de l'e-mail ({fournisseur}, HTTP {reponse.status_code}).")
