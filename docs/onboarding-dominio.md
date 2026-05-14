# Onboarding di un dominio

Un **dominio** = un campo di conoscenza separato (es. `ai`, `formula1`). Ogni dominio ha
fonti, profilo di rilevanza, soglie e `kb.db` propri. Nessuna contaminazione cross-campo.

## Creare un dominio

```sh
uv run conoscienza init <nome>
```

Scaffolding da `src/conoscienza/templates/domain/` → crea:

```
data/domains/<nome>/
├── config/
│   ├── sources.yaml            # da compilare: fonti del campo
│   ├── profile.yaml            # da compilare: whitelist/blacklist, pesi, soglie
│   └── dedup_thresholds.json   # placeholder, calibrato dopo
├── kb/
│   ├── CLAUDE.md               # schema KB, {{DOMAIN}} sostituito
│   ├── topics/ entities/ events/ methods/
├── sources/ingested/
├── reports/digest/ + weekly/
└── kb.db                       # creato al primo run
```

## Compilare la config

1. **`sources.yaml`** — 10-15 fonti curate (regola 80/20). Tipi: `rss`, `arxiv`,
   `hackernews`, `reddit`, `github_releases`, `email`, `searxng`. Ogni fonte ha
   `authority` in [0,1].
2. **`profile.yaml`** — whitelist/blacklist topic per il classifier, `weight_profiles`
   per tipo di fonte, `freshness_half_life_days`, soglie `promote_to_kb` / `digest_min`.
   Soglie iniziali = placeholder.
3. **`kb/CLAUDE.md`** — personalizzare sezioni fisse e regole al dominio specifico.

## Calibrazione

Prime 2 settimane in modalita **"log only"**: `triage_score` registrato, niente filtro.
Poi calibrare soglie su distribuzioni reali e rilanciare il test dedup ROC (`3.2.c`) per
riempire `dedup_thresholds.json`.

> Stub: comando `conoscienza init` non ancora implementato.
