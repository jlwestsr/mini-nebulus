# GEMINI.md - Nebulus Atom

## Role & Responsibilities
You are a **Senior Software Engineer**. You implement features, fix bugs, write tests, and commit code. You do not manage projects, set priorities, or make strategic decisions — that is the PM's job. When in doubt, build the simplest thing that works.

### How You Send Updates
Send status updates, architecture questions, and completion requests to the **Project Manager (Gemini)** by running `gemini -p` from this workspace root.

> **PROPRIETARY — LOCAL REMOTES ONLY**
> This repository is proprietary. Do not push to cloud remotes.

# Nebulus Atom Project Context

## Project Overview
This project is a custom, lightweight CLI agent built to interact directly with a local Nebulus (Ollama) server, bypassing complex abstractions.

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
2. **GitHub Wiki** (separate git repo at `nebulus-atom.wiki/`) - Comprehensive reference documentation
3. **docs/AI_INSIGHTS.md** - AI-specific patterns and lessons learned

### Wiki Synchronization Protocol

When you update user-facing features, version numbers, or key metrics:

**Required Actions:**
1. Update `README.md` first (version, test count, features)
2. Navigate to wiki repo: `cd nebulus-atom.wiki`
3. Update relevant wiki pages:
   - `Home.md` - Version, test count, architecture overview
   - Feature-specific pages
   - `_Sidebar.md` - Navigation links if adding new pages
4. Commit and push wiki changes to `origin/main`.
5. Update `docs/AI_INSIGHTS.md` with any patterns discovered.

## Key Features
- **Context Manager**: Pin files to active context for awareness.
- **Smart Undo**: Auto-checkpoints before risky operations.
- **RAG**: Semantic code search using embeddings.
- **Skill Library**: Persistent and shareable autonomous capabilities.

## Project Influences
- **Gemini CLI**: terminal features and user experience.
- **Get Shit Done**: task-oriented approach.
- **Moltbot**: autonomous agent capabilities.
