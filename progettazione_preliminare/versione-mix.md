# Knowledge Pipeline: progettazione consolidata (versione fusa)

Sistema personale di discovery, ingestion, triage, compile e delivery di novità dal web. Fonde la pipeline di discovery+RAG (v2-1) con il design della knowledge base persistente, integrando le revisioni emerse durante review architetturale (collasso BERTopic, frammentazione vettoriale, VRAM contention, scoring multi-dominio).

**Data:** maggio 2026
**Target:** uso personale single-tenant su Pop_OS!, hardware desktop con GPU consumer, budget cloud LLM 5-10 USD/mese.

## Indice

1. Filosofia e principi
2. Architettura a due binari
3. Stadio 1: Discovery
4. Stadio 2: Ingestion
5. Stadio 3: Triage (il router)
6. Stadio 4: Compile (binario durevole)
7. Stadio 5: Report e delivery
8. Topic discovery emergente (sliding window)
9. Storage: schema unificato sqlite-vec
10. Gestione VRAM e batching sequenziale
11. Stack tecnologico
12. Schedule operativo
13. Roadmap implementativa
14. Calibrazione e costi attesi
15. Antipattern e questioni aperte

## 1. Filosofia e principi

Il sistema riconosce che il **flusso informativo** e la **conoscenza durevole** sono due cose diverse che richiedono trattamenti diversi:

- Il flusso è effimero, ad alto volume, va scremato aggressivamente.
- La conoscenza è permanente, a basso volume, va costruita con cura strutturale.

Principi guida:

1. **Triage prima del compute costoso.** Filtra con modelli locali ed embedding, manda al modello frontier solo il top-N.
2. **La KB è per la conoscenza durevole, non per il flusso.** Notizie effimere vivono nel digest e muoiono lì. Nella KB ci va solo quello che ha valore a 6 mesi.
3. **Costruire incrementalmente.** V1 senza LLM (aggregazione + dedup), poi triage, poi compile, poi synthesis.
4. **LLM mai libero di inventare riferimenti.** Le decisioni "dove scrivere" sono fatte da ricerca vettoriale. L'LLM lavora con riferimenti già risolti.
5. **Plan-then-apply.** L'LLM produce piani strutturati (Pydantic), il rendering è deterministico da template.
6. **Transazioni atomiche.** Stato relazionale, vettoriale e file system aggiornati insieme o per niente.
7. **Score assoluti, soglie relative.** Il `triage_score` è normalizzato in [0, 1] e cross-dominio confrontabile. Le soglie di promozione possono variare per dominio senza inquinare la metrica base.
8. **Batching per modello caricato.** Su GPU singola, ammortizza l'overhead di swap caricando un modello e processando tutto il batch del giorno con quello, prima di passare al successivo.

## 2. Architettura a due binari

```
Discovery ─▶ Ingestion ─▶ Triage ──┬──▶ Digest giornaliero (binario effimero)
                                    │     vive 90 giorni in items_vec
                                    │     poi viene potato
                                    │
                                    └──▶ Compile in KB (binario durevole)
                                          plan-then-apply
                                          pagine markdown permanenti
                                          alimenta weekly synthesis
```

Il **triage** è il punto di biforcazione. Imposta un flag `promote_to_kb` sull'item. Sotto soglia, l'item finisce nel digest e i suoi chunk restano interrogabili via RAG per 90 giorni, poi vengono potati. Sopra soglia, parte il compile pieno e l'item lascia tracce permanenti nella KB.

## 3. Stadio 1: Discovery

Cosa cercare e dove. Le fonti contano più del modello: l'80% del valore viene da 10-15 fonti ben scelte.

### Tipologie di fonti

| Tipo | Strumento | Note |
|---|---|---|
| RSS/Atom | `feedparser` | Affidabile, strutturato, zero scraping |
| arXiv | API ufficiale | Per categoria (cs.LG, cs.CL, etc.) |
| GitHub releases | GitHub REST API | Per repo seguiti |
| HN/Reddit | API ufficiali | Con filtro upvote minimo |
| Newsletter via email | Gmail API o IMAP | Casella dedicata, parser `mail-parser` |
| Aggregatori | RSS | TLDR AI, alphaSignal, Ben's Bites |
| Discovery aperta | SearXNG self-hosted | 70 motori aggregati, zero tracking |
| Web scraping mirato | Crawl4AI | Solo per siti senza feed |
| Discovery a richiesta | Firecrawl `/search` | Per ricerche periodiche su topic |

### File di configurazione

