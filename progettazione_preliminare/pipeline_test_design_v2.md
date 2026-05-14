# Progettazione dei test per la pipeline locale news/RAG (V2)

**Data:** maggio 2026
**Contesto:** validazione della pipeline V2 (discovery → dedup → fetch → chunking → embedding → topic → RAG → sintesi) prima dell'implementazione completa.
**Ambito tematico di test:** AI/ML tooling (sorgenti: arXiv cs.AI/cs.LG, blog tech come Hugging Face blog, Anthropic, Simon Willison, Hacker News).
**Ambiente:** Pop_OS! locale, tutto in venv Python isolato.

**Changelog V2:** soglia cosine derivata via ROC e per-dimensionalità (era hardcoded), espansione dataset PDF a 20-25 documenti con introduzione di PDF ibridi e routing page-level (era document-level su 8 PDF), introduzione di LLM-as-a-judge incrociato per il reranker con esclusione esplicita del chunking (era tutto giudizio umano), note operative sulla Milestone 2 integrate nei test (erano fuori documento).

## Indice

1. Principi guida del testing
2. Dataset di prova condiviso
3. Test isolati per componente (con criteri di accettazione)
4. Test end-to-end
5. Ordine di esecuzione e milestone
6. Metriche, logging e tracking risultati

## 1. Principi guida del testing

**Test isolati prima, e2e dopo.** Ogni stadio si valida con input fissato e output osservabile. Solo quando i singoli pezzi passano si compone la pipeline completa.

**Riproducibilità sopra automazione.** Tutti i test partono dallo stesso dataset fisso (vedi sezione 2) salvato su disco. Niente rete durante l'esecuzione dei test (eccetto i test discovery dichiarati).

**Misurare, non solo eseguire.** Ogni test ha almeno una metrica numerica (tempo, accuracy, recall, dimensione output) loggata. "Funziona" non basta, serve un numero confrontabile tra le scelte tecnologiche alternative.

**Criteri di accettazione espliciti.** Per ogni test, definire prima quale soglia rende il pezzo "promosso" in pipeline. Senza soglia, ogni risultato sembra accettabile.

**Niente tuning durante i test isolati.** Si usano i default delle librerie. Il tuning si fa dopo l'e2e, solo dove emergono colli di bottiglia reali.

**Anti-circolarità nei test automatizzati.** L'LLM-as-a-judge è permesso solo se l'LLM judge è diverso dall'LLM usato nello stesso stadio della pipeline che si sta validando. Mai testare un componente con la sua stessa funzione di valutazione.

## 2. Dataset di prova condiviso

Si costruisce un fixture set salvato in `data/fixtures/` da usare in tutti i test. Approccio: prendere campioni reali oggi, congelarli su disco, riusarli sempre.

**Composizione minima:**

- 20 URL HTML di blog tech (Hugging Face, Anthropic news, Simon Willison, lobste.rs, Hacker News selezionati a mano).
- 20-25 PDF totali, suddivisi in:
  - **8 PDF "puri" arXiv**: text-dominant, struttura accademica standard (abstract, sections, references).
  - **3 PDF patologici**: uno scansionato (no text layer), uno con tabelle finanziarie complesse, uno multi-colonna accademico.
  - **8-10 PDF ibridi** (categoria nuova V2): paper discorsivi con UNA tabella critica, tech report con figure incorporate, whitepaper con codice misto a prosa, slide convertite in PDF, report con grafici di cui serve il dato. Sono i casi reali in cui il routing dinamico deve dimostrare il suo valore.
- 5 casi noti di syndication: la stessa notizia pubblicata su 2-3 siti diversi (es. annuncio modello ripreso da TechCrunch + The Verge + blog originale).
- 5 feed RSS di test (HF blog RSS, arXiv cs.AI RSS, blog personali).

**Struttura su disco:**

```
data/fixtures/
├── html/          (20 file .html salvati offline)
├── pdf/
│   ├── pure/      (8 PDF arXiv standard)
│   ├── pathological/ (3 PDF patologici)
│   └── hybrid/    (8-10 PDF ibridi)
├── rss/           (5 file .xml snapshot dei feed)
├── syndication/   (gruppi di 2-3 URL/HTML che parlano della stessa news)
└── manifest.json  (mapping URL → file locale, data raccolta, fonte, expected_routing)
```

