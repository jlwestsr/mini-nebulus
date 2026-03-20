import os
import asyncio
import typer
from typing import List, Optional
from nebulus_atom.services.doc_service import DocService
from rich.markdown import Markdown
from rich.console import Console

# Silence HuggingFace warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from nebulus_atom.commands.overlord_commands import overlord_app
from nebulus_atom.commands.queue_commands import queue_app
from nebulus_atom.commands.dispatch_commands import dispatch_app
from nebulus_atom.commands.focus_commands import focus_app

app = typer.Typer(invoke_without_command=True)
app.add_typer(overlord_app, name="overlord")
app.add_typer(queue_app, name="queue")
app.add_typer(dispatch_app, name="dispatch")
app.add_typer(focus_app, name="focus")

# --- Mirror subcommand group ---
mirror_app = typer.Typer(help="Manage bare-clone mirrors of ecosystem repos.")
app.add_typer(mirror_app, name="mirror")


@mirror_app.command("init")
def mirror_init(
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Init a single project mirror"
    ),
) -> None:
    """Initialize bare-clone mirrors for ecosystem repos."""
    from nebulus_swarm.overlord.mirrors import MirrorManager
    from nebulus_swarm.overlord.registry import load_config

    console = Console()
    try:
        config = load_config()
    except ValueError as e:
        console.print(f"[red]Config error: {e}[/red]")
        return

    if not config.projects:
        console.print("[yellow]No projects registered.[/yellow]")
        return

    mgr = MirrorManager(config)

    if project:
        if project not in config.projects:
            console.print(f"[red]Unknown project: {project}[/red]")
            return
        ok = mgr.init_project(project)
        status = "[green]done[/green]" if ok else "[red]failed[/red]"
        console.print(f"Mirror init {project}: {status}")
    else:
        results = mgr.init_all()
        for name, ok in results.items():
            status = "[green]done[/green]" if ok else "[red]failed[/red]"
            console.print(f"  {name}: {status}")


@mirror_app.command("sync")
def mirror_sync(
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Sync a single project mirror"
    ),
) -> None:
    """Fetch updates for ecosystem mirror clones."""
    from nebulus_swarm.overlord.mirrors import MirrorManager
    from nebulus_swarm.overlord.registry import load_config

    console = Console()
    try:
        config = load_config()
    except ValueError as e:
        console.print(f"[red]Config error: {e}[/red]")
        return

    if not config.projects:
        console.print("[yellow]No projects registered.[/yellow]")
        return

    mgr = MirrorManager(config)

    if project:
        if project not in config.projects:
            console.print(f"[red]Unknown project: {project}[/red]")
            return
        ok = mgr.sync_project(project)
        status = "[green]done[/green]" if ok else "[red]failed[/red]"
        console.print(f"Mirror sync {project}: {status}")
    else:
        results = mgr.sync_all()
        for name, ok in results.items():
            status = "[green]done[/green]" if ok else "[red]failed[/red]"
            console.print(f"  {name}: {status}")


@mirror_app.command("status")
def mirror_status() -> None:
    """Show the state of all ecosystem mirror clones."""
    from rich.table import Table

    from nebulus_swarm.overlord.mirrors import MirrorManager
    from nebulus_swarm.overlord.registry import load_config

    console = Console()
    try:
        config = load_config()
    except ValueError as e:
        console.print(f"[red]Config error: {e}[/red]")
        return

    if not config.projects:
        console.print("[yellow]No projects registered.[/yellow]")
        return

    mgr = MirrorManager(config)
    states = mgr.status()

    table = Table(title="Mirror Status")
    table.add_column("Project", style="bold")
    table.add_column("Exists")
    table.add_column("Last Fetch")
    table.add_column("Refs")

    for name, state in states.items():
        if state.exists:
            exists_str = "[green]yes[/green]"
            fetch_str = (
                state.last_fetch.strftime("%Y-%m-%d %H:%M")
                if state.last_fetch
                else "[dim]unknown[/dim]"
            )
            refs_str = str(state.ref_count)
        else:
            exists_str = "[red]no[/red]"
            fetch_str = "-"
            refs_str = "-"
        table.add_row(name, exists_str, fetch_str, refs_str)

    console.print(table)


@app.callback()
def main(ctx: typer.Context):
    """
    Nebulus Atom: A professional, autonomous AI engineer CLI.
    """
    pass


@app.command()
def start(
    prompt: Optional[List[str]] = typer.Argument(
        None, help="Initial prompt to execute immediately"
    ),
    session_id: str = typer.Option("default", help="Session ID for persistence"),
):
    """
    Start the Nebulus Atom AI Agent.
    """
    _start_agent(prompt, session_id)