```yaml
# config/sources.yaml
sources:
  - id: anthropic-blog
    type: rss
    url: https://www.anthropic.com/news/rss
    domain: llm
    authority: 0.9

  - id: arxiv-cs-cl
    type: arxiv
    query: cat:cs.CL
    max_per_run: 20
    domain: research
    authority: 0.7

  - id: tldr-ai
    type: email
    from_address: dan@tldrnewsletter.com
    domain: llm
    authority: 0.6

  - id: hn-front-page
    type: hackernews
    min_score: 100
    domain: tech
    authority: 0.5

  - id: fastf1-releases
    type: github_releases
    repo: theOehrly/Fast-F1
    domain: formula1
    authority: 0.8
```

Il campo `domain` è cruciale per il triage multi-dominio (vedi §5.4).

## 4. Stadio 2: Ingestion

Ogni item entra normalizzato in markdown con frontmatter standard.

### Struttura su disco

```
sources/
  ingested/
    2026-05-13/
      arxiv-2505.12345.md
      blog-anthropic-claude-opus-47.md
      newsletter-tldr-ai-20260513.md
```

### Frontmatter

```yaml
---
id: arxiv-2505.12345
url: https://arxiv.org/abs/2505.12345
canonical_url: https://arxiv.org/abs/2505.12345
title: "Titolo originale"
source: arxiv-cs-cl
domain: research
date_published: 2026-05-13T08:00:00Z
date_ingested: 2026-05-13T09:15:00Z
content_hash: sha256:abc123...
simhash: 7f3a9b2c1d4e5f60
word_count: 1240
language: en
authors: ["Cognome, Nome"]
---
```

`content_hash` per deduplica esatta byte-level. `simhash` (64 bit) per deduplica near-duplicate sul testo estratto. `language` per scegliere modello a valle.

### Strumenti

**HTML → Markdown**: Crawl4AI primario (JS rendering, output markdown LLM-ready). Trafilatura come fallback rapido per fonti statiche.

**PDF → Markdown**: PyMuPDF4LLM default (text-layer only, velocissimo). Routing dinamico verso parser pesanti solo su trigger:

- Se il testo estratto ha < N caratteri per pagina → passa a Marker con OCR.
- Se contiene pattern tabellari rotti o alta densità numerica → passa a Docling.

Per le prime due settimane, si parte con PyMuPDF4LLM da solo e si logga ogni PDF problematico. Si attiva Marker/Docling nella settimana 3 in base ai pattern di fallimento reali, non a priori.

**Newsletter**: parsing IMAP/Gmail API + `mail-parser`, strip boilerplate via regex.

## 5. Stadio 3: Triage (il router)

Tre passaggi sequenziali per filtrare il rumore, più uno scoring che decide il binario.

### 5.1 Deduplica esatta

Confronto `content_hash`. Item con stesso byte stream scartati. Costo trascurabile, primo filtro.

### 5.2 Deduplica SimHash

Estrazione testuale (Trafilatura su HTML, PyMuPDF4LLM su PDF), calcolo SimHash a 64 bit. Distanza di Hamming < 3 con item degli ultimi 7 giorni identifica syndication e quasi-duplicati. Si tiene la versione più completa o della fonte più autorevole.

Questo livello intercetta news riscritte con piccole variazioni che il content_hash non vede e che cosine semantico vede solo male.

### 5.3 Deduplica semantica

Embedding del titolo + primi 500 token via Qwen3-Embedding-4B (Matryoshka 512). Similarità coseno > 0.95 contro chunk recenti già indicizzati negli ultimi 7 giorni → stessa notizia da fonti diverse riscritta in modo più sostanziale.

### 5.4 Classificazione rilevanza

LLM zero-shot locale (Gemma 3 4B, o Qwen3 4B se serve italiano) con prompt che descrive whitelist e blacklist dei topic seguiti.

```python
SYSTEM_PROMPT = """Sei un classificatore di rilevanza. Whitelist topic:
- LLM training, inference, evaluation
- AI agents, MCP, Claude
- Formula 1 data analysis e telemetria
- 3D modeling, Blender, Fusion 360
- Mathematics, optimization, distribuzioni

Blacklist:
- Crypto pricing news
- Generic startup news
- Politica

Output JSON: {relevant: bool, domain: str, topics: [str], reason: str}"""
```

### 5.5 Priority scoring (assoluto, normalizzato)

Formula con tutti gli input normalizzati a [0, 1]:

```
score = w_f * freshness + w_a * source_authority + w_t * topic_match + w_s * social_signal
```