Il manifest serve come "ground truth" per dedup, attribuzione e routing PDF (include, per ogni PDF ibrido, la lista delle pagine "problematiche" attese, generata a mano).

## 3. Test isolati per componente

Ogni test ha lo stesso schema: **Obiettivo**, **Input**, **Output atteso**, **Metrica**, **Criterio di accettazione**, **Note operative**.

### 3.1 Discovery (SearXNG + RSS + arXiv API)

**Obiettivo:** verificare che le tre fonti restituiscano risultati coerenti, deduplicabili, con metadati sufficienti (URL, titolo, data).

**Input:** una query test stabile, es. `"retrieval augmented generation"`.

**Output atteso:** lista unificata di candidati con schema `{source, url, title, published_at, snippet}`.

**Metrica:**
- Numero di risultati per fonte.
- Percentuale di risultati con `published_at` valido.
- Numero di duplicati cross-source (stesso URL).

**Criterio di accettazione:**
- SearXNG risponde in < 5s, restituisce ≥ 10 risultati.
- arXiv API risponde in < 3s, restituisce ≥ 5 risultati con data.
- RSS parsing su 5 feed riesce per almeno 4/5.
- Almeno 80% dei risultati ha data parsabile.

**Note operative:**
- SearXNG va avviato a parte in Docker prima del test (porta 8080). Senza Docker, il test SearXNG viene skippato e si testa solo il path RSS + arXiv.
- Test va lanciato una volta con rete attiva, poi i risultati si salvano in `data/fixtures/discovery_snapshot.json` per riuso offline.

### 3.2 Deduplication a 3 livelli

**Obiettivo:** verificare che ogni livello catturi i duplicati che gli competono, senza falsi positivi sul resto.

**Input:** il set syndication (5 gruppi noti) mescolato con 20 articoli unici.

**Output atteso:** classificazione finale "unique" / "duplicate of X" per ogni articolo.

**Test in 3 sotto-test:**

**3.2.a — URL canonicalization**
- Input: 10 URL con UTM/redirect noti.
- Output: URL canonical previsto a mano.
- Metrica: % URL canonicalizzati correttamente.
- Soglia: 100% (è deterministico, deve essere perfetto).

**3.2.b — SimHash testuale**
- Input: 5 coppie syndication + 5 coppie articoli diversi sullo stesso tema.
- Output: per ogni coppia, Hamming distance.
- Metrica: separazione tra distribuzione "stesso articolo" e "stesso tema, articoli diversi".
- Soglia: tutti i syndication veri devono avere Hamming < 5, tutti i "tema simile ma diverso" Hamming > 10. Se le distribuzioni si sovrappongono, soglia di Hamming va ricalibrata.

**3.2.c — Near-duplicate semantico (revisione V2)**
- Input: 5 coppie syndication "riscritte" (stessa notizia, parole diverse) + 5 coppie tema simile + 20 coppie "non duplicate" come baseline negativa.
- Output: cosine similarity tra embedding di tutte le coppie.
- **Metrica V2: calibrazione via ROC, non soglia fissa.**
  - Si tracciano le distribuzioni di similarity per coppie duplicate vs non-duplicate.
  - Si calcola la curva ROC.
  - Si sceglie la soglia ottimale via Youden's J (sensitivity + specificity - 1 massimizzato), oppure si fissa al punto operativo "recall > 95%" se la priorità è non perdere duplicati.
  - La calibrazione si fa **separatamente per ogni dimensionalità Matryoshka** (256, 512, 1024 dim), perché la topologia dello spazio vettoriale cambia.
- **Output:** file `config/dedup_thresholds.json` con schema:
  ```
  {
    "cosine_threshold": {
      "256": 0.89,
      "512": 0.91,
      "1024": 0.93
    },
    "calibration_date": "...",
    "fixture_set_version": "..."
  }
  ```
