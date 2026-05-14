# Knowledge Pipeline: Documento di progettazione

Sistema personale di scoperta, ingestion, sintesi e delivery di novità dal web in una knowledge base locale interrogabile. Versione di progettazione consolidata dopo review architetturale.

## Obiettivo

Costruire un sistema che ogni giorno:

1. Scopre cosa è uscito di nuovo sul web nei domini di interesse
2. Ingerisce, deduplica e filtra il rumore
3. Integra il signal in una knowledge base persistente che cresce in coerenza
4. Consegna digest giornaliero e sintesi settimanale narrative

Vincoli:

- Singolo utente, uso personale
- Hardware: workstation con RTX 4060 8GB, RAM 32GB+
- Budget cloud LLM: 5-10 USD/mese
- Locale dove possibile, cloud (Claude API) solo per il compile pesante
- Manutenzione minima, esecuzione invisibile in background su Linux

## Principi di design

1. **Triage prima del compute costoso.** Filtra aggressivamente con modelli locali ed embedding, manda al modello frontier solo il top-N.
2. **La KB è per la conoscenza durevole, non per il flusso.** Notizie effimere vivono nel digest e muoiono lì. Nella KB ci va solo quello che ha valore a 6 mesi.
3. **Costruire incrementalmente.** V1 senza LLM (aggregazione + dedup), poi triage, poi compile, poi synthesis. Ogni stadio aggiunge valore reale e può essere fermato lì.
4. **LLM mai libero di inventare riferimenti.** Le decisioni "dove scrivere" sono fatte da ricerca vettoriale. L'LLM lavora con riferimenti già risolti.
5. **Plan-then-apply.** L'LLM produce piani strutturati (Pydantic), il rendering è deterministico da template.
6. **Transazioni atomiche.** Stato relazionale, vettoriale e file system aggiornati insieme o per niente.

## Architettura a cinque stadi

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Discovery   │───▶│  Ingestion   │───▶│   Triage     │───▶│   Compile    │───▶│   Report     │
│              │    │              │    │              │    │              │    │              │
│  RSS, API,   │    │  HTML/PDF    │    │  Dedup +     │    │  Resolution  │    │  Daily +     │
│  Newsletter  │    │  → Markdown  │    │  Rilevanza   │    │  + plan-apply│    │  Weekly      │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                            │                   │                   │                   │
                            ▼                   ▼                   ▼                   ▼
                       sources/            metadata.db          kb/topics/         reports/
                       ingested/           embeddings           kb/entities/       digest-*.md
                                           (sqlite-vec)         kb/events/
```

## Stadio 1: Discovery

Cosa cercare e dove. Le fonti contano più del modello. Regola: l'80% del valore viene da 10-15 fonti ben scelte.

### Tipologie di fonti

| Tipo | Strumento | Note |
|------|-----------|------|
| RSS/Atom | `feedparser` | Affidabile, strutturato, zero scraping |
| Mailing list | Gmail API o IMAP | Newsletter a casella dedicata |
| arXiv | API ufficiale | Per categoria (cs.LG, cs.CL, etc.) |
| GitHub releases | GitHub REST API | Per repo seguiti |
| HN/Reddit | API ufficiali | Con filtro upvote minimo |
| Aggregatori | RSS | TLDR AI, alphaSignal, Ben's Bites, The Batch |
| Web scraping | Crawl4AI | Solo per siti senza feed |
| Discovery aggiuntiva | Firecrawl `/search` | Per ricerche periodiche su topic |

### File di configurazione

```yaml
# config/sources.yaml
sources:
  - id: anthropic-blog
    type: rss
    url: https://www.anthropic.com/news/rss
    tags: [llm, anthropic]
    authority: 0.9

  - id: arxiv-cs-cl
    type: arxiv
    query: cat:cs.CL
    max_per_run: 20
    tags: [research, nlp]
    authority: 0.7

  - id: tldr-ai
    type: email
    from_address: dan@tldrnewsletter.com
    tags: [aggregator]
    authority: 0.6

  - id: hn-front-page
    type: hackernews
    min_score: 100
    tags: [aggregator, tech]
    authority: 0.5
```

## Stadio 2: Ingestion

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
title: "Titolo originale"
source: arxiv-cs-cl
date_published: 2026-05-13T08:00:00Z
date_ingested: 2026-05-13T09:15:00Z
tags: [llm, releases]
content_hash: sha256:abc123...
word_count: 1240
language: en
authors: ["Cognome, Nome"]
---
```