Normalizzazioni obbligatorie:

- `freshness`: `exp(-hours_since_publish / half_life)`, half-life 3-7 giorni
- `source_authority`: lookup statico da `sources.yaml`, già in [0, 1]
- `topic_match`: similarità coseno con embedding del profilo utente, rescaled da [-1, 1] a [0, 1]
- `social_signal`: `log(1 + raw_score) / log(1 + max_observed_per_source)` con cap

### 5.6 Weight profiles per tipologia di fonte

Le fonti hanno tipologie di metadati diverse. Niente imputazione di valori mancanti (introduce bias): si usano profili di pesi per tipo, rinormalizzati a somma 1:

```python
WEIGHT_PROFILES = {
    "rss":        {"f": 0.30, "a": 0.50, "t": 0.20, "s": 0.00},
    "newsletter": {"f": 0.20, "a": 0.40, "t": 0.40, "s": 0.00},
    "arxiv":      {"f": 0.20, "a": 0.30, "t": 0.50, "s": 0.00},
    "hackernews": {"f": 0.20, "a": 0.20, "t": 0.30, "s": 0.30},
    "reddit":     {"f": 0.20, "a": 0.10, "t": 0.40, "s": 0.30},
    "github":     {"f": 0.30, "a": 0.20, "t": 0.30, "s": 0.20},
    "searxng":    {"f": 0.40, "a": 0.30, "t": 0.30, "s": 0.00},
}
```

Lo score finale è sempre in [0, 1] e confrontabile cross-source.

### 5.7 Soglie di promozione differenziate per dominio

`triage_score` viene salvato sempre come valore assoluto. La decisione di promozione è invece booleana e calibrata per dominio:

```python
PROMOTION_THRESHOLDS = {
    "llm":       0.75,
    "research":  0.70,
    "tech":      0.80,
    "formula1":  0.50,  # dominio in cui vuoi memoria fine-grained
    "3d":        0.55,
    "math":      0.60,
}

DIGEST_THRESHOLDS = {
    # sotto questa soglia l'item viene scartato del tutto
    "default": 0.30,
}
```

Lo schema separa `triage_score` (metrica assoluta confrontabile) da `promote_to_kb` (decisione booleana per dominio). Le query storiche sul punteggio restano consistenti, la calibrazione di cosa entra in KB resta flessibile.

Calibrazione iniziale: prime 2 settimane in modalità "log only" senza filtrare, per raccogliere dati reali su distribuzioni di score per dominio.

## 6. Stadio 4: Compile (binario durevole)

Solo per item con `promote_to_kb = true`. Lo snodo più delicato del sistema, dove l'agente integra novità nella KB senza inventare riferimenti.

### Struttura della KB

```
kb/
  topics/                # un .md per topic seguito (curati a mano)
    llm-training.md
    formula1-data.md
  entities/              # persone, organizzazioni, modelli, prodotti
    anthropic.md
    claude.md
  events/                # eventi datati, immutabili
    2026-05-anthropic-claude-opus-47.md
  methods/               # tecniche, paper seminali
    flash-attention.md
  index.md               # catalogo navigabile generato
  log.md                 # log cronologico ingestion
  CLAUDE.md              # schema operativo per l'agente
```

### Pagine temporali

Le pagine entity mantengono timeline di eventi:

```markdown
# Claude (modello)

Famiglia di LLM di Anthropic.

## Timeline

- 2024-06: Sonnet 3.5 → [[events/2024-06-claude-sonnet-35]]
- 2025-02: Sonnet 3.7 con extended thinking → [[events/2025-02-claude-sonnet-37]]
- 2026-05: Opus 4.7 → [[events/2026-05-anthropic-claude-opus-47]]

## Caratteristiche correnti

<!-- conf:high -->
Aggiornate all'ultimo ingestion: 2026-05-13

## Summary for synthesis

<!-- generated_at_compile_time -->
Famiglia LLM Anthropic, modelli flagship Opus e Sonnet, focus su safety e long context.
```

### Loop di compile rigoroso

