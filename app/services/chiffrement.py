"""Chiffrement au repos des jetons OAuth (Google Agenda, Outlook).

Clé : variable INTEGRATION_ENCRYPTION_KEY, une clé Fernet (AES-128-CBC +
HMAC-SHA256), à générer une fois :

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Une valeur chiffrée est stockée préfixée « enc1: ». Les valeurs en clair
écrites avant ce chiffrement restent lisibles (transition) ; au démarrage,
chiffrer_restants() les chiffre dès que la clé est présente. Sans clé, les
nouvelles valeurs sont écrites en clair et un avertissement est journalisé :
un déploiement sans la variable ne doit pas casser la connexion aux agendas.

Perdre la clé rend les jetons illisibles : l'utilisateur devra reconnecter
son agenda, rien de plus grave.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

log = logging.getLogger("suivi.chiffrement")
PREFIXE = "enc1:"


def _fernet() -> Fernet | None:
    cle = os.environ.get("INTEGRATION_ENCRYPTION_KEY", "").strip()
    return Fernet(cle.encode()) if cle else None


def chiffrer(valeur: str | None) -> str | None:
    if valeur is None or valeur.startswith(PREFIXE):
        return valeur
    f = _fernet()
    if f is None:
        return valeur
    return PREFIXE + f.encrypt(valeur.encode()).decode()


def dechiffrer(valeur: str | None) -> str | None:
    if valeur is None or not valeur.startswith(PREFIXE):
        return valeur  # valeur écrite avant le chiffrement
    f = _fernet()
    if f is None:
        raise RuntimeError("Jeton chiffré mais INTEGRATION_ENCRYPTION_KEY absente.")
    try:
        return f.decrypt(valeur[len(PREFIXE):].encode()).decode()
    except InvalidToken:
        raise RuntimeError("Jeton chiffré avec une autre clé : reconnecter l'agenda.")


class ChaineChiffree(TypeDecorator):
    """Colonne texte chiffrée à l'écriture, déchiffrée à la lecture."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return chiffrer(value)

    def process_result_value(self, value, dialect):
        return dechiffrer(value)


def verifier_configuration() -> None:
    if _fernet() is None:
        log.warning("INTEGRATION_ENCRYPTION_KEY absente : jetons OAuth stockés en clair.")


def chiffrer_restants(db) -> int:
    """Chiffre les jetons encore en clair (idempotent). Passe par du SQL brut
    pour lire la valeur stockée telle quelle, sans le déchiffrement du type."""
    if _fernet() is None:
        return 0
    from sqlalchemy import text
    lignes = db.execute(text("SELECT id, access_token, refresh_token FROM external_integrations")).all()
    n = 0
    for id_, acces, rafraichissement in lignes:
        if (acces and not acces.startswith(PREFIXE)) or (rafraichissement and not rafraichissement.startswith(PREFIXE)):
            db.execute(
                text("UPDATE external_integrations SET access_token = :a, refresh_token = :r WHERE id = :i"),
                {"a": chiffrer(acces), "r": chiffrer(rafraichissement), "i": id_},
            )
            n += 1
    db.commit()
    if n:
        log.info("%s connexion(s) d'agenda chiffrée(s) au démarrage", n)
    return n