- **Criterio di accettazione:**
  - AUC ≥ 0.90 su tutte le dimensionalità testate.
  - Se AUC < 0.85 a una certa dimensionalità, quella dimensionalità non è utilizzabile per dedup semantico, va escluso dalla pipeline o si torna a 1024.
  - Soglia esternalizzata, mai hardcoded nel codice.

**Note operative:**
- Quando si cambia embedder o dimensionalità Matryoshka in produzione, il test 3.2.c va rilanciato e il file di config aggiornato. Questo deve essere documentato come precondizione di deploy.
- Il dominio AI/ML è particolarmente sfidante perché i paper si assomigliano molto tra loro: le distribuzioni potrebbero essere molto sovrapposte. In quel caso, è meglio accettare AUC più bassa e operare a recall fisso piuttosto che a F1 massimo.

### 3.3 Trafilatura (HTML extraction)

**Obiettivo:** verificare qualità di estrazione su 20 URL HTML reali, e identificare casi dove fallisce.

**Input:** 20 HTML salvati in `data/fixtures/html/`.

**Output atteso:** 20 file .md + metadati JSON.

**Metrica:**
- % di file in cui il titolo è estratto correttamente (confronto con manifest).
- % di file in cui la data è estratta correttamente.
- Rapporto medio `len(markdown) / len(html)` (indicatore di boilerplate removal).
- Numero di file in cui l'output è vuoto o < 200 caratteri (failure).

**Criterio di accettazione:**
- Titolo corretto su ≥ 18/20.
- Data corretta su ≥ 15/20.
- Zero output vuoti su contenuti che a occhio hanno testo.

**Note operative:**
- I siti JS-heavy noti (es. dashboard, single-page apps) vanno marcati a priori nel manifest come "expected_js_fallback": permette di sapere se servirà Playwright o no.

### 3.4 PDF routing dinamico (revisione V2: page-level su dataset esteso)

**Obiettivo:** validare che il routing scelga il parser giusto **a livello di pagina, non di documento**, e che il fast-path funzioni davvero veloce sui PDF puri.

**Input:** 20-25 PDF distribuiti su pure / patologici / ibridi (vedi sezione 2).

**Cambio architetturale rispetto a V1:** il routing non è più document-level ("questo PDF va a Docling o no") ma **page-level** ("queste pagine vanno a Docling, le altre stanno con PyMuPDF4LLM"). Per i PDF ibridi questo è cruciale: un paper di 15 pagine con UNA tabella critica al p.12 non deve passare interamente per Docling, costa 30 secondi inutili. Si processa con PyMuPDF4LLM tutto il documento, l'euristica identifica le pagine sospette, solo quelle vengono rilavorate con Docling e ricomposte nel markdown finale.

**Test in 3 sotto-test:**

**3.4.a — PyMuPDF4LLM da solo, page by page**
- Misura: tempo medio per pagina, lunghezza testo estratto per pagina, presenza di pattern tabellari rotti per pagina.
- Soglia: < 0.5s/pagina su CPU per pagine non scansionate.

**3.4.b — Euristica di routing page-level**
- Input: l'output per pagina di PyMuPDF4LLM su tutti i PDF.
- Output atteso per ogni pagina: classificazione `{fast_ok, needs_ocr, needs_table_parser}`.
- Confronto: classificazione manuale page-by-page (gold standard fatto a mano nel manifest, sezione `expected_routing`).
- Metrica: accuracy classificazione a livello di pagina + accuracy di "ricostruzione documento" (un PDF è "correttamente routed" se TUTTE le sue pagine sono classificate giuste).
- Soglia: accuracy page-level ≥ 90%, accuracy document-level ≥ 75% sul subset ibrido.

**3.4.c — Ricomposizione del markdown finale**
- Input: PDF ibridi processati con routing misto (alcune pagine PyMuPDF, alcune Docling).
- Output: file .md unico per PDF, con ordine pagine corretto e tabelle integrate dove servono.
- Metrica: ispezione visiva su 3-5 PDF ibridi rappresentativi. Le tabelle critiche compaiono nel markdown? L'ordine è preservato? Ci sono duplicazioni di testo (pagina processata due volte)?
- Soglia: 0 errori di ordine, 0 duplicazioni, tabelle presenti dove attese.

