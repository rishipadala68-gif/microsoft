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
    from rich.table import Table

    from app.memory.retrieval import HybridRetrievalEngine
    from app.models import Cue

    console.print(f"[bold yellow]Recalling precedents for:[/bold yellow] '{query}'")
    services = [service] if service else []
    cue = Cue(text=query, services=services, error_messages=[query])

    retriever = HybridRetrievalEngine()
    result = retriever.recall(cue, top_k=top)

    if not result.incidents:
        console.print("[dim red]No relevant past incidents found in memory.[/dim red]")
        return

    table = Table(title="Recalled Precedents & Score Breakdown", show_header=True, header_style="bold magenta")
    table.add_column("Incident ID", style="cyan", width=12)
    table.add_column("Final Score", justify="right", style="green")
    table.add_column("Vector", justify="right")
    table.add_column("FTS", justify="right")
    table.add_column("Fingerprint", justify="right")
    table.add_column("Graph", justify="right")
    table.add_column("Code", justify="right")
    table.add_column("Matched On", style="yellow")
    table.add_column("Flags", style="red")

    for inc in result.incidents:
        sb = inc.score_breakdown
        table.add_row(
            inc.id,
            f"{inc.final:.4f}",
            f"{sb.get('vec', 0.0):.3f}",
            f"{sb.get('fts', 0.0):.3f}",
            f"{sb.get('fp', 0.0):.1f}",
            f"{sb.get('svc', 0.0):.2f}",
            f"{sb.get('code', 0.0):.2f}",
            ", ".join(inc.matched_on) or "-",
            ", ".join(inc.flags) or "-",
        )

    console.print(table)


@app.command()
def investigate(scenario: str = typer.Option("A_pool_exhaustion", help="Demo scenario")):
    """Run full reasoning agent on a scenario."""
    console.print(f"Investigating scenario {scenario}...")


@app.command()
def resolve(live_id: str, root_cause: str = "", steps: str = "", worked: bool = True):
    """Resolve an incident, generate post-mortem, and write back to memory."""
    console.print(f"Resolving incident {live_id}...")


@app.command()
def consolidate(
    half_life_days: int = typer.Option(365, help="Half life days for decay"),
    distance_threshold: float = typer.Option(0.25, help="Clustering distance threshold"),
    min_cluster: int = typer.Option(3, help="Minimum incidents per pattern cluster"),
):
    """Run nightly consolidation job."""
    from app.jobs.consolidate import run_consolidation

    console.print("[bold cyan]Running consolidation job...[/bold cyan]")
    stats = run_consolidation(
        half_life_days=half_life_days,
        distance_threshold=distance_threshold,
        min_cluster=min_cluster,
    )
    console.print("[green]Consolidation complete![/green]")
    console.print(f"  Incidents decayed: {stats.get('incidents_decayed', 0)}")
    console.print(f"  Clusters found: {stats.get('clusters_found', 0)}")
    console.print(f"  Patterns upserted: {stats.get('patterns_upserted', 0)}")
    weak = stats.get("weak_runbooks", [])
    if weak:
        console.print(f"  [yellow]Weak runbooks identified: {len(weak)}[/yellow]")
        for w in weak:
            console.print(f"    - {w['id']} ({w['title']}): success rate {w['success_rate']:.1%}")


@app.command()
def eval(
    k: int = typer.Option(3, help="Recall@k metric k"),
    ablation: bool = typer.Option(True, help="Run ablation (vector-only & FTS-only)"),
):
    """Run evaluation benchmark and ablation suite."""
    from app.eval.harness import run_eval

    console.print(f"[bold cyan]Running evaluation suite (Recall@{k})...[/bold cyan]")
    res = run_eval(k=k, ablation=ablation)
    if "error" in res:
        console.print(f"[bold red]Evaluation failed: {res['error']}[/bold red]")
        return

    hybrid_recall = res["hybrid"][f"recall@{k}"]
    pass_status = "[bold green]PASS[/bold green]" if res.get("pass") else "[bold yellow]NEEDS IMPROVEMENT[/bold yellow]"
    console.print(f"\n[bold]Hybrid Retrieval Recall@{k}:[/bold] {hybrid_recall:.2%} ({pass_status})")

    if ablation:
        vec_r = res.get("vector_only", {}).get(f"recall@{k}", 0.0)
        fts_r = res.get("fts_only", {}).get(f"recall@{k}", 0.0)
        console.print(f"[bold]Vector-only Recall@{k}:[/bold] {vec_r:.2%}")
        console.print(f"[bold]FTS-only Recall@{k}:[/bold]    {fts_r:.2%}")
        if res.get("beats_vector") and res.get("beats_fts"):
            console.print("[bold green]✓ Hybrid retrieval strictly outperforms both vector-only and FTS-only![/bold green]")


@app.command()
def stats():
    """Display memory statistics, runbook success rates, and feedback ratios."""
    from rich.table import Table

    store = MemoryStore()
    console.print(f"\n[bold]Total Confirmed Incidents:[/bold] {store.count_incidents()}")
    patterns = store.list_patterns()
    console.print(f"[bold]Discovered Patterns:[/bold] {len(patterns)}")

    rbs = store.list_runbooks()
    console.print(f"[bold]Total Runbooks:[/bold] {len(rbs)}\n")

    if rbs:
        table = Table(title="Runbook Performance")
        table.add_column("Runbook ID", style="cyan")
        table.add_column("Title")
        table.add_column("Successes", justify="right")
        table.add_column("Failures", justify="right")
        table.add_column("Success Rate", justify="right")

        for rb in rbs:
            tot = rb.success_count + rb.failure_count
            rate = f"{(rb.success_count / tot):.0%}" if tot > 0 else "N/A"
            table.add_row(rb.id, rb.title, str(rb.success_count), str(rb.failure_count), rate)
        console.print(table)


@app.command()
def reindex():
    """Re-embed all incidents after changing embedding model."""
    console.print("Reindexing all incident embeddings...")


if __name__ == "__main__":
    app()
