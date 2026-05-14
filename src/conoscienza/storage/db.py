"""Storage unificato sqlite-vec, un file ``kb.db`` per dominio.

Metadati relazionali e spazio vettoriale nello stesso DB: transazioni ACID,
nessuna sincronizzazione tra store separati, nessun record orfano.

Le migration sono file ``NNN_*.sql`` in ``migrations/``, applicate in ordine e
registrate in ``schema_migrations``. Il runner e idempotente.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import sqlite_vec

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_DIM_PLACEHOLDER = "{{EMBEDDING_DIM}}"


def connect(db_path: Path) -> sqlite3.Connection:
    """Apre una connessione con l'estensione sqlite-vec caricata e i foreign key attivi."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transazione atomica: commit in uscita pulita, rollback su eccezione."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Versioni di migration gia registrate. Vuoto se il DB e nuovo."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def _pending_migrations(applied: set[int]) -> list[Path]:
    """File di migration non ancora applicati, in ordine di versione."""
    files = sorted(_MIGRATIONS_DIR.glob("[0-9]*.sql"))
    return [f for f in files if int(f.name.split("_", 1)[0]) not in applied]


def init_db(db_path: Path, embedding_dim: int) -> sqlite3.Connection:
    """Crea o aggiorna ``kb.db`` applicando le migration pendenti.

    Idempotente: rieseguibile, applica solo le migration non ancora registrate.
    ``embedding_dim`` (dimensionalita Matryoshka, da config) viene iniettato nello
    schema vec0 al momento della creazione.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    pending = _pending_migrations(_applied_versions(conn))
    if not pending:
        return conn

    now = datetime.now(timezone.utc).isoformat()
    for migration in pending:
        version = int(migration.name.split("_", 1)[0])
        sql = migration.read_text(encoding="utf-8").replace(
            _DIM_PLACEHOLDER, str(embedding_dim)
        )
        # executescript fa commit del DDL; la riga di tracking segue e viene committata.
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now),
        )
        conn.commit()
    return conn