def _start_agent(prompt: Optional[List[str]], session_id: str = "default"):
    initial_prompt = " ".join(prompt) if prompt else None

    from nebulus_atom.views.cli_view import CLIView
    from nebulus_atom.controllers.agent_controller import AgentController

    view = CLIView()
    controller = AgentController(view=view)

    try:
        asyncio.run(controller.start(initial_prompt, session_id=session_id))
    except (KeyboardInterrupt, SystemExit):
        pass


@app.command()
def docs(
    action: str = typer.Argument(..., help="Action: 'list' or 'read'"),
    filename: Optional[str] = typer.Argument(None, help="Filename to read"),
):
    """
    Access embedded documentation.
    """
    service = DocService()
    console = Console()

    if action.lower() == "list":
        files = service.list_docs()
        if not files:
            console.print("No documentation files found.", style="yellow")
            return

        console.print("[bold cyan]Available Documentation:[/bold cyan]")
        for f in files:
            console.print(f" - {f}")

    elif action.lower() == "read":
        if not filename:
            console.print(
                "Error: Filename required for 'read' action.", style="bold red"
            )
            return

        content = service.read_doc(filename)
        if content:
            md = Markdown(content)
            console.print(md)
        else:
            console.print(f"Error: Could not read '{filename}'", style="bold red")
    else:
        console.print(
            f"Unknown action: {action}. Use 'list' or 'read'.", style="bold red"
        )


@app.command("review-pr")
def review_pr(
    pr_number: int = typer.Argument(..., help="Pull request number to review"),
    repo: Optional[str] = typer.Option(
        None, help="Repository in owner/name format (auto-detected from git remote)"
    ),
    no_checks: bool = typer.Option(
        False, "--no-checks", help="Skip local checks (pytest, ruff, security)"
    ),
):
    """
    Review a pull request using LLM analysis and local checks.
    """
    from rich.panel import Panel

    from nebulus_atom.commands.review_pr import (
        format_review_output,
        run_review,
    )

    console = Console()
    console.print(f"[bold cyan]Reviewing PR #{pr_number}...[/bold cyan]")

    result = run_review(
        pr_number=pr_number,
        repo=repo,
        run_checks=not no_checks,
    )

    output = format_review_output(result)

    decision = result.llm_result.decision
    if decision == "APPROVE" or (
        hasattr(decision, "value") and decision.value == "APPROVE"
    ):
        style = "green"
    elif decision == "REQUEST_CHANGES" or (
        hasattr(decision, "value") and decision.value == "REQUEST_CHANGES"
    ):
        style = "red"
    else:
        style = "yellow"

    console.print(Panel(output, title="PR Review", border_style=style))


@app.command()
def dashboard():
    """
    Launch the Flight Recorder Dashboard (Streamlit).
    """
    import os
    import subprocess
    import sys

    # Path to dashboard.py
    dashboard_path = os.path.join(os.path.dirname(__file__), "ui", "dashboard.py")

    if not os.path.exists(dashboard_path):
        console = Console()
        console.print(
            f"Error: Dashboard file not found at {dashboard_path}", style="bold red"
        )
        return

    # Run streamlit
    cmd = [sys.executable, "-m", "streamlit", "run", dashboard_path]
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


@app.command()
def proposals(
    action: str = typer.Argument(
        ..., help="Action: 'list', 'show', 'approve', or 'reject'"
    ),
    proposal_id: Optional[str] = typer.Argument(
        None, help="Proposal ID (for show/approve/reject)"
    ),
):
    """
    Manage enhancement proposals.
    """
    from nebulus_atom.commands.proposals import (
        approve_proposal,
        list_proposals,
        reject_proposal,
        show_proposal,
    )

    console = Console()

    if action == "list":
        result = list_proposals()
        console.print(result)
    elif action == "show":
        if not proposal_id:
            console.print("[red]Error: 'show' requires a proposal ID[/red]")
            return
        result = show_proposal(proposal_id)
        console.print(result)
    elif action == "approve":
        if not proposal_id:
            console.print("[red]Error: 'approve' requires a proposal ID[/red]")
            return
        result = approve_proposal(proposal_id)
        console.print(f"[green]{result}[/green]")
    elif action == "reject":
        if not proposal_id:
            console.print("[red]Error: 'reject' requires a proposal ID[/red]")
            return
        result = reject_proposal(proposal_id)
        console.print(f"[yellow]{result}[/yellow]")
    else:
        console.print(
            f"[red]Error: Unknown action '{action}'. Use: list, show, approve, or reject[/red]"
        )