`content_hash` per deduplica esatta. `language` per scegliere modello a valle.

### Strumenti per stadio

**HTML → Markdown**: Crawl4AI locale (JS rendering, output markdown LLM-ready). Fallback Jina Reader (`r.jina.ai/URL`) per quick fetch.

**PDF → Markdown**: Marker come default. Docling se integri LangChain/LlamaIndex. MinerU per matematica complessa o layout CJK.

**Newsletter**: parsing IMAP/Gmail API + `mail-parser`, strip boilerplate via regex.

**arXiv**: download PDF, parse con Marker, conserva metadati strutturati (autori, abstract, categorie).

## Stadio 3: Triage

Tre passaggi sequenziali per filtrare il rumore prima del compile.

### 3.1 Deduplica esatta

Confronto `content_hash`. Item con stesso byte stream scartati.

### 3.2 Deduplica semantica

Embedding di titolo + primi 500 token. Similarità coseno > 0.85 sull'indice degli ultimi 7 giorni → stesso evento da fonti diverse. Si tiene la versione più completa o della fonte più autorevole.

### 3.3 Classificazione rilevanza

LLM zero-shot locale (Gemma 4 E4B via Ollama) con prompt che descrive whitelist e blacklist dei topic seguiti.

```python
SYSTEM_PROMPT = """Sei un classificatore di rilevanza. Whitelist topic:
- LLM training, inference, evaluation
- AI agents, MCP, Claude
- Formula 1 data analysis
- 3D modeling, Blender, Fusion 360

Blacklist:
- Crypto pricing news
- Generic startup news
- Politica

Output JSON: {relevant: bool, topics: [str], reason: str}"""
```

### 3.4 Priority scoring

Formula con tutti gli input normalizzati a [0, 1]:

```
score = w_f * freshness + w_a * source_authority + w_t * topic_match + w_s * social_signal
```

Normalizzazioni obbligatorie:

- `freshness`: exponential decay, `exp(-hours_since_publish / half_life)`, half-life 3-7 giorni
- `source_authority`: lookup statico da `sources.yaml`, già in [0, 1]
- `topic_match`: similarità coseno con embedding del profilo utente, rescaled da [-1, 1] a [0, 1]
- `social_signal`: `log(1 + raw_score) / log(1 + max_observed_per_source)` con cap, oppure percentile rank sui dati storici della fonte

### 3.5 Gestione dei null per profilo di fonte

Le fonti hanno tipologie di metadati diverse. RSS non ha upvote, HN non ha autorità editoriale paragonabile. Niente imputazione (introduce bias), si usano **profili di pesi per tipo di fonte**, rinormalizzati a somma 1:

```python
WEIGHT_PROFILES = {
    "rss":       {"f": 0.30, "a": 0.50, "t": 0.20, "s": 0.00},
    "newsletter":{"f": 0.20, "a": 0.40, "t": 0.40, "s": 0.00},
    "arxiv":     {"f": 0.20, "a": 0.30, "t": 0.50, "s": 0.00},
    "hackernews":{"f": 0.20, "a": 0.20, "t": 0.30, "s": 0.30},
    "reddit":    {"f": 0.20, "a": 0.10, "t": 0.40, "s": 0.30},
    "github":    {"f": 0.30, "a": 0.20, "t": 0.30, "s": 0.20},
}
```

Lo score finale è sempre in [0, 1] e confrontabile cross-source. Solo item con `score > threshold` passano al compile. Soglia calibrata empiricamente nei primi 7-10 giorni.

### Modelli consigliati

| Componente | Modello | Note |
|------------|---------|------|
| Embedding | Qwen3-Embedding-4B | SOTA 2026 open, supporta Matryoshka |
| Embedding alternativo | BGE-M3 | Hybrid dense+sparse nativo, ottimo IT/EN |
| Classifier LLM | Gemma 4 E4B | Veloce, gira tutto in VRAM, 128K context |
| Classifier alternativo | Qwen3 4B | Migliore su italiano per dominio |

## Stadio 4: Compile

Lo snodo più delicato. Integrazione dei nuovi item nella KB con pattern LLM Wiki temporale, ma trasformato in micro-RAG per evitare allucinazioni di riferimenti.

### Struttura della KB

