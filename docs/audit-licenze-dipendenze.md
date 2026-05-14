# Audit licenze dipendenze

Da risolvere **prima** di distribuire / vendere / prestare il prodotto. La licenza del
prodotto e proprietaria (vedi `LICENSE`): dipendenze copyleft (GPL/AGPL) linkate sono
incompatibili con la distribuzione proprietaria.

## Stato: NON risolto

## Problemi noti

| Dipendenza | Licenza | Problema | Mitigazione |
|---|---|---|---|
| `pymupdf4llm` / PyMuPDF | **AGPL-3.0** o commerciale a pagamento | AGPL linkato in prodotto proprietario = obbligo di rilascio sorgente, incompatibile con distribuzione chiusa | Sostituire con parser permissivo (`pypdfium2` BSD-3, `pdfplumber` MIT) **oppure** acquistare licenza commerciale PyMuPDF |
| `marker-pdf` | **GPL-3.0** | Stesso problema. Gia isolato in extra opzionale `[heavy-pdf]` | Mantenere opzionale e non distribuirlo, oppure sostituire. Valutare `docling` (MIT) come default per il path pesante |

## OK (permissive)

`feedparser`, `crawl4ai` (Apache-2.0), `trafilatura` (Apache-2.0/GPL? verificare),
`bertopic` (MIT), `pydantic` (MIT), `sentence-transformers` (Apache-2.0),
`anthropic` (MIT), `ollama` (MIT), `sqlite-vec` (Apache-2.0/MIT), `typer` (MIT),
`rich` (MIT), `apscheduler` (MIT).

> Nota: `trafilatura` va riverificata — alcune versioni storiche erano GPL, le recenti
> Apache-2.0. Confermare la versione pinnata in `uv.lock`.

## Azione

1. Decidere parser PDF permissivo per il path di default (escludere PyMuPDF/Marker dalla
   distribuzione, o licenza commerciale).
2. Eseguire audit automatico completo prima della prima release:
   `uv run pip-licenses` o `uv tree` + check manuale.
3. Aggiornare questo file con l'esito.
