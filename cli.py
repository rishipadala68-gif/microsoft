from pathlib import Path

import typer
from rich.console import Console

from app.core.embeddings import get_embedder
from app.ingestion.loaders import load_folder, load_jira_export, load_slack_export
from app.ingestion.pipeline import IngestionPipeline
from app.memory.store import MemoryStore
from app.models import Runbook
from scripts.generate_seed_data import generate_seed_data

app = typer.Typer(help="Incident Response Agent CLI")
console = Console()

SERVICES_TOPOLOGY = [
    ("web-frontend", ["checkout-api", "auth-service"]),
    ("checkout-api", ["payments-gateway", "orders-service", "inventory-service", "redis-cache"]),
    ("orders-service", ["postgres-primary", "kafka-orders"]),
    ("inventory-service", ["postgres-primary"]),
    ("notification-worker", ["kafka-orders"]),
    ("payments-gateway", []),
    ("postgres-primary", []),
    ("redis-cache", []),
    ("kafka-orders", []),
    ("auth-service", []),
]


@app.command()
def seed():
    """Generate seed data, load runbooks, and initialize service topology."""
    console.print("[bold green]Seeding database with services, runbooks, and synthetic incidents...[/bold green]")
    store = MemoryStore()
    embedder = get_embedder()

    # 1. Seed Services & Dependencies
    console.print("Loading service topology...")
    for svc, deps in SERVICES_TOPOLOGY:
        store.upsert_service(svc, description=f"{svc} core component")
        for dep in deps:
            store.add_service_dependency(svc, dep)

    # 2. Seed Runbooks from data/runbooks/
    console.print("Loading runbooks...")
    runbooks_dir = Path("data/runbooks")
    if runbooks_dir.exists():
        for rb_file in runbooks_dir.glob("*.md"):
            content = rb_file.read_text(encoding="utf-8")
            rb_id = rb_file.stem
            title = rb_id
            services = []

            # parse frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].splitlines():
                        if line.startswith("id:"):
                            rb_id = line.split(":", 1)[1].strip()
                        elif line.startswith("title:"):
                            title = line.split(":", 1)[1].strip()
                    body = parts[2]
            else:
                body = content

            emb = embedder.embed_documents([f"{title} {body[:500]}"])[0]
            store.upsert_runbook(Runbook(
                id=rb_id,
                title=title,
                body_md=body.strip(),
                services=services,
                emb=emb,
            ))

    # 3. Generate synthetic incidents
    console.print("Generating seed incident files...")
    generate_seed_data()
    console.print("[bold green]Seed generation completed successfully![/bold green]")


@app.command()
def ingest(
    path: str = typer.Argument("data/seed", help="Path to folder or file to ingest"),
    source: str = typer.Option("folder", help="Source type: folder | jira | slack | md"),
    accept_low: bool = typer.Option(False, help="Accept low confidence extractions"),
):
    """Ingest incident documents through the memory pipeline."""
    console.print(f"[bold cyan]Ingesting documents from {path}...[/bold cyan]")
    pipeline = IngestionPipeline()
    count = 0

    if source == "folder" or Path(path).is_dir():
        docs = load_folder(path)
    elif source == "jira":
        docs = load_jira_export(path)
    elif source == "slack":
        docs = load_slack_export(path)
    else:
        docs = load_folder(path)

    for doc in docs:
        inc_id = pipeline.ingest_doc(doc, accept_low=accept_low)
        if inc_id:
            count += 1

    console.print(f"[bold green]Successfully ingested {count} incidents.[/bold green]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Error message, symptoms, or partial cue"),
    service: str = typer.Option(None, help="Service name filter"),
    top: int = typer.Option(5, help="Top K past incidents to recall"),
):
    """Retrieval only: recall past incidents and print score breakdown table."""
    console.print(f"[bold yellow]Recalling precedents for:[/bold yellow] '{query}'")
    # Will be connected to app.memory.retrieval in Phase 3
    console.print("[dim]Retrieval engine will be activated in Part 2 (Phase 3).[/dim]")


@app.command()
def investigate(scenario: str = typer.Option("A_pool_exhaustion", help="Demo scenario")):
    """Run full reasoning agent on a scenario."""
    console.print(f"Investigating scenario {scenario}...")


@app.command()
def resolve(live_id: str, root_cause: str = "", steps: str = "", worked: bool = True):
    """Resolve an incident, generate post-mortem, and write back to memory."""
    console.print(f"Resolving incident {live_id}...")


@app.command()
def consolidate():
    """Run nightly consolidation job."""
    console.print("Running consolidation job...")


@app.command()
def eval():
    """Run evaluation benchmark and ablation suite."""
    console.print("Running evaluation suite...")


@app.command()
def pr_check(files: list[str] = typer.Option(None), diff: str = typer.Option(None)):
    """Check code changes against past outage files."""
    console.print("Running PR check...")


@app.command()
def stats():
    """Display memory statistics, runbook success rates, and feedback ratios."""
    store = MemoryStore()
    console.print(f"Total Confirmed Incidents: {store.count_incidents()}")
    console.print(f"Total Runbooks: {len(store.list_runbooks())}")


@app.command()
def reindex():
    """Re-embed all incidents after changing embedding model."""
    console.print("Reindexing all incident embeddings...")


if __name__ == "__main__":
    app()
