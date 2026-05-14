# Pipeline locale per discovery, RAG e report quotidiano di novità (V2)

**Data:** maggio 2026
**Obiettivo:** progettare una pipeline che cerchi novità su un ambito specifico, scarichi i contenuti (HTML, PDF), li converta in Markdown, costruisca un RAG e produca quotidianamente un report di novità e idee derivate. Privilegio massimo al locale (first-class citizen) ed efficienza operativa, con scalabilità modulare per futuri scenari di servizio.

## Indice

1. Architettura generale a 6 stadi
2. Punti dolenti veri da considerare a monte
3. Stack di frontiera dettagliato per ogni stadio
4. Tabella riassuntiva dello stack consigliato
5. Note finali e errori comuni

## 1. Architettura generale a 6 stadi

### Stadio 1: Discovery (cosa cercare)

Si definiscono due famiglie di input:

- **Sorgenti note**: blog, arXiv, GitHub trending, newsletter, subreddit, account social. Per queste si usa RSS dove disponibile, altrimenti scraping mirato.
- **Query aperte**: parole chiave per ricerca web esplorativa.

Output dello stadio: lista di URL candidati con metadati (fonte, data, titolo).

### Stadio 2: Deduplication e filtering a 3 livelli

Il filtraggio pre-LLM è vitale per abbattere i costi e il rumore. Si esegue in tre fasi progressive:

1. **URL canonicalization**: rimozione di parametri UTM, query string irrilevanti e risoluzione redirect.
2. **Text Hashing**: estrazione rapida (es. Trafilatura) e applicazione di SimHash a 64 bit. Una distanza di Hamming < 3 identifica syndication e quasi-duplicati.
3. **Semantic Near-Duplicate**: per i sopravvissuti, check via cosine similarity (> 0.95) contro chunk recenti già indicizzati, per catturare la stessa notizia riscritta da testate diverse.

### Stadio 3: Fetch e conversione dinamica

- **HTML**: estrazione del contenuto pulito con rimozione di menu, footer, ads.
- **PDF**: routing dinamico basato su un'euristica fast-path (testo puro) / slow-path (layout complesso e tabelle).

Output: file .md organizzati per data e fonte.

### Stadio 4: Chunking e embedding

Si spezzano i documenti con criteri semantici. Generazione di embedding a dimensionalità controllata e caricamento nel vector store. I metadati salvati per ogni chunk includono: fonte, data, URL, titolo.

### Stadio 5: Synthesis layer (Topic Discovery & Report)

Due strade complementari:

- **Report ricorrente**: si prendono i chunk delle ultime 24 ore. Per evitare la maledizione della dimensionalità su batch piccoli, si applicano algoritmi di topic modeling specializzati (es. BERTopic) per raggruppare i documenti ed estrarre keyword, guidando la generazione del report strutturato.
- **RAG interattivo**: interrogazione dello storico via vector store ("cosa è uscito sul tema X negli ultimi 3 mesi?").

### Stadio 6: Idea generation (Opzionale)

Prende il report del giorno, lo incrocia col contesto dei propri progetti e chiede a un LLM "quali novità sono attivabili?". Output: 3-5 idee concrete con razionale.

### Orchestrazione

Esecuzione OS-native schedulata alle 7:00 del mattino. Output: Markdown in una cartella, email, o push su Notion/Obsidian.

## 2. Punti dolenti veri da considerare a monte

**Il rumore è il problema numero uno.** Il 70% di quello che si scarica sarà ripetitivo o irrilevante. La pipeline di deduplicazione a 3 livelli è il firewall principale del sistema.

**Il drift dei temi.** Dopo un mese il sistema diventa noioso. Soluzione: ruotare le query, aggiungere query random settimanali su sottotemi adiacenti.

**I colli di bottiglia sui PDF.** Analizzare il layout costa tempo e compute. Mai usare parser pesanti basati su reti neurali di default se serve solo un abstract testuale.

## 3. Stack di frontiera dettagliato per ogni stadio

### 3.1 Discovery

**SearXNG** in Docker (con Redis per rate-limiting). Aggrega oltre 70 motori senza tracking o ads, API JSON, chiavi non necessarie. Per l'accademia: arXiv API, OpenAlex, Semantic Scholar.

### 3.2 Fetch ed estrazione HTML

**Trafilatura**. Output Markdown nativo, strippa ads e boilerplate, estrae testo e metadati. Fallback per siti JS-heavy: Playwright headless.

### 3.3 Conversione PDF: Routing Dinamico

Approccio "Fast path default, slow path on trigger":

