"""CLI di La Conoscienza.

Entrypoint: ``conoscienza`` (vedi ``[project.scripts]`` in ``pyproject.toml``).
In questa fase espone solo ``init``; gli stadi della pipeline arrivano dopo.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from conoscienza import __version__
from conoscienza import config
from conoscienza import paths

load_dotenv()  # carica .env dalla cwd, se presente

console = Console()
app = typer.Typer(
    name="conoscienza",
    help="Knowledge base + report quotidiano di novita dal web. Self-hosted.",
    no_args_is_help=True,
    add_completion=False,
)

# slug dominio: minuscolo, alfanumerico, trattini interni
_DOMAIN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# sottocartelle di un dominio non incluse nei template (create vuote)
_DOMAIN_RUNTIME_DIRS = (
    "sources/ingested",
    "reports/digest",
    "reports/weekly",
)


@app.command()
def version() -> None:
    """Mostra la versione installata."""
    console.print(__version__)


@app.command()
def init(
    domain: str = typer.Argument(
        None,
        help="Nome del dominio da creare. Se omesso, inizializza solo la struttura dati globale.",
    ),
) -> None:
    """Inizializza la struttura dati, oppure crea un nuovo dominio.

    Senza argomento: crea ``CONOSCIENZA_DATA`` con ``config/global.yaml``.
    Con un nome: crea ``domains/<nome>/`` dallo scaffold del pacchetto.
    """
    root = paths.data_root()
    if domain is None:
        _init_global(root)
    else:
        _init_domain(root, domain)


@app.command()
def check(
    domain: str = typer.Argument(
        None,
        help="Dominio da validare. Se omesso, valida la config globale e tutti i domini.",
    ),
) -> None:
    """Valida le configurazioni: ``global.yaml`` e i file di config dei domini.

    Senza argomento controlla la config globale e ogni dominio presente. Con un nome,
    controlla la config globale e quel dominio soltanto. Esce con codice 1 se trova
    anche un solo problema: utile in CI o in un hook pre-run.
    """
    root = paths.data_root()
    if not paths.config_dir(root).exists():
        console.print(
            f"[red]Errore:[/red] struttura dati assente in {root}. Esegui prima: conoscienza init"
        )
        raise typer.Exit(code=1)

    errors = 0

    try:
        config.load_global(root)
        console.print("[green]ok  [/green] global.yaml")
    except config.ConfigError as exc:
        errors += 1
        console.print(f"[red]FAIL[/red] global.yaml\n{_indent(exc)}")

    if domain is None:
        targets = sorted(p.name for p in paths.domains_dir(root).iterdir() if p.is_dir())
        if not targets:
            console.print("[yellow]nota:[/yellow] nessun dominio da controllare.")
    elif not paths.domain_dir(domain, root).exists():
        console.print(f"[red]Errore:[/red] il dominio '{domain}' non esiste sotto {paths.domains_dir(root)}")
        raise typer.Exit(code=1)
    else:
        targets = [domain]

    for dom in targets:
        try:
            cfg = config.load_domain(dom, root)
            console.print(f"[green]ok  [/green] dominio '{dom}' ({len(cfg.sources)} fonti)")
        except config.ConfigError as exc:
            errors += 1
            console.print(f"[red]FAIL[/red] dominio '{dom}'\n{_indent(exc)}")

    if errors:
        console.print(f"\n[red]{errors} problema/i di configurazione.[/red]")
        raise typer.Exit(code=1)
    console.print("\n[green]Configurazione valida.[/green]")


def _indent(exc: Exception, prefix: str = "       ") -> str:
    """Rientra un messaggio d'errore multilinea sotto la riga di esito."""
    return "\n".join(prefix + line for line in str(exc).splitlines())


def _init_global(root: Path) -> None:
    """Crea la struttura dati e copia la config di esempio se assente."""
    paths.config_dir(root).mkdir(parents=True, exist_ok=True)
    paths.domains_dir(root).mkdir(parents=True, exist_ok=True)
    paths.logs_dir(root).mkdir(parents=True, exist_ok=True)
    console.print(f"Radice dati: [bold]{root}[/bold]")

    cfg = paths.global_config_path(root)
    if cfg.exists():
        console.print(f"[yellow]Esiste gia[/yellow], lasciata intatta: {cfg}")
    else:
        shutil.copyfile(paths.global_config_template(), cfg)
        console.print(f"[green]Creata[/green] config trasversale: {cfg}")
        console.print("  -> rivederla e adattarla prima del primo run.")

    console.print("Struttura dati pronta. Crea un dominio con: conoscienza init <nome>")


def _init_domain(root: Path, domain: str) -> None:
    """Copia lo scaffold di un dominio sotto ``domains/<domain>/``."""
    if not _DOMAIN_RE.match(domain):
        raise typer.BadParameter(
            f"'{domain}' non valido. Usa minuscole, cifre e trattini (es. 'ai', 'formula1')."
        )

    target = paths.domain_dir(domain, root)
    if target.exists():
        console.print(f"[red]Errore:[/red] il dominio esiste gia: {target}")
        raise typer.Exit(code=1)

    if not paths.config_dir(root).exists():
        console.print("[yellow]Struttura dati assente.[/yellow] Eseguo prima init globale.")
        _init_global(root)

    shutil.copytree(paths.domain_template_dir(), target)
    for sub in _DOMAIN_RUNTIME_DIRS:
        (target / sub).mkdir(parents=True, exist_ok=True)
        (target / sub / ".gitkeep").touch()

    # sostituisce il placeholder {{DOMAIN}} nello schema KB
    claude_md = target / "kb" / "CLAUDE.md"
    if claude_md.exists():
        claude_md.write_text(
            claude_md.read_text(encoding="utf-8").replace("{{DOMAIN}}", domain),
            encoding="utf-8",
        )

    console.print(f"[green]Creato[/green] dominio '{domain}': {target}")
    console.print("  -> compilare config/sources.yaml e config/profile.yaml.")


def main() -> None:
    """Entrypoint per ``[project.scripts]``."""
    app()


if __name__ == "__main__":
    main()