**Note operative:**
- Docling e Marker NON vanno installati in fase di Milestone 1, basta validare che l'euristica scelga di chiamarli al momento giusto. Si installa Docling solo quando il routing dice di farlo, per non scaricare 2GB di modelli inutilmente.
- Il caso "ibrido" è dove la pipeline mostra il proprio valore reale. Se il routing fallisce qui, la pipeline diventa o lenta (tutto Docling) o povera (tutto PyMuPDF e perdi le tabelle). Non è un test secondario.

### 3.5 Chunking

**Obiettivo:** confrontare 2-3 strategie di chunking su un set fisso per scegliere il default.

**Input:** 5 documenti .md di varia lunghezza (1 paper, 2 blog lunghi, 2 articoli brevi).

**Strategie da testare:**
- Fixed-size (es. 512 token, overlap 50).
- Markdown header splitter (struttura nativa).
- Semantic chunking (split su cambio di similarity).

**Metrica:**
- Numero di chunk per documento.
- Distribuzione lunghezze chunk.
- Test qualitativo: 5 query di test, retrieval top-3, valutazione "il chunk risponde alla query?" (sì/no a mano).

**Criterio di accettazione:**
- Almeno una strategia ha hit rate ≥ 4/5 sulle query di test.
- Lunghezze chunk distribuite ragionevolmente (no chunk da 5 caratteri o da 10k).

**Esclusione esplicita V2: NO LLM-as-a-judge per questo test.** Il chunking determina quale contesto l'LLM riceve. Se un LLM giudica i chunk, sta valutando "questo chunk è quello che io vorrei per rispondere?", il che premia chunk simili a quelli che l'LLM ha visto in training, non chunk effettivamente utili per il dominio. Il test resta umano: 30 minuti di lavoro, una volta sola, su 5 query rappresentative scritte a mano. Investimento minimo per evitare bias di valutazione.

**Note operative:**
- Le 5 query di test e le loro risposte attese vanno salvate in `data/fixtures/chunking_queries.json` per riuso quando si rivaluterà il chunking in futuro.

### 3.6 Embedding (Qwen3-Embedding-4B + Matryoshka)

**Obiettivo:** verificare che il modello giri localmente, che le dimensioni Matryoshka producano embedding validi a 256/512/1024, e misurare il throughput.

**Input:** 100 chunk dal set di test (dopo chunking).

**Test in 3 sotto-test:**

**3.6.a — Throughput**
- Metrica: chunk/secondo su batch da 32, su CPU e (se disponibile) GPU.
- Soglia: ≥ 5 chunk/s su CPU mid-range, ≥ 50 chunk/s su GPU consumer.

**3.6.b — Qualità Matryoshka**
- Confronto: top-5 retrieval per 10 query, usando embedding a 256, 512, 1024 dim.
- Metrica: % di overlap tra top-5 a 1024 e top-5 a 256/512.
- Soglia: overlap ≥ 4/5 a 512 dim, ≥ 3/5 a 256 dim. Se 256 dà overlap ≥ 4/5, si può usare a 256 in produzione (risparmio storage).

**3.6.c — Determinismo**
- Stesso input due volte → embedding identici.
- Soglia: cosine = 1.0 (a meno di errori floating point trascurabili).

**Note operative:**
- Modello scaricato via Ollama o sentence-transformers, salvato in cache locale.
- Tracciare la versione esatta del modello nel log dei test.
- I risultati di 3.6.b determinano direttamente quale dimensionalità si usa in produzione, e quindi quale calibrazione di 3.2.c è quella "attiva". I tre test sono interconnessi e vanno rilanciati insieme se cambia uno qualsiasi degli elementi.

### 3.7 LanceDB (vector store)

**Obiettivo:** verificare scrittura, lettura, filtering e persistenza su disco.

**Input:** i 100 chunk embeddati dal test 3.6.

