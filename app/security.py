import os
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

# À définir en variable d'environnement en prod — valeur de dev uniquement.
SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: str) -> str:
    """Retourne le user_id (sub) si le token est valide, lève JWTError sinon."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise JWTError("Wrong token type")
    return payload["sub"]
