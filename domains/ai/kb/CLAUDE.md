# Schema della Knowledge Base — dominio AI

Schema operativo per l'agente di compile. Questa KB contiene **solo conoscenza durevole**
(valore a 6 mesi). Le notizie effimere vivono nel digest e muoiono li.

## Tipi di pagina

### topic — `kb/topics/`
Curati a mano, un `.md` per topic seguito.
Sezioni fisse: overview, sub-topic, eventi correlati, fonti recenti.
Aggiornata quando nuovi events/methods/entities emergono nel topic.

### entity — `kb/entities/`
Una pagina per organizzazione, prodotto, modello, persona di rilievo.
Sezioni fisse: descrizione, timeline, caratteristiche correnti, relazioni, summary_for_synthesis.
Le pagine entity sono **temporali**: mantengono una timeline di eventi.

### event — `kb/events/`
**IMMUTABILE dopo la creazione.**
Sezioni fisse: data, descrizione, fonti, implicazioni, summary_for_synthesis,
link a entity/topic coinvolti.

### method — `kb/methods/`
Tecnica, algoritmo, paper seminale.
Sezioni fisse: idea base, paper di riferimento, applicazioni note.

## Regole

- Wikilinks `[[path/to/page]]` SEMPRE da `resolved_entities`, MAI inventati.
- Mai duplicare informazioni: linkare invece.
- Tag confidenza inline: `<!-- conf:high -->`, `<!-- conf:medium -->`, `<!-- conf:low -->`.
- Inferenze cross-document SEMPRE marcate con `conf:medium` o inferiore, mai come fatti.
- Niente contenuto effimero (prezzi, hot take, news di mercato).
- Ogni pagina entity/event ha una sezione `summary_for_synthesis` (100-200 token).
- Lint settimanale: orphan pages, link rotti, contraddizioni, summary mancanti.

## Pattern di compile

L'agente NON cerca match liberamente. Pipeline strutturata:
entity extraction locale → resolution vettoriale contro la KB → plan-pass (piano Pydantic,
non markdown libero) → apply deterministico con wikilink da template → transazione atomica.

Le decisioni "dove scrivere" sono fatte da ricerca vettoriale. L'LLM lavora con
riferimenti gia risolti.