**Test:**
- Insert 100 chunk con metadati `{source, date, url, title}`.
- Query semantica top-10 senza filtri.
- Query semantica top-10 con filtro `date >= today-7d`.
- Query semantica con filtro su source.
- Riavvio del processo + riapertura DB + query: i dati persistono.

**Metrica:**
- Tempo insert/100 chunk.
- Tempo query top-10 (target < 50ms).
- Dimensione file .lance su disco.

**Criterio di accettazione:**
- Tutte le operazioni completano senza errori.
- Filtering metadata funziona correttamente (verificato controllando manualmente i top-10 restituiti).
- Persistenza confermata.

### 3.8 BERTopic (topic modeling)

**Obiettivo:** verificare che su un mini-batch (~50-100 documenti, simulando un giorno reale) BERTopic produca topic sensati e stabili.

**Input:** 80 documenti embedati dal test set.

**Metrica:**
- Numero di topic generati (target 5-15 per 80 doc; se > 30 o < 3, c'è un problema di parametrizzazione).
- Numero di "outlier" (topic -1): se > 50%, il batch è troppo piccolo o eterogeneo.
- Lettura a mano delle top-5 keyword per topic: hanno senso? (giudizio soggettivo, ma necessario)
- Stabilità: eseguire BERTopic 3 volte con stesso input. Confrontare i cluster ottenuti (Adjusted Rand Index tra le tre run).

**Criterio di accettazione:**
- Numero topic in range plausibile.
- ARI tra run ≥ 0.7 (stabilità accettabile).
- Almeno 4/5 topic hanno keyword leggibili e coerenti al lettore umano.

**Note operative:**
- Se la stabilità è bassa, fissare `random_state` in UMAP e in HDBSCAN. Documentare nel codice di produzione.

### 3.9 Reranker (BGE-reranker-v2-m3) — revisione V2 con LLM-as-a-judge incrociato

**Obiettivo:** verificare che il reranker migliori effettivamente il ranking sui top-K retrieval.

**Input:** 5 query test scritte a mano + top-20 chunk da LanceDB per ciascuna.

**Generazione dei giudizi di rilevanza (revisione V2):**

Invece di valutare a mano 100 coppie (5 query × 20 candidati), si usa un approccio ibrido:

1. **Gold set umano minimo (calibrazione)**: 1 sola query con 20 candidati valutati a mano (rilevanza 0/1/2). Costa 15 minuti, serve come "calibratore del judge".
2. **LLM-as-a-judge incrociato per le altre 4 query**: si usa un LLM **diverso** da quello previsto nello stadio di sintesi della pipeline. Esempio: se la pipeline usa Claude Sonnet per il report finale, il judge è GPT-5.5 o Gemini. Mai lo stesso modello.
3. **Validazione del judge sul gold set**: prima di usare il judge sulle 4 query automatiche, lo si testa sulla query gold-umana. Se l'agreement (Cohen's kappa o accuratezza ordinale) tra giudice umano e LLM è < 0.6, il judge non è affidabile per questo dominio e si torna al giudizio umano completo.
4. **Revisione delle anomalie**: si controllano a mano solo i casi in cui il judge dà giudizi estremi (rilevanza 2 o 0) che cambiano il ranking dopo rerank. Tipicamente 5-10 casi per run.

**Metrica:**
- nDCG@5 e MRR prima e dopo il rerank.
- Tempo medio rerank (target < 500ms per 20 candidati).
- Agreement kappa tra LLM judge e umano sul gold set.

**Criterio di accettazione:**
- Miglioramento medio nDCG@5 ≥ 10% (su 5 query è indicativo, non statistico).
- Se il miglioramento è < 5%, il reranker non è ancora un must-have, si rimanda.
- Kappa LLM-vs-umano ≥ 0.6 sul gold set, altrimenti il numero sopra è inaffidabile.

**Note operative:**
- I giudizi LLM-generati vanno salvati in `data/fixtures/reranker_judgments_<judge_model>_<date>.json`, per audit e riproducibilità.
- Vincolo di anti-circolarità da rispettare nel codice: il modulo `reranker_eval.py` deve esplicitamente rifiutare di usare lo stesso modello configurato come sintetizzatore. È una guardia esplicita, non una linea guida.