```python
async def compile_item(item, kb, llm):
    # 1. Entity extraction locale (Gemma 3 4B, zero-shot strutturato)
    entities_raw = await extract_entities(
        text=item.content,
        types=["person", "organization", "model", "product", "method", "paper"],
        model="gemma3:4b"
    )

    # 2. Resolution contro KB esistente via sqlite-vec unificato
    resolved_entities = []
    for ent in entities_raw:
        ent_embedding = await embed(ent.name + " " + ent.context_snippet)
        candidates = kb.vector_search(
            embedding=ent_embedding,
            k=5,
            min_similarity=0.75,
            filter={"source_type": "kb_page", "entity_type": ent.type}
        )
        if not candidates:
            resolved_entities.append(Entity.new(ent, status="new"))
        elif candidates[0].similarity > 0.92:
            resolved_entities.append(Entity.match(candidates[0], status="confirmed"))
        else:
            # Solo i casi ambigui consumano LLM
            decision = await llm.arbitrate_entity_match(ent, candidates)
            resolved_entities.append(decision)

    # 3. Topic resolution (stesso pattern, su kb/topics/)
    resolved_topics = await resolve_topics(item, kb, llm)

    # 4. Context packing mirato
    context = build_compile_context(
        item=item,
        existing_entities=[e for e in resolved_entities if e.status == "confirmed"],
        new_entities=[e for e in resolved_entities if e.status == "new"],
        existing_topics=resolved_topics.matched,
        relevant_pages=kb.fetch_pages([e.page_path for e in resolved_entities if e.exists])
    )

    # 5. Plan-pass: LLM produce piano strutturato Pydantic
    plan = await llm.plan_compile(context, schema=COMPILE_PLAN_SCHEMA)

    # 6. Apply deterministico: wikilinks da template, path da resolved_entities
    operations = build_operations(plan, resolved_entities, resolved_topics)

    # 7. Transazione atomica
    async with kb.transaction():
        for op in operations:
            await op.apply()
            new_embedding = await embed(op.content[:1000])
            kb.update_embedding(op.path, new_embedding, source_type="kb_page")
        kb.append_log(item, operations)
        kb.update_index()

    return CompileResult(operations=operations, plan=plan)
```

### Schema del compile plan

```python
class EntityUpdate(BaseModel):
    resolved_path: str          # garantito valido (da resolved_entities)
    sections_to_update: list[SectionUpdate]
    add_to_timeline: TimelineEntry | None
    confidence: Literal["high", "medium", "low"]

class NewEntity(BaseModel):
    proposed_slug: str
    type: EntityType
    initial_content: EntityContent
    summary_for_synthesis: str  # 100-200 token

class EventPage(BaseModel):
    title: str
    date: date
    description: str
    summary_for_synthesis: str  # 100-200 token
    related_entities: list[str]  # path resolved
    related_topics: list[str]
    sources: list[SourceRef]

class CompilePlan(BaseModel):
    entity_updates: list[EntityUpdate]
    new_pages: list[NewEntity]
    event_page: EventPage
```

### Garanzie del pattern

- L'LLM non può inventare path: ogni `resolved_path` viene da ricerca vettoriale o slug deterministico.
- I wikilinks sono iniettati dal template, non dall'LLM.
- Le scritture sono transazionali.
- Le inferenze cross-document sono marcate con `confidence`, mai presentate come fatti.

## 7. Stadio 5: Report e delivery

### Daily digest

- 5-10 bullet con item più rilevanti delle ultime 24h
- Generato alle 7:00
- Ordinato per `triage_score` discendente
- Link agli item originali e alle pagine KB toccate (solo per item promossi)
- Marcato come "letto" automaticamente all'apertura

```markdown
# Daily digest 2026-05-13

## LLM e AI
- Anthropic rilascia Claude Opus 4.7 ([source](url), [[kb/events/2026-05-claude-opus-47]])
- Nuovo paper su sparse attention da DeepMind ([source](url), [[kb/methods/sparse-attention-v2]])

## Formula 1
- FastF1 v3.6: dati telemetria meteorologica ([source](url), [[kb/events/2026-05-fastf1-v36]])

## Da leggere quando hai tempo
- Karpathy aggiorna gist su LLM wiki ([source](url))
```

### Weekly synthesis (input ad alta densità)

Per evitare "Lost in the Middle", l'input NON sono gli item grezzi, ma:

1. Tutte le `summary_for_synthesis` degli **event** creati nella settimana
2. Il **diff** delle **entity** aggiornate (sezioni "caratteristiche correnti" before/after)
3. La lista dei **topic** con maggior attività (dal topic discovery sliding window)

Input totale tipico: 10-15k token invece di 50k+. Output narrativo di qualità superiore a costo inferiore.

### Topic alerts

Pattern detection sui metadata, non sintesi LLM:

- Topic con attività anomala (es. 5+ paper in una settimana su argomento che ne aveva uno al mese)
- Entity menzionata in 3+ event distinti in pochi giorni
- Contraddizioni rilevate dal lint settimanale

