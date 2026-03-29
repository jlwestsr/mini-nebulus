# Project Context & Rules

This file serves as the primary context injection point for the Nebulus Atom autonomous agent.
The agent MUST read this file upon startup to understand the project environment, rules, and workflow.

## 1. Core Documentation

- **[AI Directives](AI_DIRECTIVES.md)**: Coding standards, architecture (MVC), and commit conventions.
- **[Workflow](WORKFLOW.md)**: Branching strategy (Gitflow-lite) and development lifecycle.
- **[Project Goals](GEMINI.md)**: High-level objectives and communication protocol.
- **[CLAUDE.md](CLAUDE.md)**: Persona definition and project-specific instructions.

## 2. 🚨 MANDATORY: AI Behavior & Rules
**CRITICAL**: Before proposing any changes or running commands, you MUST review and adhere to the rules defined in:
👉 **[AI_DIRECTIVES.md](AI_DIRECTIVES.md)**

Key constraints from these rules include:
*   **MVC Architecture**: Strict separation of Models, Views, Controllers, and Services.
*   **Test-Driven**: `pytest` must pass before completion.
*   **Git-Ops**: Strict branching (Feature/Fix/Docs -> Develop -> Main).

## 3. 🗺️ Project Structure Overview

- `nebulus_atom/`: Core CLI agent logic.
- `nebulus_swarm/`: Multi-agent swarm orchestration.
- `docs/`: Project documentation and feature specs.
- `tests/`: Unit and integration testing suite.
- `scripts/`: Utility scripts and test runners.

## 4. 💻 CLI Reference

**Nebulus Atom** is a command-line tool. The primary entry point is `nebulus_atom/main.py`.

### Usage
```bash
python3 -m nebulus_atom.main [COMMAND] [ARGS]
```

### Commands
| Command | Description |
| :--- | :--- |
| `start` | Start the interactive agent. |
| `dashboard` | Launch the telemetry dashboard. |
| `docs` | View or list embedded documentation. |
| `overlord` | Control plane commands for swarm management. |

## 5. Coding Standards

1. **Unit Tests**: ALL changes must have accompanying unit tests in the `tests/` directory.
2. **Type Hinting**: Use Python type hints for all function definitions.
3. **Documentation**: All public functions must have docstrings (Google style).
4. **Conventional Commits**: Use `feat:`, `fix:`, `docs:`, or `chore:` prefixes.
