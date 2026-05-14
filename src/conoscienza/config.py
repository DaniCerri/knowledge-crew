"""Caricamento e validazione della configurazione.

Due livelli, allineati alla separazione codice/dati:

- ``data/config/global.yaml``        -> :class:`GlobalConfig`  (trasversale all'installazione)
- ``data/domains/<x>/config/``       -> :class:`DomainConfig`  (per dominio: profilo,
  fonti, soglie di deduplica)

Tutti i path passano da :mod:`conoscienza.paths`. Ogni errore di lettura, parsing o
validazione viene incapsulato in :class:`ConfigError` con il file che l'ha causato:
la config la compila chi installa, gli errori devono essere leggibili.

Le scelte di schema seguono ``progettazione_preliminare/versione-mix.md`` (§3 fonti,
§5.5-5.7 scoring e soglie) e il template ``templates/global.example.yaml``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from conoscienza import paths

_M = TypeVar("_M", bound=BaseModel)

# --- Tipi base -------------------------------------------------------------

# Backend di esecuzione di un modello. Locale (sentence-transformers, ollama) o cloud.
Backend = Literal["sentence-transformers", "ollama", "anthropic"]

# Tipologie di fonte supportate dalla discovery (versione-mix.md §3).
SourceType = Literal[
    "rss", "arxiv", "hackernews", "reddit", "github_releases", "email", "searxng"
]


class _Strict(BaseModel):
    """Base che vieta i campi extra: un refuso nello YAML diventa errore, non viene ignorato."""

    model_config = ConfigDict(extra="forbid")


class ConfigError(Exception):
    """Config mancante, malformata o non valida. Il messaggio include sempre il file."""


# --- global.yaml -----------------------------------------------------------


class EmbeddingModel(_Strict):
    """Modello di embedding. La dimensionalita Matryoshka e fissata qui e iniettata
    nello schema sqlite-vec alla creazione del DB (vedi storage/db.py)."""

    name: str
    backend: Backend
    matryoshka_dim: Literal[256, 512, 1024]


class ModelSpec(_Strict):
    """Modello generico (classifier, compile, synthesis, rag)."""

    name: str
    backend: Backend
    prompt_caching: bool = False


class ModelsConfig(_Strict):
    embedding: EmbeddingModel
    classifier: ModelSpec
    entity_extraction: ModelSpec
    compile: ModelSpec
    weekly_synthesis: ModelSpec
    rag_interactive: ModelSpec


class VramConfig(_Strict):
    """Batching sequenziale su GPU consumer singola (versione-mix.md §10)."""

    sequential_batching: bool = True
    ollama_keep_alive: int = 0
    empty_cache_between_stages: bool = True


class RetentionConfig(_Strict):
    ephemeral_chunks_days: int = Field(default=90, gt=0)
    ingested_markdown_days: int = Field(default=90, gt=0)
    digest_months: int = Field(default=12, gt=0)


class DeliveryChannel(BaseModel):
    """Un canale di delivery. ``for`` e parola riservata Python: alias su ``for_``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool = False
    for_: list[str] = Field(default_factory=list, alias="for")
    vault_path: str | None = None  # solo per il canale obsidian


class DeliveryConfig(_Strict):
    email: DeliveryChannel = Field(default_factory=DeliveryChannel)
    obsidian: DeliveryChannel = Field(default_factory=DeliveryChannel)
    telegram: DeliveryChannel = Field(default_factory=DeliveryChannel)
    rss: DeliveryChannel = Field(default_factory=DeliveryChannel)


class CalibrationConfig(_Strict):
    """Prime settimane in "log only": registra triage_score senza filtrare."""

    log_only_weeks: int = Field(default=2, ge=0)


class GlobalConfig(_Strict):
    """Config trasversale all'installazione. Le specificita di campo stanno per dominio."""

    models: ModelsConfig
    vram: VramConfig = Field(default_factory=VramConfig)
    # schedule: solo riferimento, l'orchestrazione reale e in deploy/systemd. Chiavi libere.
    schedule: dict[str, str] = Field(default_factory=dict)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)


