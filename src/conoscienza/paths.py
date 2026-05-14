"""Risoluzione dei percorsi: radice dati del cliente e template del pacchetto.

Separazione netta:
- i *template* viaggiano col pacchetto (``conoscienza/templates/``);
- i *dati* del cliente vivono sotto ``CONOSCIENZA_DATA`` (default ``./data``),
  fuori dal pacchetto e dal controllo di versione.
"""

from __future__ import annotations

import importlib.resources as resources
import os
from pathlib import Path

ENV_DATA = "CONOSCIENZA_DATA"
DEFAULT_DATA = "./data"


# --- Dati del cliente -------------------------------------------------------

def data_root() -> Path:
    """Radice dei dati del cliente. Da ``CONOSCIENZA_DATA``, default ``./data``."""
    return Path(os.environ.get(ENV_DATA, DEFAULT_DATA)).expanduser().resolve()


def config_dir(root: Path | None = None) -> Path:
    return (root or data_root()) / "config"


def global_config_path(root: Path | None = None) -> Path:
    """Config trasversale compilata dal cliente."""
    return config_dir(root) / "global.yaml"


def domains_dir(root: Path | None = None) -> Path:
    return (root or data_root()) / "domains"


def domain_dir(domain: str, root: Path | None = None) -> Path:
    return domains_dir(root) / domain


def logs_dir(root: Path | None = None) -> Path:
    return (root or data_root()) / "logs"


# --- Template del pacchetto -------------------------------------------------

def templates_dir() -> Path:
    """Directory dei template inclusi nel pacchetto distribuibile."""
    return Path(str(resources.files("conoscienza"))) / "templates"


def global_config_template() -> Path:
    return templates_dir() / "global.example.yaml"


def domain_template_dir() -> Path:
    return templates_dir() / "domain"