### 3.10 LLM locale via Ollama (per RAG interattivo)

**Obiettivo:** verificare che il modello scelto (Qwen3 14B o simile) risponda correttamente a query RAG con contesto fornito.

**Input:** 5 query + top-5 chunk di contesto per ciascuna.

**Metrica:**
- Tempo prima token, tempo totale risposta.
- Lunghezza risposta.
- Lettura a mano: risposta usa il contesto fornito? Cita correttamente? Allucina?

**Criterio di accettazione:**
- Risposta in < 30s su hardware locale (per modello 14B Q4).
- Su 5/5 query, la risposta è ancorata al contesto (no allucinazioni evidenti).
- Su 4/5 query, la risposta è qualitativamente utile.

**Note operative:**
- Test di confronto rapido: stesse 5 query + contesto inviate anche a Claude Sonnet via API. Differenza di qualità percepita giustifica o no il keep-local della sintesi.
- Questo test va ripetuto ogni 2-3 mesi al variare dei modelli locali, per decidere se spostare la sintesi finale in locale.

### 3.11 LLM cloud per sintesi (API esterna)

**Obiettivo:** validare che il prompt di sintesi del report funzioni con un cluster BERTopic + chunk reali.

**Input:** output reale di BERTopic dal test 3.8 + 3-5 chunk per topic.

**Metrica:**
- Lunghezza report.
- Tempo generazione.
- Costo stimato (token in/out × pricing).
- Lettura a mano: il report cattura le novità reali presenti nei chunk? Inventa cose?

**Criterio di accettazione:**
- Report leggibile, strutturato per topic.
- Zero invenzioni evidenti (no claim non presenti nei chunk).
- Costo per run < 0.10 USD.

## 4. Test end-to-end

Una volta che tutti i test isolati passano, si compone la pipeline completa su un mini-batch reale.

**Setup:**
- Query: 3 query rappresentative AI/ML (es. "RAG techniques", "long context LLM", "AI agents").
- Discovery limitato: max 10 risultati per query, 30 totali.
- Limite pagine PDF: prime 5 pagine di ogni paper (per non far esplodere il tempo).
- Tutto il resto come pipeline V2 reale.

**Obiettivo:** verificare che la catena giri senza errori, in tempo ragionevole, e produca un report finale leggibile.

**Metrica:**
- Tempo totale end-to-end.
- Numero di documenti raccolti / sopravvissuti a dedup / chunk generati / topic estratti.
- Dimensione del report finale.
- Errori intermedi loggati.

**Criterio di accettazione:**
- Pipeline completa senza errori non gestiti.
- Tempo totale < 15 minuti per 30 documenti.
- Report finale prodotto, leggibile, con almeno 3 topic e 5 osservazioni.

**Casi di stress da provare dopo il primo successo:**
- Far girare la pipeline 3 giorni di fila e verificare che la dedup catturi le ripetizioni cross-giorno.
- Inserire artificialmente un duplicato sintetizzato (stesso paper riproposto) e verificare che venga scartato.
- Far girare con SearXNG offline: il sistema deve degradare gracefully (RSS + arXiv come fallback) senza crashare.

## 5. Ordine di esecuzione e milestone

I test non si scrivono tutti insieme. Si seguono 3 milestone, ognuna con un Definition of Done chiaro e una stima realistica di cicli di calibrazione.

### Milestone 1 — Ingestion pulito (settimana 1, 1-2 cicli di calibrazione)

Obiettivo: avere un'ingestion che produce .md puliti, deduplicati, salvati su disco.

Test da completare:
- 3.1 Discovery
- 3.2 Dedup (tutti e 3 i livelli, con calibrazione ROC su 3.2.c per la dimensionalità Matryoshka scelta)
- 3.3 Trafilatura
- 3.4 PDF routing page-level (solo PyMuPDF4LLM + euristica, senza Docling)

DoD: 30 articoli su disco, zero duplicati, metadati completi, leggibili a occhio.