### Canali di delivery

| Canale | Strumento | Per cosa |
|---|---|---|
| Email | SMTP a se stessi | Daily digest |
| Obsidian vault | File .md in cartella watched | Tutto, archivio navigabile |
| Telegram | Bot personale | Topic alerts urgenti |
| RSS personale | Feed generato | Per app esterne |

## 8. Topic discovery emergente (sliding window)

BERTopic non gira sul flusso giornaliero (sarebbe statisticamente vuoto su 20-30 documenti). Gira invece su una **finestra scorrevole a densità minima**:

```python
async def run_topic_discovery():
    # Estrai vettori da items_vec degli ultimi 14 giorni
    window_items = db.query("""
        SELECT m.reference_id, e.embedding
        FROM vector_metadata m
        JOIN embeddings_vec e ON m.embedding_id = e.embedding_id
        WHERE m.source_type = 'item'
          AND m.created_at > datetime('now', '-14 days')
    """)

    if len(window_items) < 200:
        # Densità insufficiente, salta o estendi finestra
        log("Topic discovery skipped: only {} items in window".format(len(window_items)))
        return

    # BERTopic con UMAP + HDBSCAN su finestra densa
    topics, probs = bertopic_model.fit_transform(
        embeddings=[i.embedding for i in window_items]
    )

    # Confronta cluster emergenti contro kb/topics/ esistenti
    for cluster in topics.clusters:
        cluster_embedding = mean(cluster.member_embeddings)
        existing_topic_match = kb.vector_search(
            embedding=cluster_embedding,
            filter={"source_type": "kb_page", "page_type": "topic"},
            k=3
        )
        if not existing_topic_match or existing_topic_match[0].similarity < 0.7:
            # Topic emergente non coperto da pagine esistenti
            suggest_new_topic_page(cluster)
```

**Schedule:** la domenica notte (insieme al lint settimanale), fuori dal critical path mattutino. Output: lista di topic emergenti candidati a diventare pagine KB. Non auto-crea pagine, suggerisce.

## 9. Storage: schema unificato sqlite-vec

Spazio vettoriale unificato per garantire che entità menzionate negli item effimeri possano essere risolte contro pagine KB durevoli con una singola query.

```sql
-- Tabella vettoriale unica
CREATE VIRTUAL TABLE embeddings_vec USING vec0(
    embedding_id INTEGER PRIMARY KEY,
    embedding FLOAT[512]
);

-- Metadata polimorfica
CREATE TABLE vector_metadata (
    embedding_id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,    -- 'item' | 'item_chunk' | 'kb_page' | 'kb_page_chunk'
    reference_id TEXT NOT NULL,   -- item_id oppure kb_path
    page_type TEXT,               -- per kb_page: 'topic' | 'entity' | 'event' | 'method'
    entity_type TEXT,             -- per kb_page entity: 'person' | 'organization' | etc.
    created_at TEXT NOT NULL,
    expires_at TEXT,              -- NULL = durevole, data = effimero (potato dopo)
    FOREIGN KEY(embedding_id) REFERENCES embeddings_vec(embedding_id)
);

CREATE INDEX idx_meta_source_ref ON vector_metadata(source_type, reference_id);
CREATE INDEX idx_meta_expires ON vector_metadata(expires_at) WHERE expires_at IS NOT NULL;

-- Tabella items (flusso)
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE,
    canonical_url TEXT,
    simhash INTEGER,
    content_hash TEXT,
    source TEXT,
    domain TEXT,
    date_published TEXT,
    date_ingested TEXT,
    triage_score REAL,            -- assoluto, normalizzato [0, 1]
    triage_status TEXT,           -- 'pending' | 'kept' | 'dropped'
    promote_to_kb BOOLEAN DEFAULT 0,
    compile_status TEXT,          -- 'pending' | 'compiled' | 'failed' | 'na'
    read_at TEXT,
    FOREIGN KEY(simhash) -- usato per dedup query
);

CREATE INDEX idx_items_simhash ON items(simhash);
CREATE INDEX idx_items_domain_score ON items(domain, triage_score DESC);

-- Tabella pagine KB (durevole)
CREATE TABLE kb_pages (
    path TEXT PRIMARY KEY,
    page_type TEXT NOT NULL,      -- 'topic' | 'entity' | 'event' | 'method'
    title TEXT,
    slug TEXT,
    last_updated TEXT,
    summary_for_synthesis TEXT
);

CREATE TABLE kb_aliases (
    alias TEXT,
    canonical_path TEXT,
    PRIMARY KEY (alias, canonical_path)
);

CREATE TABLE compile_log (
    id INTEGER PRIMARY KEY,
    item_id TEXT,
    timestamp TEXT,
    operations_json TEXT,
    FOREIGN KEY(item_id) REFERENCES items(id)
);

-- Ponte item → pagine KB (quale item ha alimentato quali pagine)
CREATE TABLE item_to_kb (
    item_id TEXT,
    kb_path TEXT,
    PRIMARY KEY (item_id, kb_path),
    FOREIGN KEY(item_id) REFERENCES items(id),
    FOREIGN KEY(kb_path) REFERENCES kb_pages(path)
);
```