1. **PyMuPDF4LLM** (Default): velocissimo, text-layer only. Estrae abstract e conclusioni istantaneamente.
2. **Heuristics trigger**: tramite Python, si valuta l'output.
   - Se il testo ha < N caratteri per pagina (PDF scansionato) → passa a **Marker** con OCR.
   - Se contiene pattern tabellari rotti ("│", "┃", "┌") o alta densità numerica → passa a **Docling** per la ricostruzione semantica delle tabelle.

### 3.4 e 3.5 Chunking, Embedding e Topic Discovery

- **Embedder**: **Qwen3-Embedding-4B** (tramite Ollama o sentence-transformers). Supporta Matryoshka Representation Learning: permette di estrarre embedding a 256 o 512 dimensioni mantenendo la qualità. Abbassa drasticamente i costi computazionali e mitiga i problemi geometrici negli spazi ad alta dimensione.
- **Topic Discovery (Daily Batch)**: **BERTopic**. Ottimizzato per raggruppare l'infornata giornaliera, integra internamente UMAP + HDBSCAN + c-TF-IDF, restituendo cluster stabili e keyword chiare per la sintesi.

### 3.6 Vector store locale

**LanceDB (Embedded)**. La scelta local-first per eccellenza. Gira nello stesso processo Python della pipeline, zero container Docker, zero servizi da esporre, i dati sono salvati in file .lance facilmente backuppabili.

*(Nota: Qdrant rimane l'opzione di upgrade consigliata nel caso in futuro si debba esporre la pipeline come servizio RAG multi-tenant).*

### 3.7 Reranker locale

**BGE-reranker-v2-m3** (o **Jina Reranker v2** per maggiore velocità). Aggiunto dopo il retrieval iniziale nel RAG storico, alza la precisione del 15-30%.

### 3.8 LLM locale per RAG interattivo

- Top/MoE: **Qwen3 30B-A3B** o **Llama 4 Scout**.
- Medium/Consumer: **Gemma 3 27B** o **Qwen3 14B** (quantizzati Q4_K_M via Ollama).

### 3.9 Inference engine locale

**Ollama** per semplicità operativa e API OpenAI-compatible, interfacciato internamente con llama.cpp.

### 3.10 Orchestrazione OS-Native

**systemd timer** + **systemd service**. Configurazione nativa su distribuzioni Linux. Esegue lo script Python isolato nel suo ambiente, gestisce retry, crash e logging (tramite journalctl) con letteralmente zero dipendenze esterne o database aggiuntivi da manutenere.

*(Fallback: GitHub Actions con cron se si preferisce delocalizzare il trigger).*

### 3.11 Synthesis layer (Report)

**Ibrido (raccomandato)**: locale per tutto il preprocessing, ma **Claude Sonnet / GPT-5.5 via API** per la sintesi narrativa del report finale. Pochi centesimi al giorno per garantire un output qualitativamente superiore, stabile e meno prono ad allucinazioni logiche rispetto a un 14B locale.

## 4. Tabella riassuntiva dello stack consigliato

| Stadio | Tecnologia | Note |
|---|---|---|
| Discovery | SearXNG + RSS + API aperte | |
| Deduplicazione | Canonical URL + SimHash + Embedding | Pipeline a 3 livelli d'intensità |
| HTML extraction | Trafilatura | Standard de facto |
| PDF extraction | PyMuPDF4LLM (Default) | Routing dinamico a Docling/Marker su trigger |
| Embedding | Qwen3-Embedding-4B | Uso Matryoshka a 256/512 dim. |
| Clustering/Topic | BERTopic | Perfetto per il batch daily |
| Vector store | LanceDB (embedded) | Zero container. (Qdrant per futuri scenari B2B) |
| Reranker | BGE-reranker-v2-m3 | |
| LLM interattivo | Qwen3 14B/30B via Ollama | Per interrogare lo storico |
| LLM sintesi | API esterne (Claude/GPT) | Qualità massima per l'output finale |
| Orchestrazione | systemd timer (OS-native) | Robusto, zero overhead infrastrutturale |

## 5. Note finali ed errori comuni

**L'embedder è il vincolo a monte.** Se si sbaglia l'embedder, nessun reranker compensa.

**L'over-engineering infrastrutturale uccide i side-project.** LanceDB e systemd minimizzano i pezzi in movimento. Meno server da far girare significa meno rotture silenziose.

**Investire tempo nel filtering, non nel prompt.** Un prompt mediocre su contenuto de-duplicato e filtrato produce report buoni; un super-prompt su immondizia produce report confusi.