```
kb/
  topics/              # un .md per topic seguito
    llm-training.md
    formula1-data.md
  entities/            # persone, organizzazioni, modelli, prodotti
    anthropic.md
    claude.md
    openai.md
  events/              # eventi datati, immutabili
    2026-05-anthropic-claude-opus-47.md
  methods/             # tecniche, paper seminali
    flash-attention.md
  index.md             # catalogo navigabile generato
  log.md               # log cronologico ingestion
  CLAUDE.md            # schema operativo per l'agente
```

### Pagine temporali

Differenza chiave dal pattern Karpathy nativo: le pagine entity sono **temporali**, mantengono timeline di eventi.

Esempio `kb/entities/claude.md`:

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
...

## Summary for synthesis

<!-- generated_at_compile_time -->
Famiglia LLM Anthropic, modelli flagship Opus e Sonnet, focus su safety e long context.
Ultimo rilascio significativo: Opus 4.7 (2026-05) con capacità agentiche estese.
```

### Loop di compile rigoroso (risolve il collo di bottiglia cognitivo)

L'agente di compile NON cerca match liberamente. Esegue una pipeline strutturata:

```python
async def compile_item(item: TriagedItem, kb: KnowledgeBase, llm: LLMClient) -> CompileResult:

    # 1. Entity extraction locale (modello piccolo, zero-shot)
    entities_raw = await extract_entities(
        text=item.content,
        types=["person", "organization", "model", "product", "method", "paper"],
        model="gemma4:e4b"
    )

    # 2. Resolution contro KB esistente via sqlite-vec
    resolved_entities = []
    for ent in entities_raw:
        ent_embedding = await embed(
            ent.name + " " + ent.context_snippet,
            model="qwen3-embedding-4b"
        )
        candidates = kb.entities.vector_search(
            embedding=ent_embedding,
            k=5,
            min_similarity=0.75,
            filter={"type": ent.type}
        )
        if not candidates:
            resolved_entities.append(Entity.new(ent, status="new"))
        elif candidates[0].similarity > 0.92:
            resolved_entities.append(Entity.match(candidates[0], status="confirmed"))
        else:
            # Solo i casi ambigui consumano una chiamata LLM
            decision = await llm.arbitrate_entity_match(ent, candidates)
            resolved_entities.append(decision)

    # 3. Topic resolution (stesso pattern, su kb/topics/)
    resolved_topics = await resolve_topics(item, kb, llm)

    # 4. Context packing mirato (non l'intera KB)
    context = build_compile_context(
        item=item,
        existing_entities=[e for e in resolved_entities if e.status == "confirmed"],
        new_entities=[e for e in resolved_entities if e.status == "new"],
        existing_topics=resolved_topics.matched,
        relevant_pages=kb.fetch_pages(
            [e.page_path for e in resolved_entities if e.exists]
        )
    )

    # 5. Plan-pass: LLM produce un piano strutturato Pydantic, NON markdown libero
    plan = await llm.plan_compile(context, schema=COMPILE_PLAN_SCHEMA)

    # 6. Apply deterministico: wikilinks da template, path da resolved_entities
    operations = build_operations(plan, resolved_entities, resolved_topics)

    # 7. Transazione atomica
    async with kb.transaction():
        for op in operations:
            await op.apply()                          # scrittura file
            new_embedding = await embed(op.content[:1000])
            kb.update_embedding(op.path, new_embedding)  # aggiorna sqlite-vec
        kb.append_log(item, operations)
        kb.update_index()

    return CompileResult(operations=operations, plan=plan)
```

### Schema del compile plan

```python
class EntityUpdate(BaseModel):
    resolved_path: str          # da resolved_entities, garantito valido
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

- L'LLM non può inventare path: ogni `resolved_path` viene da ricerca vettoriale o slug deterministico
- I wikilinks sono iniettati dal template, non dall'LLM
- Le scritture sono transazionali: stato relazionale, vettoriale e file system coerenti
- Le inferenze cross-document sono marcate con `confidence`, mai presentate come fatti

### CLAUDE.md (schema operativo per l'agente)