### Vantaggi dello schema unificato

- Una sola query vettoriale per cercare in **tutta la memoria** (effimera + durevole).
- Potatura a 90 giorni dei chunk effimeri è un singolo `DELETE FROM vector_metadata WHERE expires_at < CURRENT_DATE` + cascade su `embeddings_vec`.
- Entity resolution durante compile può scoprire connessioni tra item recenti non promossi e pagine KB esistenti.
- Transazioni ACID native, niente sync tra file separati, niente record orfani.

## 10. Gestione VRAM e batching sequenziale

Su GPU consumer singola, caricare embedder + classifier + BERTopic + parser OCR contemporaneamente non sta in memoria. La soluzione è batchare per modello caricato.

### Pattern operativo

```python
async def morning_pipeline():
    # Fase 1: fetch, no GPU pesante
    await fetch_all_sources()
    await dedup_exact()             # content_hash
    await dedup_simhash()           # CPU only, hashing

    # Fase 2: GPU step "embedder loaded"
    embedder = load_model("qwen3-embedding-4b")
    embeddings = await batch_embed_all(today_items, embedder)
    await dedup_semantic(embeddings)
    await store_embeddings(embeddings, source_type="item",
                           expires_at=today + 90_days)
    unload_model(embedder)
    torch.cuda.empty_cache()

    # Fase 3: GPU step "classifier loaded"
    classifier = load_model("gemma3:4b")
    triage_results = await batch_classify(surviving_items, classifier)
    promotion_flags = compute_promotion(triage_results)
    unload_model(classifier)
    torch.cuda.empty_cache()

    # Fase 4: GPU step opzionale "OCR/layout loaded"
    pdfs_needing_ocr = [p for p in today_pdfs if p.chars_per_page < 200]
    if pdfs_needing_ocr:
        marker = load_model("marker")
        await batch_ocr(pdfs_needing_ocr, marker)
        unload_model(marker)
        torch.cuda.empty_cache()

    # Fase 5: compile (Claude API, niente VRAM locale)
    promoted = [i for i in today_items if i.promote_to_kb]
    for item in promoted:
        await compile_item(item, kb, claude_client)
```

### Comandi Ollama per unload esplicito

```bash
# Scarica modello dalla VRAM
curl http://localhost:11434/api/generate -d '{"model": "gemma3:4b", "keep_alive": 0}'

# Oppure variabile globale
export OLLAMA_KEEP_ALIVE=0
```

Per modelli usati via sentence-transformers direttamente:

```python
del model
import gc; gc.collect()
torch.cuda.empty_cache()
```

## 11. Stack tecnologico

### Locale (sulla macchina, Pop_OS!)

| Layer | Strumento | Note |
|---|---|---|
| Runtime LLM locale | Ollama | API OpenAI-compatible, gestione modelli |
| Classifier | Gemma 3 4B (o Qwen3 4B per IT) | Zero-shot strutturato |
| Entity extraction | Gemma 3 4B | Stesso modello, scarico lazy |
| LLM RAG interattivo | Qwen3 30B-A3B (MoE) | Per query sullo storico |
| Embedding | Qwen3-Embedding-4B | Matryoshka 512 dim |
| Crawler HTML | Crawl4AI (primario) + Trafilatura (fallback) | JS rendering |
| PDF parser | PyMuPDF4LLM default | Marker/Docling on trigger |
| Topic discovery | BERTopic sliding window | Domenica notte, density-gated |
| Reranker | BGE-reranker-v2-m3 | Per RAG interattivo |
| Storage | SQLite + sqlite-vec | Unificato, ACID |
| Discovery aperta | SearXNG in Docker | + Redis per rate limiting |
| Viewer KB | Obsidian | Graph view, wikilinks |
| Orchestrazione | cron → APScheduler | V1 → V2 |