@app.command("audit")
def audit(
    action: str = typer.Argument(..., help="Action: 'verify' or 'export'"),
    task_id: Optional[str] = typer.Option(
        None, "--task", "-t", help="Filter by task ID"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file for export"
    ),
):
    """
    Manage the audit trail for compliance.
    """
    from pathlib import Path
    from nebulus_swarm.overlord.audit_trail import (
        AuditTrail,
        load_or_create_signing_key,
    )

    console = Console()

    # Default paths
    atom_dir = Path.home() / ".atom"
    db_path = atom_dir / "audit_trail.db"
    key_path = atom_dir / "signing_key"

    signing_key = load_or_create_signing_key(key_path) if key_path.exists() else None
    trail = AuditTrail(str(db_path), signing_key)

    if action == "verify":
        is_valid, issues = trail.verify_integrity()
        if is_valid:
            console.print("[green]Audit trail integrity verified.[/green]")
        else:
            console.print("[red]Audit trail integrity check FAILED:[/red]")
            for issue in issues:
                console.print(f"  - {issue}")

    elif action == "export":
        import json

        data = trail.export(task_id)
        json_output = json.dumps(data, indent=2)

        if output:
            Path(output).write_text(json_output)
            console.print(f"[green]Exported to {output}[/green]")
        else:
            console.print(json_output)

    else:
        console.print(f"[red]Unknown action: {action}. Use 'verify' or 'export'.[/red]")


@app.command("orchestrate")
def orchestrate(
    goal: Optional[List[str]] = typer.Argument(
        None, help="Goal or task description to orchestrate"
    ),
    template: str = typer.Option(
        "build-feature",
        "--template",
        "-t",
        help="Workflow template to use (build-feature, fix-bug, research-and-draft)",
    ),
    list_templates_flag: bool = typer.Option(
        False, "--list-templates", "-l", help="List available workflow templates"
    ),
    workflow_file: Optional[str] = typer.Option(
        None, "--workflow", "-w", help="Path to custom workflow YAML file"
    ),
):
    """
    Run a multi-step workflow using the orchestration engine.

    Examples:
      atom orchestrate "Add JWT authentication to the API"
      atom orchestrate "Login returns 500 on special chars" --template fix-bug
      atom orchestrate --list-templates
      atom orchestrate "research topic" --template research-and-draft
    """
    import asyncio
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    # List templates and exit
    if list_templates_flag:
        from nebulus_atom.orchestrator.loader import list_templates, load_workflow

        available = list_templates()
        if not available:
            console.print("[yellow]No templates found.[/yellow]")
            return
        table = Table(title="Available Workflow Templates", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Steps")
        for name in available:
            try:
                wf = load_workflow(name)
                table.add_row(
                    name, wf.description[:80], ", ".join(s.id for s in wf.steps)
                )
            except Exception:
                table.add_row(name, "(error loading)", "")
        console.print(table)
        return

    if not goal:
        console.print(
            "[red]Provide a goal, e.g.: atom orchestrate 'build a REST API'[/red]"
        )
        raise typer.Exit(1)

    goal_text = " ".join(goal)

    async def run():
        from nebulus_atom.orchestrator.engine import WorkflowEngine
        from nebulus_atom.orchestrator.loader import load_workflow
        from nebulus_atom.controllers.agent_controller import AgentController
        from nebulus_atom.views.cli_view import CLIView

        # Bootstrap enough of the agent to get an OpenAI service
        view = CLIView()
        controller = AgentController(view=view)
        # _openai is initialized in AgentController.__init__
        engine = WorkflowEngine(controller._openai)

        # Load workflow
        source = workflow_file or template
        try:
            workflow = load_workflow(source)
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]Invalid workflow: {e}[/red]")
            raise typer.Exit(1)

        console.print(
            Panel(
                f"[bold cyan]Workflow:[/bold cyan] {workflow.name}\n"
                f"[bold cyan]Goal:[/bold cyan] {goal_text}\n"
                f"[bold cyan]Steps:[/bold cyan] {' → '.join(s.id for s in workflow.steps)}",
                title="🔄 Orchestrating",
            )
        )

        job = await engine.submit_and_wait(workflow, inputs={"goal": goal_text})

        # Display results
        for step in workflow.steps:
            result = job.step_results.get(step.id)
            if not result:
                continue
            icon = "✅" if result.status.value == "completed" else "❌"
            duration = (
                f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""
            )
            model = f" [{result.model_used}]" if result.model_used else ""
            console.print(f"\n{icon} [bold]{step.id}[/bold]{duration}{model}")
            if result.output:
                console.print(
                    Panel(
                        result.output[:2000]
                        + ("..." if len(result.output) > 2000 else "")
                    )
                )
            if result.error:
                console.print(f"[red]Error: {result.error}[/red]")

        status_color = "green" if job.status.value == "completed" else "red"
        console.print(
            f"\n[{status_color}]Job {job.status.value}: {job.id}[/{status_color}]"
        )

    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    app()