```markdown
# Schema della Knowledge Base

## Tipi di pagina

### topic
Sezioni fisse: overview, sub-topic, eventi correlati, fonti recenti.
Aggiornata quando nuovi events/methods/entities emergono nel topic.

### entity
Sezioni fisse: descrizione, timeline, caratteristiche correnti, relazioni,
summary_for_synthesis.
Una pagina per organizzazione, prodotto, modello, persona di rilievo.

### event
IMMUTABILE dopo creazione.
Sezioni fisse: data, descrizione, fonti, implicazioni, summary_for_synthesis,
link a entity/topic coinvolti.

### method
Tecnica, algoritmo, paper seminale.
Sezioni fisse: idea base, paper di riferimento, applicazioni note.

## Regole

- Wikilinks `[[path/to/page]]` SEMPRE da resolved_entities, MAI inventati
- Mai duplicare informazioni, linkare invece
- Tag confidenza inline: `<!-- conf:high -->`, `<!-- conf:medium -->`, `<!-- conf:low -->`
- Inferenze cross-document SEMPRE marcate con `conf:medium` o inferiore
- Niente contenuto effimero nella KB (prezzi, hot take, news di mercato)
- Ogni pagina entity/event ha sezione summary_for_synthesis (100-200 token)
- Lint settimanale: orphan pages, link rotti, contraddizioni, summary mancanti
```

### Modelli per il compile

| Scenario | Modello | Costo stimato/mese |
|----------|---------|---------------------|
| Massima qualità | Claude Sonnet 4.6 via API con prompt caching | 3-8 USD |
| Locale puro | Qwen3 30B-A3B via Ollama | 0, lento ma utilizzabile |
| Entity extraction | Gemma 4 E4B locale | 0 |
| Arbitrato match ambigui | Gemma 4 E4B locale | 0 |
| Plan-pass | Claude Sonnet 4.6 | parte dei 3-8 USD totali |

## Stadio 5: Report

Tre formati in parallelo.

### Daily digest

- 5-10 bullet con item più rilevanti delle ultime 24h
- Generato la mattina alle 7
- Solo top-N per priority score
- Link agli item originali e alle pagine KB toccate
- Marcato come "letto" automaticamente all'apertura dei link

Esempio:

```markdown
# Daily digest 2026-05-13

## LLM e AI
- Anthropic rilascia Claude Opus 4.7 ([source](url), [[kb/events/2026-05-claude-opus-47]])
- Nuovo paper su sparse attention da DeepMind ([source](url), [[kb/methods/sparse-attention-v2]])

## Formula 1
- FastF1 v3.6: dati telemetria meteorologica ([source](url))

## Da leggere quando hai tempo
- Karpathy aggiorna gist su LLM wiki con sezione lint avanzato
```

### Weekly synthesis (input ad altissima densità)

Per evitare l'effetto "Lost in the Middle", l'input NON sono gli item grezzi compilati, ma:

1. Tutte le `summary_for_synthesis` degli **event** creati nella settimana
2. Il **diff** delle **entity** aggiornate (sezioni "caratteristiche correnti" before/after)
3. La lista dei **topic** con maggior attività

Input totale tipico: 10-15k token invece di 50k+. Il modello ragiona su materiale già condensato, output narrativo di qualità superiore a costo inferiore.

```python
async def generate_weekly_synthesis(kb, week_start, week_end):
    events = kb.events.filter(created_between=(week_start, week_end))
    entity_diffs = kb.compute_entity_diffs(week_start, week_end)
    topic_activity = kb.compute_topic_activity(week_start, week_end)

    synthesis_input = {
        "event_summaries": [e.summary_for_synthesis for e in events],
        "entity_diffs": entity_diffs,
        "topic_activity": topic_activity,
        "week": f"{week_start} → {week_end}"
    }

    return await llm.synthesize(
        synthesis_input,
        model="claude-sonnet-4.6",
        instructions=WEEKLY_SYNTHESIS_PROMPT
    )
```

### Topic alerts

Pattern detection sui metadata, non sintesi LLM. Trigger:

- Topic con attività anomala (es. 5+ paper in una settimana su argomento che ne aveva uno al mese)
- Entity menzionata in 3+ event distinti in pochi giorni
- Contraddizioni rilevate dal lint settimanale

Notifica fuori dal digest standard, formato breve.

### Delivery

| Canale | Strumento | Per cosa |
|--------|-----------|----------|
| Email | SMTP a te stesso | Daily digest |
| Obsidian vault | File .md in cartella watched | Tutto, archivio navigabile |
| Telegram | Bot personale | Topic alerts urgenti |
| RSS personale | Feed generato | Per app esterne |