### Cloud (API a consumo)

| Layer | Strumento | Costo stimato |
|---|---|---|
| Compile primary | Claude Sonnet 4.6 | 3-8 USD/mese con prompt caching |
| Weekly synthesis | Claude Sonnet 4.6 | parte dei 3-8 USD |
| Discovery aggiuntiva | Firecrawl `/search` | 0-5 USD/mese opzionale |

### Dipendenze Python chiave

```toml
[project.dependencies]
# ingestion
feedparser = "*"
crawl4ai = "*"
trafilatura = "*"
pymupdf4llm = "*"
arxiv = "*"

# dedup
simhash = "*"

# embedding e ml
sentence-transformers = "*"
bertopic = "*"

# llm clients
ollama = "*"
anthropic = "*"

# storage
sqlite-vec = "*"
sqlite-utils = "*"

# orchestration
apscheduler = "*"

# email
mail-parser = "*"

# utility
pydantic = "*"
typer = "*"
rich = "*"
```

## 12. Schedule operativo

```
00:00  cron: ingestion arxiv batch notturno (no GPU contention)
06:00  cron: ingestion RSS + newsletter + searxng
06:15  dedup esatto (content_hash) + SimHash (CPU)
06:25  GPU: embedder caricato → batch embed → dedup semantica → store
06:40  GPU: classifier caricato → batch classify → promotion flags
06:55  GPU: OCR/layout solo se PDF triggered
07:00  compile via Claude API (item promossi, no GPU locale)
07:15  daily digest generato e inviato via email
22:00  cron: potatura chunk effimeri > 90 giorni
Dom 22:00  BERTopic sliding window 7-14 giorni
Dom 22:30  KB lint job (orphan, link rotti, contraddizioni, summary mancanti)
Lun 08:00  weekly synthesis su summary_for_synthesis + entity diffs
```

## 13. Roadmap implementativa

### Settimana 1-2: V1 minima (solo flusso)

**Obiettivo:** vedere il volume reale del flusso prima di scegliere come gestirlo.

- Repo Python con struttura cartelle
- `feedparser` su 5-8 RSS principali
- Canonicalizzazione URL (rimozione UTM, risoluzione redirect)
- Dedup esatto via content_hash
- Salvataggio markdown con frontmatter in `sources/ingested/YYYY-MM-DD/`
- Schema iniziale sqlite (senza embeddings ancora)
- Daily digest plain text (lista item) via email o file locale
- cron alle 7:00
- Modalità "log only" su `triage_score`: registra ma non filtra, per calibrazione

### Settimana 3-4: Triage completo

- SimHash dedup (3 livelli)
- Setup Ollama + Gemma 3 4B (classifier)
- Setup embedder Qwen3-Embedding-4B + sqlite-vec
- Dedup semantica con soglia 0.95
- Classifier rilevanza zero-shot
- Priority scoring con weight profiles per source type
- Calibrazione soglie per dominio sui dati raccolti nelle prime 2 settimane
- Digest ordinato per priorità
- Routing PDF: Marker su trigger (in base ai fallimenti osservati)

### Settimana 5-8: KB e Compile

- Setup cartelle KB con `CLAUDE.md`
- Schema completo sqlite-vec unificato (items, kb_pages, aliases, vector_metadata)
- Entity extraction locale (Gemma 3 4B)
- Resolution via vector search unificata
- Plan-pass via Claude API con Pydantic schema
- Apply deterministico con template
- Transazioni atomiche
- Viewing in Obsidian
- Implementazione batching sequenziale per VRAM

### Settimana 9-12: Synthesis, topic discovery, lint

- Generazione `summary_for_synthesis` nel compile
- Weekly synthesis su input condensato
- BERTopic sliding window 7-14 giorni, density-gated
- Lint job (orphan, contraddizioni, link rotti, summary mancanti)
- Topic alerts su pattern detection
- Ricalibrazione soglie sui dati accumulati

### Mese 4+: ottimizzazioni

- Telegram bot per alerts urgenti
- Migrazione a Prefect/Dagster solo se serve davvero
- SearXNG self-hosted se la copertura RSS non basta
- Re-embedding storico se si cambia modello

## 14. Calibrazione e costi attesi

Volumi tipici:

- 20-50 fonti monitorate
- 50-200 item grezzi al giorno
- 10-30 item dopo dedup (3 livelli)
- 3-8 item compilati pienamente nella KB
- 1 daily digest, 1 weekly synthesis

Costo Claude con prompt caching:

