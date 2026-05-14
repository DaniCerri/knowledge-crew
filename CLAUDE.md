# CLAUDE.md — La Conoscienza

Riassunto operativo del progetto per agenti. Tenere aggiornato.

## Cos'è

Sistema di **knowledge base + report quotidiano di novità dal web**. Pipeline a 5 stadi:

```
Discovery → Ingestion → Triage → Compile → Report
```

Il **Triage** è il punto di biforcazione: sotto soglia l'item vive nel digest e muore lì,
sopra soglia viene compilato in una knowledge base markdown durevole.

**Obiettivo prodotto:** generico e riutilizzabile, **distribuibile e venduto/prestato a
terzi** per costruire la loro KB. Modello di distribuzione: **self-hosted** (chi installa
esegue sulla propria macchina).

Documenti di progettazione: `progettazione_preliminare/` — `versione-mix.md` è il design
consolidato di riferimento.

## Architettura — decisioni fissate

- **Codice vs dati.** `src/conoscienza/` = codice distribuibile, domain-agnostic. `data/`
  = dati del cliente (gitignored, mai nel pacchetto). `CONOSCIENZA_DATA` punta alla radice
  dati (default `./data`).
- **Per-dominio.** Ogni dominio (`ai`, `formula1`, ...) è un workspace isolato sotto
  `data/domains/<x>/` con config, KB, sorgenti, report e `kb.db` propri. Nessuna
  contaminazione cross-campo. Il codice non sa nulla dei domini concreti.
- **Template nel pacchetto.** `src/conoscienza/templates/` (`domain/`, `global.example.yaml`)
  viaggia col distribuibile; `conoscienza init` ne fa scaffolding.
- **Storage.** Un `kb.db` sqlite-vec per dominio: spazio vettoriale unificato (item
  effimeri + KB durevole), transazioni ACID, niente store separati. Migration in
  `storage/migrations/NNN_*.sql`, runner idempotente.
- **5 stadi** = 5 sottopacchetti in `src/conoscienza/` (+ `topics`, `storage`, `models`).
- **Triage = router.** `triage_score` assoluto e normalizzato `[0,1]`; `promote_to_kb`
  booleano con soglia calibrata per dominio.

## Regole

- **MAI riferimenti a Claude/Anthropic/AI nei commit, PR o output git.** Niente trailer
  `Co-Authored-By`, niente "Generated with". Regola permanente.
- **Commit in italiano**, Conventional Commits (`feat:`, `refactor:`, `chore:`, ...).
  Corpo del commit quando il "perché" non è ovvio.
- **`src/` resta domain-agnostic.** Nessun `"ai"` o altro dominio hardcoded, nessun path
  o assunzione hardware nel codice. Le specificità vivono in config.
- **Ambiente con `uv`.** `.venv` va creato **fuori dal drive** (repo su exFAT, no symlink):
  `export UV_PROJECT_ENVIRONMENT=~/.venvs/conoscienza` prima di ogni comando `uv`.
- **Dipendenze copyleft vietate** nel pacchetto distribuibile (licenza proprietaria):
  vedi `docs/audit-licenze-dipendenze.md`. PyMuPDF (AGPL) e marker-pdf (GPL) da sostituire.
- **Decisioni data-driven rinviate.** Soglie, dimensionalità Matryoshka, routing PDF: si
  calibrano sui dati reali dopo 2 settimane di "log only", non a priori.
- **Plan-then-apply nel compile.** L'LLM produce piani Pydantic, il rendering è
  deterministico da template. Mai wikilink inventati: sempre risolti via ricerca vettoriale.

## Comandi

```sh
export UV_PROJECT_ENVIRONMENT=~/.venvs/conoscienza   # obbligatorio: repo su exFAT
uv sync                          # crea venv + installa deps
uv run conoscienza --help
uv run conoscienza init          # crea struttura dati (data/config/, domains/, logs/)
uv run conoscienza init <nome>   # scaffold di un nuovo dominio
```

## Stato

Implementato: CLI (`init`), storage layer (schema sqlite-vec + migration runner),
config loader (`config.py`: modelli Pydantic + validazione di `global.yaml` e dei tre
file di config per-dominio, `load_global` / `load_domain`).
Non ancora implementato: nessuno dei 5 stadi della pipeline.

Roadmap: `progettazione_preliminare/versione-mix.md` §13.

## Registro problemi noti risolti

Aggiornare quando un problema non ovvio viene risolto. Una riga per problema.

| Data | Problema | Soluzione |
|---|---|---|
| 2026-05-14 | `uv sync` fallisce: `failed to symlink .venv/bin/python` (`Operation not permitted`). Repo su drive exFAT, niente symlink. | Creare il venv fuori dal drive: `export UV_PROJECT_ENVIRONMENT=~/.venvs/conoscienza`. Documentato in `docs/installazione.md`. |
| 2026-05-14 | `[project.scripts]` puntava a `conoscienza.cli:app` (oggetto Typer, non callable come console_script). | Aggiunta `main()` che chiama `app()`, entrypoint → `conoscienza.cli:main`. |
| 2026-05-14 | `executescript` di sqlite committa implicitamente il DDL → rompe una transazione esterna che lo avvolge. | Nel runner di migration: `executescript` + `INSERT` di tracking + `commit()` per ogni migration, niente CM esterno. |