## Stadio 0: Orchestrazione

### Tre livelli di maturità

**V1 (settimana 1-2)**: cron + script Python. Niente orchestrator. Debug a mano, capisci dove sono i problemi veri.

**V2 (mese 2-3)**: APScheduler in un singolo processo Python. Retry, logging strutturato, scheduling sofisticato. Nessun framework esterno.

**V3 (se serve)**: Prefect per Python-first dinamico, Dagster se vuoi asset-based reasoning. Per uso singolo utente, V2 è probabilmente il punto di arrivo.

### Schedule consigliato

```
00:00  cron: ingestion arxiv daily (batch grande notturno)
06:00  cron: ingestion RSS + newsletter
06:30  triage + dedup
07:00  compile (solo high-priority del giorno)
07:15  generate daily digest, send email
*/4h   cron: light ingestion (releases, alerts)
Lun 08:00  weekly synthesis
Dom 22:00  KB lint job (orphan, contraddizioni, link rotti, summary mancanti)
```

## Stack tecnologico

### Locale (sulla tua macchina)

| Layer | Strumento | Note |
|-------|-----------|------|
| Runtime LLM locale | Ollama | API OpenAI-compatible |
| Modello classifier | Gemma 4 E4B | Filtri veloci, schema decente |
| Modello compile locale | Qwen3 30B-A3B | MoE, 3B attivi, agentic decente |
| Modello entity extraction | Gemma 4 E4B | Veloce, zero-shot strutturato |
| Embedding | Qwen3-Embedding-4B | SOTA 2026, MRL support |
| Crawler HTML | Crawl4AI | Locale, JS rendering |
| PDF parser | Marker | Default, GPU-accelerated |
| Storage unificato | **SQLite + sqlite-vec** | Metadati e vettori in transazioni ACID |
| Viewer KB | Obsidian | Graph view, wikilinks, Smart Connections |

### Cloud (API a consumo)

| Layer | Strumento | Costo stimato |
|-------|-----------|---------------|
| Compile primary | Claude Sonnet 4.6 | 3-8 USD/mese con prompt caching |
| Weekly synthesis | Claude Sonnet 4.6 | parte dei 3-8 USD |
| Discovery aggiuntiva | Firecrawl `/search` | 0-5 USD/mese opzionale |
| Fallback web fetch | Jina Reader | Gratuito tier base |

### Storage: sqlite-vec come default obbligatorio

NON tenere SQLite e FAISS separati. Tutto in sqlite-vec:

```sql
-- Schema unificato
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE,
    title TEXT,
    source TEXT,
    date_published TEXT,
    date_ingested TEXT,
    content_hash TEXT,
    triage_score REAL,
    triage_status TEXT,
    compile_status TEXT,
    read_at TEXT  -- null finché non aperto
);

CREATE VIRTUAL TABLE items_vec USING vec0(
    item_id TEXT PRIMARY KEY,
    embedding FLOAT[1024]
);

CREATE TABLE kb_pages (
    path TEXT PRIMARY KEY,
    page_type TEXT,
    title TEXT,
    slug TEXT,
    last_updated TEXT,
    summary_for_synthesis TEXT
);

CREATE VIRTUAL TABLE kb_pages_vec USING vec0(
    path TEXT PRIMARY KEY,
    embedding FLOAT[1024]
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
    operations_json TEXT
);
```

Vantaggi: transazioni ACID, single file, niente sync, niente record orfani.

### Codice Python (dipendenze chiave)

```toml
[project.dependencies]
# ingestion
feedparser = "*"
crawl4ai = "*"
marker-pdf = "*"
arxiv = "*"

# embedding e ml
sentence-transformers = "*"
fastembed = "*"

# llm clients
ollama = "*"
anthropic = "*"

# storage unificato
sqlite-vec = "*"
sqlite-utils = "*"

# orchestration
apscheduler = "*"

# email
mail-parser = "*"
google-api-python-client = "*"

# utility
pydantic = "*"
typer = "*"
rich = "*"
```

## Costi e calibrazione attesa

Volumi tipici per uso personale ben calibrato:

- 20-50 fonti monitorate
- 50-200 item grezzi al giorno
- 10-30 item dopo dedup esatta + semantica
- 3-8 item compilati pienamente nella KB
- 1 daily digest, 1 weekly synthesis

Costo Claude con prompt caching:

