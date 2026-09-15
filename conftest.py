"""
Pytest session bootstrap (repo root).

Sets the database + API key env BEFORE any test module is imported, so the
`database` module (bound to DATABASE_URL at module import time) never falls
back to the dev-local ./sovereign_local.db file depending on collection order.
"""
import os
import uuid

_TMP = os.environ.get("TEMP", ".")
_TMP_DB = os.path.join(_TMP, "opencode", f"pytest_{uuid.uuid4().hex}.db")

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{_TMP_DB.replace(os.sep, '/')}",
)
os.environ.setdefault(
    "SEED_API_KEYS",
    "acme-corp:acme-secret-1,big-bank:big-secret-2",
)
os.environ.setdefault("API_KEY_SALT", "test-salt")