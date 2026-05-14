# Installazione

Guida per chi installa "La Conoscienza" sulla propria macchina (self-hosted).

## Requisiti

- Linux (testato su Pop_OS!). macOS probabile, non verificato.
- Python 3.12 (fissato in `.python-version`).
- [uv](https://docs.astral.sh/uv/) per ambiente virtuale e dipendenze.
- Opzionale: GPU consumer per i modelli locali (embedding, classifier). Senza GPU si puo
  operare in modalita cloud-only — vedi `config/global.example.yaml`, sezione `models`.
- Opzionale: Docker, solo se si usa SearXNG per la discovery aperta.

## Passi

```sh
# 1. dipendenze
uv sync

# 2. credenziali e percorso dati
cp .env.example .env
# compilare: ANTHROPIC_API_KEY, SMTP_*, e CONOSCIENZA_DATA se diverso da ./data

# 3. inizializzazione: crea data/config/global.yaml e la struttura dati
uv run conoscienza init

# 4. primo dominio
uv run conoscienza init <nome-dominio>
# poi compilare data/domains/<nome>/config/sources.yaml e profile.yaml

# 5. verifica
uv run conoscienza run --domain <nome> --dry-run
```

## Cosa NON viaggia col pacchetto

Tutto cio che sta in `data/` e di proprieta di chi installa: config compilata, domini,
`kb.db`, sorgenti ingerite, report, log. Va backuppato a parte (vedi sotto). Non e in git.

## Backup

Backuppare periodicamente:

- `data/domains/<x>/kb.db` (sqlite-vec)
- `data/domains/<x>/kb/` (knowledge base markdown)
- `data/config/`

Il resto (`data/domains/<x>/sources/ingested/`) e ricostruibile dalle fonti.

## Orchestrazione

Schedulazione via systemd: vedi i template in `deploy/systemd/`.

> Stub: dettagli da completare quando esiste la CLI.
