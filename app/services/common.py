"""Petits utilitaires partagés par les nouveaux routers (voir SUIVI_RECAP.md
§5). Traduction directe des fonctions équivalentes de mobile/src/api/
mockData.js (daysSince, isSameDay, startOfWeek, relativeTime, dateKey...) —
gardées ici plutôt que dupliquées dans chaque router pour que le calcul
reste identique partout (ex. définition de "lundi = début de semaine").

Convention de sérialisation : les timestamps exposés à l'app sont en
millisecondes epoch (to_ms), pas en ISO 8601 — mockData.js utilise partout
`Date.now()` / `occurredAt` en ms, et les écrans front s'attendent à ce
format (arithmétique JS directe sur les valeurs reçues).
"""
from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_ms(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def aware(dt: datetime) -> datetime:
    """Normalise un datetime potentiellement naïf en UTC. Sur Postgres
    (prod) les colonnes DateTime(timezone=True) reviennent déjà aware ; ce
    garde-fou évite un TypeError si jamais un datetime naïf traîne (ex. en
    dev local sur SQLite, qui ne conserve pas le fuseau)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def start_of_week(dt: datetime) -> datetime:
    # Lundi 00:00 — même convention que HabitsScreen/mockData (startOfWeek).
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def is_same_day(a: datetime, b: datetime) -> bool:
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a.astimezone(timezone.utc).date() == b.astimezone(timezone.utc).date()


def days_since(dt: datetime, now: datetime | None = None) -> int:
    now = now or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (now - dt).days)


def date_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def today_key(now: datetime | None = None) -> str:
    return date_key(now or now_utc())


def relative_time(dt: datetime, now: datetime | None = None) -> str:
    now = now or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hours = int((now - dt).total_seconds() // 3600)
    if hours < 1:
        return "à l’instant"
    if hours < 24:
        return f"il y a {hours} h"
    days = hours // 24
    return f"il y a {days} j"
