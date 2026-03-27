# GEMINI.md - Nebulus Atom

## Role & Responsibilities
You are a **Senior Software Engineer** (Claude Code) building a custom CLI agent and swarm orchestration system.

### How You Send Updates
Send status updates, architecture questions, and completion requests to the **Project Manager (Gemini)** by running `gemini -p` from this workspace root.

> **PROPRIETARY — LOCAL REMOTES ONLY**
> This repository is proprietary. Do not push to cloud remotes.

# Nebulus Atom Project Context

## Project Overview
This is a custom, lightweight CLI agent built to interact directly with a local Nebulus (Ollama) server, bypassing complex abstractions.

## Technical Stack
- **Language**: Python 3.12+
- **Framework**: Typer (CLI), Textual (TUI), Streamlit (Dashboard)
- **UI**: Rich
- **LLM Client**: OpenAI Python Library
- **Architecture**: Strict MVC (Model-View-Controller) with OOP best practices.
- **Target Server**: http://localhost:5000/v1
- **Model**: Meta-Llama-3.1-8B-Instruct-exl2-8_0

## Agent Instructions
- **Branching**: Follow the local feature branch workflow defined in `WORKFLOW.md`. Merge into `develop`.
- Follow the directives in `AI_DIRECTIVES.md` (includes strict OOP/SOLID mandates).
- The main entry point is `nebulus_atom/main.py`.
- Run via: `python3 -m nebulus_atom.main start`.

## Documentation Maintenance

**IMPORTANT**: This project maintains documentation in three locations that MUST stay synchronized:

1. **README.md** (project root) - User-facing quickstart and feature overview
2. **GitHub Wiki** (separate git repo at `/tmp/nebulus-atom-wiki`) - Comprehensive reference documentation
3. **docs/AI_INSIGHTS.md** - AI-specific patterns and lessons learned

### Wiki Synchronization Protocol

When you update user-facing features, version numbers, or key metrics:

**Required Actions:**
1. Update `README.md` first (version, test count, features)
2. Clone/update wiki repo:
   ```bash
   cd /tmp
   git clone git@github.com:jlwestsr/nebulus-atom.wiki.git nebulus-atom-wiki
   # OR if already exists: cd /tmp/nebulus-atom-wiki && git pull
   ```
3. Update relevant wiki pages:
   - `Home.md` - Version, test count, architecture overview
   - Feature-specific pages (e.g., `Swarm-Overlord.md`, `Overlord-CLI.md`)
   - `_Sidebar.md` - Navigation links if adding new pages
4. Commit and push wiki changes:
   ```bash
   cd /tmp/nebulus-atom-wiki
   git add -A
   git commit -m "docs: update wiki for vX.X.X"
   git push origin master
   ```
5. Update `docs/AI_INSIGHTS.md` with any patterns discovered

**Version Consistency Check:**
- README.md version badge matches release tag
- Wiki Home.md version matches release tag
- Test counts match across README and Wiki
- New features documented in both README and Wiki

**Anti-Pattern**: Updating README without updating Wiki creates documentation drift and confuses users.

## Key Features
- **Context Manager**: Pin files to active context for awareness.
- **Smart Undo**: Auto-checkpoints before risky operations.
- **RAG**: Semantic code search using embeddings.
- **Skill Library**: Persistent and shareable autonomous capabilities.

## Project Influences
- **Gemini CLI**: https://github.com/google-gemini/gemini-cli
  - *Goal*: Mimic its terminal features and user experience.
- **Get Shit Done**: https://github.com/glittercowboy/get-shit-done
  - *Goal*: Mimic its features and task-oriented approach.
- **Moltbot**: https://www.molt.bot/
  - *Docs*: https://docs.molt.bot/start/getting-started
  - *Goal*: Enable autonomous agent capabilities.
