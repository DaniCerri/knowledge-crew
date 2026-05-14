# La Conoscienza

Sistema di knowledge base + report quotidiano di novita dal web.

Pipeline a 5 stadi: **Discovery → Ingestion → Triage → Compile → Report**. Triage e il
punto di biforcazione: sotto soglia l'item vive nel digest e muore li, sopra soglia viene
compilato in una knowledge base markdown durevole.

Progettato per essere **generico e riutilizzabile**: distribuibile e installabile da terzi
per costruire la propria knowledge base. Modello di distribuzione: **self-hosted** — chi
installa esegue il sistema sulla propria macchina, con le proprie fonti, credenziali e dati.

## Codice vs dati

Separazione netta tra cio che si distribuisce e cio che appartiene al cliente:

| Path | Cosa | In git |
|---|---|---|
| `src/conoscienza/` | Codice pipeline. Domain-agnostic, scritto una volta, riusato da ogni dominio. | si |
| `src/conoscienza/templates/` | Scheletri (`domain/`, `global.example.yaml`) usati da `conoscienza init` per lo scaffolding. Viaggiano col pacchetto. | si |
| `deploy/` | Template systemd + docker-compose (SearXNG). | si |
| `docs/` | Guida installazione e onboarding di un dominio. | si |
| `tests/` | Test isolati + e2e. `fixtures/` = dataset congelato (ambito AI = benchmark). | si |
| **`data/`** | **Dati del cliente**: config compilata, domini, `kb.db`, sorgenti, report, log. Mutevole, di proprieta di chi installa. Da backuppare a parte. | **no** |

`CONOSCIENZA_DATA` (in `.env`) punta alla radice dati. Default `./data`.

## Struttura `data/`

```
data/
├── config/global.yaml          # copia compilata di config/global.example.yaml
└── domains/                    # un workspace per campo — separazione dei domini
    └── ai/                     # primo dominio (anche ambito di test/benchmark)
        ├── config/             # sources.yaml, profile.yaml, dedup_thresholds.json
        ├── kb/                 # KB durevole: topics/ entities/ events/ methods/ + CLAUDE.md
        ├── sources/ingested/   # markdown grezzi, potati a 90gg
        ├── reports/            # digest/ + weekly/
        └── kb.db               # sqlite-vec per-dominio
```

Ogni `domains/<x>/kb.db` e uno spazio vettoriale unificato a se. Nessuna contaminazione
cross-campo. Backup e potatura 90gg indipendenti.

## Setup

Ambiente virtuale e dipendenze gestiti con [uv](https://docs.astral.sh/uv/).

```sh
uv sync                       # crea .venv, installa deps + gruppo dev, scrive uv.lock
cp .env.example .env          # poi compilare credenziali e CONOSCIENZA_DATA
uv run conoscienza init       # crea data/config/global.yaml e struttura dati
uv run conoscienza --help
uv sync --extra heavy-pdf     # parser PDF pesanti (Milestone 3)
```

Versione Python fissata in `.python-version` (3.12). `uv.lock` va committato.
Dettagli in `docs/installazione.md`.

## Aggiungere un dominio

```sh
uv run conoscienza init <nome>
# poi compilare data/domains/<nome>/config/sources.yaml e profile.yaml
```

Lo scaffolding viene da `src/conoscienza/templates/domain/`. Dettagli in
`docs/onboarding-dominio.md`.

## Stato

Fase iniziale: struttura cartelle, config e separazione codice/dati. Nessun codice ancora.

Primo dominio: `ai` (anche dataset di test e benchmark della pipeline).

Roadmap implementativa: vedi `progettazione_preliminare/versione-mix.md` §13.

## Documenti di progettazione

In `progettazione_preliminare/`. `versione-mix.md` e il design consolidato di riferimento.
Nota: i doc partono dal presupposto "uso personale single-tenant"; l'obiettivo prodotto
self-hosted aggiunge la separazione codice/dati descritta sopra.
