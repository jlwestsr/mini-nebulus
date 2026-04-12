"""Focus Context System — ecosystem-aware context builder for PM mode.

Parses BUSINESS.md, conductor/tracks.md, and recent plan files to build
a structured context that informs strategic decision-making prompts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Max lines to read from each plan file to avoid prompt bloat
_PLAN_LINE_LIMIT = 200


@dataclass
class FocusContext:
    """Parsed ecosystem context for prompt enrichment."""

    business_priorities: list[dict] = field(default_factory=list)
    governance_rules: list[str] = field(default_factory=list)
    tech_stack: list[dict] = field(default_factory=list)
    active_tracks: list[dict] = field(default_factory=list)
    plan_summaries: list[dict] = field(default_factory=list)
    workspace_root: Path = field(default_factory=lambda: Path.cwd())

    def format_for_prompt(self) -> str:
        """Format the context as a structured string for LLM prompts.

        Returns:
            Markdown-formatted context string.
        """
        sections: list[str] = []

        if self.business_priorities:
            lines = ["## Business Priorities"]
            for p in self.business_priorities:
                name = p.get("name", "unnamed")
                priority = p.get("priority", "")
                desc = p.get("description", "")
                lines.append(f"- **{name}** ({priority}): {desc}")
            sections.append("\n".join(lines))

        if self.governance_rules:
            lines = ["## Governance Rules"]
            for rule in self.governance_rules:
                lines.append(f"- {rule}")
            sections.append("\n".join(lines))

        if self.tech_stack:
            lines = ["## Tech Stack"]
            for item in self.tech_stack:
                name = item.get("name", "")
                role = item.get("role", "")
                lines.append(f"- **{name}**: {role}")
            sections.append("\n".join(lines))

        if self.active_tracks:
            lines = ["## Active Tracks"]
            for track in self.active_tracks:
                name = track.get("name", "")
                status = track.get("status", "")
                lines.append(f"- **{name}**: {status}")
            sections.append("\n".join(lines))

        if self.plan_summaries:
            lines = ["## Recent Plans"]
            for plan in self.plan_summaries:
                title = plan.get("title", "untitled")
                date = plan.get("date", "")
                summary = plan.get("summary", "")
                lines.append(f"### {title} ({date})")
                lines.append(summary)
            sections.append("\n".join(lines))

        if not sections:
            return "## Ecosystem Context\nNo context available."

        return "# Ecosystem Focus Context\n\n" + "\n\n".join(sections)


def build_focus_context(workspace_root: Path) -> FocusContext:
    """Build a FocusContext by parsing workspace documentation files.

    Args:
        workspace_root: Root path of the workspace (e.g. ~/projects/west_ai_labs).

    Returns:
        Populated FocusContext. Missing files result in empty fields, not errors.
    """
    ctx = FocusContext(workspace_root=workspace_root)

    # Parse BUSINESS.md
    business_path = workspace_root / "BUSINESS.md"
    if business_path.is_file():
        try:
            parsed = _parse_business_md(business_path)
            ctx.business_priorities = parsed.get("priorities", [])
            ctx.governance_rules = parsed.get("governance", [])
            ctx.tech_stack = parsed.get("tech_stack", [])
        except Exception:
            logger.warning("Failed to parse %s", business_path, exc_info=True)

    # Parse conductor/tracks.md
    tracks_path = workspace_root / "conductor" / "tracks.md"
    if tracks_path.is_file():
        try:
            ctx.active_tracks = _parse_tracks_md(tracks_path)
        except Exception:
            logger.warning("Failed to parse %s", tracks_path, exc_info=True)

    # Gather recent plans
    plans_dir = workspace_root / "docs" / "plans"
    if plans_dir.is_dir():
        try:
            ctx.plan_summaries = _gather_recent_plans(plans_dir)
        except Exception:
            logger.warning("Failed to gather plans from %s", plans_dir, exc_info=True)

    return ctx


def _parse_business_md(path: Path) -> dict:
    """Parse BUSINESS.md for priorities, governance rules, and tech stack.

    Extracts data from markdown tables and bullet lists using regex.

    Args:
        path: Path to BUSINESS.md.

    Returns:
        Dict with keys: priorities, governance, tech_stack.
    """
    content = path.read_text()
    result: dict = {"priorities": [], "governance": [], "tech_stack": []}

    # Extract priorities from table rows: | name | priority | description |
    priority_pattern = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*(high|medium|low|critical)\s*\|\s*([^|]*?)\s*\|",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in priority_pattern.finditer(content):
        name = match.group(1).strip()
        # Skip header separator rows
        if name.startswith("-") or name.startswith(":"):
            continue
        result["priorities"].append(
            {
                "name": name,
                "priority": match.group(2).strip().lower(),
                "description": match.group(3).strip(),
            }
        )

    # Extract governance rules from bullet lists under governance heading
    gov_section = _extract_section(content, r"governance|rules|constraints")
    if gov_section:
        for line in gov_section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                rule = stripped[2:].strip()
                if rule:
                    result["governance"].append(rule)

    # Extract tech stack from table rows: | name | role |
    tech_pattern = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
        re.MULTILINE,
    )
    tech_section = _extract_section(content, r"tech\s*stack|technology|stack")
    if tech_section:
        for match in tech_pattern.finditer(tech_section):
            name = match.group(1).strip()
            if name.startswith("-") or name.startswith(":") or name.lower() == "name":
                continue
            result["tech_stack"].append(
                {
                    "name": name,
                    "role": match.group(2).strip(),
                }
            )

    return result


def _extract_section(content: str, heading_pattern: str) -> Optional[str]:
    """Extract content under a markdown heading matching a regex pattern.

    Args:
        content: Full markdown content.
        heading_pattern: Regex pattern to match the heading text.

    Returns:
        The section content (between the heading and the next heading), or None.
    """
    pattern = re.compile(
        rf"^(#+)\s+.*?(?:{heading_pattern}).*?$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return None

    level = len(match.group(1))
    start = match.end()

    # Find next heading at same or higher level
    next_heading = re.compile(
        rf"^#{{{1},{level}}}\s+",
        re.MULTILINE,
    )
    next_match = next_heading.search(content, start)
    end = next_match.start() if next_match else len(content)

    return content[start:end]


def _parse_tracks_md(path: Path) -> list[dict]:
    """Parse conductor/tracks.md for active track information.

    Expects markdown with track headings and status indicators.

    Args:
        path: Path to tracks.md.

    Returns:
        List of dicts with keys: name, status, description.
    """
    content = path.read_text()
    tracks: list[dict] = []

    # Match track headings: ## Track N: Name or ### Track Name
    track_pattern = re.compile(
        r"^#{2,3}\s+(?:Track\s+\d+[:.]\s*)?(.+)$",
        re.MULTILINE,
    )

    for match in track_pattern.finditer(content):
        name = match.group(1).strip()
        # Look for status in the lines following the heading
        start = match.end()
        remaining = content[start : start + 500]
        status = "unknown"

        # Check for common status markers
        for marker, label in [
            ("complete", "complete"),
            ("done", "complete"),
            ("in progress", "in-progress"),
            ("planned", "planned"),
            ("blocked", "blocked"),
        ]:
            if marker in remaining[:200].lower():
                status = label
                break

        desc_lines = [
            line.strip()
            for line in remaining.splitlines()[:3]
            if line.strip() and not line.strip().startswith("#")
        ]
        description = " ".join(desc_lines)[:200]

        tracks.append(
            {
                "name": name,
                "status": status,
                "description": description,
            }
        )

    return tracks


def _gather_recent_plans(plans_dir: Path, limit: int = 3) -> list[dict]:
    """Gather the most recent plan summaries from docs/plans/.

    Reads markdown files, sorted by filename (which should be date-prefixed).
    Truncates each plan to _PLAN_LINE_LIMIT lines.

    Args:
        plans_dir: Path to the plans directory.
        limit: Maximum number of plans to include.

    Returns:
        List of dicts with keys: title, date, summary, filename.
    """
    md_files = sorted(plans_dir.glob("*.md"), reverse=True)[:limit]
    plans: list[dict] = []

    for md_file in md_files:
        try:
            lines = md_file.read_text().splitlines()[:_PLAN_LINE_LIMIT]
            content = "\n".join(lines)

            # Extract title from first heading
            title = md_file.stem
            title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()

            # Extract date from filename (YYYY-MM-DD prefix)
            date = ""
            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", md_file.name)
            if date_match:
                date = date_match.group(1)

            # Use first non-heading paragraph as summary
            summary_lines: list[str] = []
            for line in lines[1:]:
                stripped = line.strip()
                if stripped.startswith("#"):
                    if summary_lines:
                        break
                    continue
                if stripped:
                    summary_lines.append(stripped)
                elif summary_lines:
                    break

            summary = " ".join(summary_lines)[:500]

            plans.append(
                {
                    "title": title,
                    "date": date,
                    "summary": summary,
                    "filename": md_file.name,
                }
            )
        except Exception:
            logger.warning("Failed to read plan: %s", md_file, exc_info=True)

    return plans