- Compile di 5 item/giorno: 0.05-0.15 USD/giorno → 1.5-4.5 USD/mese
- Weekly synthesis: 0.2-0.5 USD → 0.8-2 USD/mese
- **Totale realistico: 3-8 USD/mese**

Senza triage rigoroso, gli stessi volumi arrivano a 50+ USD/mese. La differenza è tutta nel filtro.

## Antipattern da evitare

**Compile libero senza resolution**: l'LLM inventa wikilinks tipo `[[openai-company]]` mentre la pagina è `[[openai]]`. Sempre micro-RAG prima di scrivere.

**Scoring senza normalizzazione**: `social_signal` cannibalizza tutto. Tutti gli input devono finire in [0, 1] prima della combinazione lineare.

**SQLite + FAISS separati**: la via più veloce per avere record orfani. sqlite-vec non è opzionale.

**Sintesi settimanale su item grezzi**: 50k+ token, "lost in the middle", costi alti. Passare solo summary_for_synthesis e diff.

**Build dal compile in giù**: aggrega e fai digest senza LLM prima. Aggiungi triage quando hai dati sul rumore reale.

**Mettere tutto nella KB**: notizie effimere muoiono nel digest. Nella KB solo quello che ha valore a 6 mesi.

**Non tracciare letture**: `read_at` nei metadati. Digest mostra solo non-letti.

**Compile senza lint**: allucinazioni si cristallizzano nelle pagine e propagano via link. Lint settimanale obbligatorio.

**Modelli piccoli per compile vero**: Gemma 4 E4B su task agentico fallisce silenziosamente. Minimo 26B-MoE o Claude API.

**Troppe fonti**: 200 fonti = 200 rumori. 15 fonti curate = 80% del valore.

## Roadmap implementativa

### Settimana 1: V1 minima

- Repo Python con struttura cartelle
- `feedparser` su 10 RSS principali
- Salvataggio markdown con frontmatter in `sources/ingested/YYYY-MM-DD/`
- Schema sqlite-vec iniziale
- Dedup su URL e content_hash
- Daily digest base (lista item) via email
- Cron alle 7:00

Già qui risolvi l'80% di "cosa è uscito oggi".

### Settimana 2-3: Triage

- Setup Ollama + Gemma 4 E4B
- Embedding con Qwen3-Embedding-4B
- Dedup semantica con soglia 0.85
- Classifier rilevanza zero-shot
- Priority scoring con weight profiles per source type
- Digest ordinato per priorità

### Settimana 4-6: KB e Compile

- Setup cartelle KB con CLAUDE.md
- Schema completo sqlite-vec (items, kb_pages, aliases)
- Entity extraction locale (Gemma 4 E4B)
- Resolution via vector search
- Plan-pass via Claude API con Pydantic schema
- Apply deterministico con template
- Transazioni atomiche
- Viewing in Obsidian

### Settimana 7-8: Synthesis e lint

- Generazione `summary_for_synthesis` nel compile
- Weekly synthesis su input condensato
- Lint job (orphan, contraddizioni, link rotti, summary mancanti)
- Topic alerts su pattern detection
- Calibrazione soglie sui dati raccolti

### Mese 3+: ottimizzazioni

- PDF parser per arxiv (Marker)
- Fonti aggiuntive
- Telegram bot per alerts urgenti
- Migrazione a Prefect/Dagster solo se serve davvero

## Decisioni di design da fissare prima dell'implementazione

1. **KB unica o multipla?** Una unica con cartelle per topic è più semplice e permette cross-references naturali. Multiple solo se i domini sono completamente disgiunti.

2. **Storico**: source markdown grezzi archiviabili dopo 90 giorni. KB permanente. Digest tenuto 12 mesi.

3. **Privacy / self-hosting puro?** Possibile usando solo Gemma/Qwen locali per il compile. Accettare perdita qualità 20-40% rispetto a Claude.

4. **Multilingua**: italiano + inglese gestiti bene da Qwen3 e BGE-M3. Per altre lingue verificare modello per modello.

5. **Calibrazione soglie**: prime 1-2 settimane in modalità "log only" senza filtrare, per raccogliere dati reali su distribuzioni di score e calibrare le soglie sui propri dati invece che su default.

6. **Backup**: il file `kb.db` (sqlite-vec) e la cartella `kb/` vanno in backup. Tutto il resto (`sources/ingested/`) è ricostruibile dalle fonti.