# --- domains/<x>/config/sources.yaml --------------------------------------


class Source(_Strict):
    """Una fonte. I campi obbligatori oltre a ``id/type/domain/authority`` dipendono
    dal ``type`` (vedi ``_REQUIRED_BY_TYPE``)."""

    id: str
    type: SourceType
    domain: str
    authority: float = Field(ge=0.0, le=1.0)

    # campi opzionali, specifici per tipologia
    url: str | None = None  # rss
    query: str | None = None  # arxiv, searxng
    max_per_run: int | None = Field(default=None, gt=0)  # arxiv
    from_address: str | None = None  # email
    min_score: int | None = Field(default=None, ge=0)  # hackernews
    repo: str | None = None  # github_releases
    subreddit: str | None = None  # reddit
    min_upvotes: int | None = Field(default=None, ge=0)  # reddit

    # Campo obbligatorio per ciascuna tipologia di fonte.
    _REQUIRED_BY_TYPE: ClassVar[dict[str, str]] = {
        "rss": "url",
        "arxiv": "query",
        "searxng": "query",
        "email": "from_address",
        "github_releases": "repo",
        "reddit": "subreddit",
        # hackernews: nessun campo obbligatorio oltre ai comuni
    }

    @model_validator(mode="after")
    def _check_required_field(self) -> Source:
        required = self._REQUIRED_BY_TYPE.get(self.type)
        if required is not None and getattr(self, required) is None:
            raise ValueError(f"fonte '{self.id}' di tipo '{self.type}' richiede il campo '{required}'")
        return self


class SourcesConfig(_Strict):
    sources: list[Source]

    @model_validator(mode="after")
    def _unique_ids(self) -> SourcesConfig:
        seen: set[str] = set()
        dup = sorted({s.id for s in self.sources if s.id in seen or seen.add(s.id)})
        if dup:
            raise ValueError(f"id fonte duplicati: {dup}")
        return self


# --- domains/<x>/config/profile.yaml --------------------------------------


class Relevance(_Strict):
    """Topic seguiti / da scartare, passati al classifier zero-shot."""

    whitelist: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)


class WeightProfile(_Strict):
    """Pesi dello scoring per una tipologia di fonte: freshness, authority, topic, social.

    I valori grezzi vengono rinormalizzati a somma 1 al momento dello scoring
    (versione-mix.md §5.6): qui basta che siano non negativi e non tutti nulli."""

    f: float = Field(ge=0.0)
    a: float = Field(ge=0.0)
    t: float = Field(ge=0.0)
    s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _not_all_zero(self) -> WeightProfile:
        if self.f + self.a + self.t + self.s <= 0:
            raise ValueError("almeno un peso deve essere > 0")
        return self

    def normalized(self) -> dict[str, float]:
        """Pesi rinormalizzati a somma 1, pronti per la combinazione lineare."""
        total = self.f + self.a + self.t + self.s
        return {"f": self.f / total, "a": self.a / total, "t": self.t / total, "s": self.s / total}


class Thresholds(_Strict):
    """Soglie a valle del ``triage_score`` (mai sul punteggio: §5.7).

    Sopra ``promote_to_kb`` l'item viene compilato in KB; sotto ``digest_min`` viene
    scartato del tutto; in mezzo vive solo nel digest."""

    promote_to_kb: float = Field(ge=0.0, le=1.0)
    digest_min: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordering(self) -> Thresholds:
        if self.digest_min >= self.promote_to_kb:
            raise ValueError(
                f"digest_min ({self.digest_min}) deve essere < promote_to_kb ({self.promote_to_kb})"
            )
        return self


class DomainProfile(_Strict):
    """Profilo di rilevanza e scoring di un dominio."""

    domain: str
    relevance: Relevance = Field(default_factory=Relevance)
    weight_profiles: dict[str, WeightProfile]
    freshness_half_life_days: float = Field(gt=0.0)
    thresholds: Thresholds


# --- domains/<x>/config/dedup_thresholds.json -----------------------------