- Compile di 5 item/giorno: 0.05-0.15 USD/giorno → 1.5-4.5 USD/mese
- Weekly synthesis: 0.2-0.5 USD → 0.8-2 USD/mese
- **Totale realistico: 3-8 USD/mese**

Senza triage rigoroso, gli stessi volumi arrivano a 50+ USD/mese. La differenza è tutta nel filtro.

## 15. Antipattern e questioni aperte

### Antipattern da evitare

**Compile libero senza resolution**: l'LLM inventa wikilinks. Sempre micro-RAG prima di scrivere.

**Scoring senza normalizzazione**: `social_signal` cannibalizza tutto. Tutti gli input in [0, 1] prima della combinazione lineare.

**Soglia di promozione che modifica triage_score**: rompe la confrontabilità storica. La soglia agisce a valle del punteggio, non sul punteggio.

**Spazi vettoriali separati**: impedisce di scoprire che entità in item effimero = entità in pagina KB. Schema unificato con metadata polimorfica.

**BERTopic sul flusso 24h**: collasso statistico su batch piccoli. Sliding window density-gated.

**Caricare tutti i modelli in VRAM contemporaneamente**: OOM o swap pesante. Batching per modello.

**SQLite + FAISS separati**: record orfani. sqlite-vec non è opzionale.

**Sintesi settimanale su item grezzi**: 50k+ token, "lost in the middle". Solo summary_for_synthesis + diff.

**Mettere tutto in KB**: notizie effimere muoiono nel digest. KB solo per valore a 6 mesi.

**Compile senza lint settimanale**: allucinazioni si cristallizzano e propagano via link.

**Modelli piccoli per compile vero**: Gemma 4 E4B su task agentico fallisce silenziosamente. Claude API per il compile.

**Implementare routing PDF complesso senza dati**: PyMuPDF4LLM su tutto, log dei fallimenti, attiva Marker/Docling solo sui pattern reali.

**Troppe fonti**: 200 fonti = 200 rumori. 15 fonti curate = 80% del valore.

### Questioni aperte da affrontare strada facendo

1. **Feedback loop sul classifier**: come ricalibrare la whitelist/blacklist quando il classifier diverge dagli interessi reali. Possibile soluzione: log delle decisioni del classifier, review manuale settimanale, fine-tuning del prompt mensile.

2. **Versioning della KB**: se a 6 mesi cambia schema delle pagine, come migrare. Possibile soluzione: campo `schema_version` nelle pagine, script di migrazione idempotenti.

3. **Death detection sulle fonti**: un RSS che smette di funzionare deve generare alert, non sparire silenziosamente. Possibile soluzione: tracciare `last_successful_fetch` per fonte, alert se > 14 giorni.

4. **Embedder drift**: cambio di modello embedding richiede re-embedding di tutta la KB. Possibile soluzione: pianificare windows di re-embedding annuali, mantenere `embedding_model_version` in metadata.

5. **Misura costi reali**: i 3-8 USD/mese sono una stima. Tracking effettivo per dashboard mensile.

6. **Backup**: il file `kb.db` (sqlite-vec) e la cartella `kb/` vanno in backup periodico. Tutto il resto (`sources/ingested/`) è ricostruibile dalle fonti.

7. **Multilingua**: italiano + inglese gestiti bene da Qwen3 e BGE-M3. Per altre lingue verificare modello per modello.

### Decisioni di design già fissate

1. **KB unica con cartelle per topic**: più semplice, cross-references naturali.
2. **Storico**: source markdown grezzi archiviabili dopo 90 giorni. KB permanente. Digest tenuto 12 mesi.
3. **Privacy / self-hosting puro**: opzionale, accettando perdita qualità 20-40% nel compile usando Qwen3 30B-A3B invece di Claude.
4. **PDF**: PyMuPDF4LLM only per le prime 2 settimane, poi routing dinamico data-driven.
5. **Soglie**: 2 settimane di "log only" per calibrazione iniziale.

---

**Nota finale.** Questo documento rappresenta il design consolidato dopo review architetturale. È blindato sui pilastri (triage come router, schema vettoriale unificato, batching VRAM, scoring assoluto con soglie relative), ma non sui dettagli operativi che emergeranno solo con i dati reali (volumi, distribuzioni di score per dominio, pattern di fallimento PDF, costi reali Claude). L'approccio incrementale della roadmap è progettato esattamente per questo: ogni stadio aggiunge valore reale e può essere fermato lì, ogni decisione data-driven è rinviata al momento in cui i dati esistono.