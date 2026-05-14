-- Migration 001 — schema unificato sqlite-vec (uno per dominio).
--
-- {{EMBEDDING_DIM}} viene sostituito alla creazione del DB con la dimensionalita
-- Matryoshka configurata (global.yaml: models.embedding.matryoshka_dim).
-- Cambiare dimensionalita in seguito richiede re-embedding: vedi questioni aperte.

-- Tracking delle migration applicate (idempotenza del runner).
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Spazio vettoriale unico: item effimeri e pagine KB durevoli nello stesso indice.
-- Una sola query vettoriale copre tutta la memoria del dominio.
CREATE VIRTUAL TABLE embeddings_vec USING vec0(
    embedding_id INTEGER PRIMARY KEY,
    embedding    FLOAT[{{EMBEDDING_DIM}}]
);

-- Metadata polimorfica sui vettori: distingue cosa rappresenta ogni embedding
-- e quando scade (effimero vs durevole).
CREATE TABLE vector_metadata (
    embedding_id INTEGER PRIMARY KEY,
    source_type  TEXT NOT NULL,   -- 'item' | 'item_chunk' | 'kb_page' | 'kb_page_chunk'
    reference_id TEXT NOT NULL,   -- items.id oppure kb_pages.path
    page_type    TEXT,            -- per kb_page: 'topic' | 'entity' | 'event' | 'method'
    entity_type  TEXT,            -- per kb_page entity: 'person' | 'organization' | ...
    created_at   TEXT NOT NULL,
    expires_at   TEXT,            -- NULL = durevole; data = effimero (potato dopo 90gg)
    FOREIGN KEY(embedding_id) REFERENCES embeddings_vec(embedding_id)
);
CREATE INDEX idx_meta_source_ref ON vector_metadata(source_type, reference_id);
CREATE INDEX idx_meta_expires ON vector_metadata(expires_at) WHERE expires_at IS NOT NULL;

-- Flusso: item ingeriti dalle fonti.
CREATE TABLE items (
    id             TEXT PRIMARY KEY,
    url            TEXT UNIQUE,
    canonical_url  TEXT,
    title          TEXT,
    source         TEXT,
    domain         TEXT,
    simhash        INTEGER,            -- 64 bit, dedup near-duplicate
    content_hash   TEXT,              -- sha256, dedup esatta byte-level
    date_published TEXT,
    date_ingested  TEXT,
    triage_score   REAL,              -- assoluto, normalizzato [0, 1]
    triage_status  TEXT,              -- 'pending' | 'kept' | 'dropped'
    promote_to_kb  INTEGER DEFAULT 0,  -- decisione booleana, soglia per dominio
    compile_status TEXT,              -- 'pending' | 'compiled' | 'failed' | 'na'
    read_at        TEXT               -- NULL finche il digest non viene aperto
);
CREATE INDEX idx_items_simhash ON items(simhash);
CREATE INDEX idx_items_domain_score ON items(domain, triage_score DESC);

-- Durevole: pagine della knowledge base.
CREATE TABLE kb_pages (
    path                  TEXT PRIMARY KEY,
    page_type             TEXT NOT NULL,     -- 'topic' | 'entity' | 'event' | 'method'
    title                 TEXT,
    slug                  TEXT,
    schema_version        INTEGER DEFAULT 1,  -- per migrazioni future dello schema pagina
    last_updated          TEXT,
    summary_for_synthesis TEXT
);

-- Alias di risoluzione entita (es. "OpenAI Inc." -> entities/openai).
CREATE TABLE kb_aliases (
    alias          TEXT,
    canonical_path TEXT,
    PRIMARY KEY (alias, canonical_path),
    FOREIGN KEY(canonical_path) REFERENCES kb_pages(path)
);

-- Log delle operazioni di compile, append-only.
CREATE TABLE compile_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT,
    timestamp       TEXT,
    operations_json TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);

-- Ponte: quale item ha alimentato quali pagine KB.
CREATE TABLE item_to_kb (
    item_id TEXT,
    kb_path TEXT,
    PRIMARY KEY (item_id, kb_path),
    FOREIGN KEY(item_id) REFERENCES items(id),
    FOREIGN KEY(kb_path) REFERENCES kb_pages(path)
);