**Stima cicli:** bassa. Quasi tutta logica deterministica (URL, SimHash, regole). Le poche soglie si calibrano una volta sola sul fixture set.

### Milestone 2 — RAG batch funzionante (settimana 2-4, 4-6 cicli di calibrazione)

**Questa è la milestone che richiede più tempo, perché ha 4 parametri interdipendenti che si influenzano a vicenda:**

1. Strategia di chunking (3 alternative)
2. Dimensionalità Matryoshka (256/512/1024)
3. Parametri BERTopic (min_topic_size, nr_topics, UMAP n_neighbors)
4. Prompt di sintesi

Non si ottimizzano insieme. Si usa la **strategia a "singola variabile attiva"**:

- **Fase 2a (settimana 1)**: fissare tre parametri ai default V2 (chunking semantic, Matryoshka 512, BERTopic default) e iterare solo sul prompt di sintesi.
- **Fase 2b (settimana 2)**: con prompt stabilizzato, far girare la pipeline ogni giorno per 7-10 giorni per osservare qualità reale del report (il segnale è debole, serve volume temporale).
- **Fase 2c (settimana 3-4, opzionale)**: solo se la qualità è insufficiente, toccare uno degli altri tre parametri, isolato.

Test da completare:
- 3.5 Chunking
- 3.6 Embedding
- 3.7 LanceDB
- 3.8 BERTopic
- 3.11 LLM cloud per sintesi

DoD: report .md generato automaticamente a fine pipeline, qualitativamente leggibile su 7+ giorni consecutivi di esecuzione.

**Avvertenza esplicita:** non procedere alla Milestone 3 prima di aver osservato la pipeline girare per almeno 7 giorni reali. La qualità del report è un giudizio soggettivo che diventa attendibile solo su volume.

### Milestone 3 — RAG interattivo + raffinamenti (settimana 5+, 2-3 cicli di calibrazione)

Obiettivo: interrogazione storica + reranker + opzionale Docling per PDF complessi.

Test da completare:
- 3.4 ripetuto con Docling/Marker installati, validando il routing page-level con i parser pesanti
- 3.9 Reranker con LLM-as-a-judge incrociato
- 3.10 LLM locale via Ollama

DoD: si può fare una query sullo storico e ricevere risposta ancorata ai documenti.

## 6. Metriche, logging e tracking risultati

**Logging:** ogni test logga in un JSON appendabile in `data/test_runs/YYYY-MM-DD.jsonl`:

```
{
  "test_id": "3.6.b",
  "timestamp": "...",
  "input_size": 100,
  "metrics": {...},
  "passed": true,
  "notes": "..."
}
```

Questo permette di tracciare nel tempo come evolvono le performance al variare delle versioni dei modelli/librerie.

**Confronti tra alternative:** quando si testa più di un'opzione (es. chunking strategy, embedder a dimensioni diverse), produrre una tabella di confronto e archiviarla in `docs/benchmark_<date>.md`. Senza confronti scritti, si finisce a scegliere per intuizione.

**Configurazioni esternalizzate:** le soglie calibrate (cosine per dedup, Hamming SimHash, parametri BERTopic) vivono in `config/` come file JSON, mai hardcoded. Ogni cambio di configurazione è un commit datato.

**Test failure ≠ bug nel codice.** Un test che fallisce significa o un bug, o una soglia mal calibrata, o un'assunzione sbagliata sul dominio. Prima di "fixare", capire quale dei tre è il caso. Spesso la soglia va ricalibrata, non il codice riscritto.

**Tempo di test contenuto.** Ogni test isolato deve girare in < 60 secondi (escluso il primo download modelli). Se un test diventa lento, splittarlo in unit + integration. Altrimenti smetti di lanciarli.

**Guardia anti-circolarità nel codice:** il vincolo "judge LLM ≠ pipeline LLM" non è una linea guida ma un assert nel codice del modulo di valutazione. Se per errore in `.env` qualcuno configura lo stesso modello per entrambi i ruoli, il test deve rifiutarsi di partire con un messaggio chiaro.