class DedupThresholds(BaseModel):
    """Soglie di deduplica. I valori cosine sono ``null`` finche non calibrati via ROC
    sui dati reali; il runner di triage deve gestire il caso non calibrato.

    ``extra="ignore"``: il file template porta un campo ``_comment`` non strutturale."""

    model_config = ConfigDict(extra="ignore")

    # chiave = dimensionalita Matryoshka come stringa ("256" | "512" | "1024")
    cosine_threshold: dict[str, float | None] = Field(default_factory=dict)
    simhash_hamming_max: int = Field(default=3, ge=0)
    calibration_date: str | None = None
    fixture_set_version: str | None = None
    embedding_model_version: str | None = None

    def cosine_for(self, dim: int) -> float | None:
        """Soglia cosine per una dimensionalita, o ``None`` se non calibrata."""
        return self.cosine_threshold.get(str(dim))


# --- Aggregato per dominio -------------------------------------------------


class DomainConfig(_Strict):
    """Config completa di un dominio: profilo + fonti + soglie di deduplica.

    Non si carica da un singolo file: la produce :func:`load_domain` combinando i tre
    file di ``config/`` e verificandone la coerenza."""

    name: str
    profile: DomainProfile
    sources: list[Source]
    dedup: DedupThresholds


# --- Lettura e validazione -------------------------------------------------


def _read_mapping(path: Path, parser) -> dict:
    """Legge un file di config e ne garantisce un mapping al top level."""
    if not path.exists():
        raise ConfigError(f"file di config mancante: {path}")
    try:
        data = parser(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigError(f"sintassi non valida in {path}: {exc}") from exc
    if data is None:
        raise ConfigError(f"file di config vuoto: {path}")
    if not isinstance(data, dict):
        raise ConfigError(
            f"atteso un mapping al top level di {path}, trovato {type(data).__name__}"
        )
    return data


def _validate(model: type[_M], data: dict, path: Path) -> _M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"config non valida in {path}:\n{exc}") from exc


def load_global(root: Path | None = None) -> GlobalConfig:
    """Carica e valida ``data/config/global.yaml``."""
    path = paths.global_config_path(root)
    return _validate(GlobalConfig, _read_mapping(path, yaml.safe_load), path)


def load_profile(domain: str, root: Path | None = None) -> DomainProfile:
    """Carica e valida ``profile.yaml`` di un dominio."""
    path = paths.domain_profile_path(domain, root)
    return _validate(DomainProfile, _read_mapping(path, yaml.safe_load), path)


def load_sources(domain: str, root: Path | None = None) -> list[Source]:
    """Carica e valida ``sources.yaml`` di un dominio."""
    path = paths.domain_sources_path(domain, root)
    return _validate(SourcesConfig, _read_mapping(path, yaml.safe_load), path).sources


def load_dedup_thresholds(domain: str, root: Path | None = None) -> DedupThresholds:
    """Carica e valida ``dedup_thresholds.json`` di un dominio."""
    path = paths.domain_dedup_thresholds_path(domain, root)
    return _validate(DedupThresholds, _read_mapping(path, json.loads), path)


def load_domain(domain: str, root: Path | None = None) -> DomainConfig:
    """Carica la config completa di un dominio e ne verifica la coerenza.

    Oltre alla validazione dei singoli file, controlla che il campo ``domain``
    del profilo e di ogni fonte combaci col nome della cartella del dominio.
    """
    profile = load_profile(domain, root)
    sources = load_sources(domain, root)
    dedup = load_dedup_thresholds(domain, root)

    if profile.domain != domain:
        raise ConfigError(
            f"profile.yaml del dominio '{domain}' dichiara domain='{profile.domain}': "
            f"deve combaciare col nome della cartella"
        )
    mismatched = sorted(s.id for s in sources if s.domain != domain)
    if mismatched:
        raise ConfigError(
            f"sorgenti del dominio '{domain}' con domain diverso dalla cartella: {mismatched}"
        )

    return DomainConfig(name=domain, profile=profile, sources=sources, dedup=dedup)
