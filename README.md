# La Conoscienza

Sistema personale di knowledge base + report quotidiano di novita dal web.

Pipeline a 5 stadi: **Discovery → Ingestion → Triage → Compile → Report**. Triage e il
punto di biforcazione: sotto soglia l'item vive nel digest e muore li, sopra soglia viene
compilato in una knowledge base markdown durevole.

Uso personale single-tenant su Pop_OS!, GPU consumer, budget cloud LLM 5-10 USD/mese.

## Architettura cartelle

| Path | Cosa |
|---|---|
| `src/conoscienza/` | Codice pipeline. Domain-agnostic, scritto una volta, riusato da ogni dominio. |
| `domains/<x>/` | Workspace per campo: fonti, profilo rilevanza, soglie calibrate, KB, `kb.db`, report. |
| `domains/_template/` | Scheletro da copiare per aggiungere un dominio. |
| `config/` | Config trasversale: modelli, schedule, VRAM, canali delivery. |
| `tests/` | Test isolati per componente + e2e. `fixtures/` = dataset congelato (ambito AI = benchmark). |
| `deploy/` | systemd unit + docker-compose (SearXNG). |
| `scripts/` | One-off: prune, re-embed, lint KB, backup. |

I domini sono **fisicamente separati**: ogni `domains/<x>/kb.db` e uno spazio vettoriale
unificato a se. Nessuna contaminazione cross-campo. Backup e potatura 90gg indipendenti.

## Setup

Ambiente virtuale e dipendenze gestiti con [uv](https://docs.astral.sh/uv/).

```sh
uv sync                       # crea .venv, installa deps + gruppo dev, scrive uv.lock
uv run conoscienza --help     # esegue la CLI nel venv
uv sync --extra heavy-pdf     # aggiunge i parser PDF pesanti (Milestone 3)
```

Versione Python fissata in `.python-version` (3.12). `uv.lock` va committato.

## Stato

Fase iniziale: struttura cartelle e config. Nessun codice ancora.

Primo dominio: `ai` (anche dataset di test e benchmark della pipeline).

Roadmap implementativa: vedi `progettazione_preliminare/versione-mix.md` §13.

## Aggiungere un dominio

```sh
cp -r domains/_template domains/<nome>
# poi compilare domains/<nome>/config/sources.yaml e profile.yaml
```

## Documenti di progettazione

In `progettazione_preliminare/`. `versione-mix.md` e il design consolidato di riferimento.
