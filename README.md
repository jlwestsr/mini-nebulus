# Nebulus Atom

![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)
![Version](https://img.shields.io/badge/version-2.6.0-green.svg)
![Tests](https://img.shields.io/badge/tests-1746%20passing-brightgreen.svg)
![License](https://img.shields.io/badge/license-proprietary-red.svg)

> **v2.6.0** - A professional, autonomous AI engineer CLI powered by local LLMs for GitHub automation, code generation, and multi-agent orchestration.

Nebulus Atom is a privacy-first, self-hosted AI coding assistant and autonomous software engineering agent. It connects to local LLM servers (Nebulus Prime, Nebulus Edge, Ollama, TabbyAPI, vLLM) to provide intelligent code assistance, automated GitHub issue processing, and multi-agent task orchestration. Perfect for developers who want AI-powered coding tools without cloud dependencies.

**Key capabilities**: Autonomous code generation • GitHub issue automation • Multi-agent swarm orchestration • Local RAG code search • TDD automation • Docker-based minion dispatch • Cross-project dependency analysis • Slack-controlled daemon mode • Proactive monitoring • Approval workflows • Test-driven development • CI/CD integration

---

## 🚀 Why Nebulus Atom?

Nebulus Atom establishes an **AI Collaboration Framework** that ensures human-AI teams work within strict governance, shared context, and professional engineering standards.

### Core Philosophy
- **AI-Native Context**: Every project ships with `AI_DIRECTIVES.md`, `CLAUDE.md`, and `GEMINI.md` to ground your AI agent.
- **Strict Governance**: Prevent AI "shadow logic" and reinvention of existing utilities.
- **Production-Ready**: Enforces Type Hinting, Google-style docstrings, and 100% logic coverage in tests.

---

## 🛠️ Installation

```bash
# Clone and install
git clone git@github.com:jlwestsr/nebulus-atom.git
cd nebulus-atom
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure your LLM server
cp .env.example .env
# Edit .env with your server URL and model name

# Run
python3 -m nebulus_atom.main start
```

See the [Installation Guide](https://github.com/jlwestsr/nebulus-atom/wiki/Installation) for detailed setup instructions.

---

## 📁 Project Structure

```text
.
├── AI_DIRECTIVES.md       # Operational guardrails for AI
├── CLAUDE.md              # Persona & project instructions
├── GEMINI.md              # PM communication protocol
├── WORKFLOW.md            # Git & development process
├── nebulus_atom/           # Core CLI agent (MVC)
│   ├── models/             # Data structures
│   ├── views/              # UI (Rich TUI)
│   ├── controllers/        # Orchestration
│   ├── services/           # LLM, RAG, Skills, MCP
│   └── main.py             # Entry point
├── nebulus_swarm/           # Multi-agent swarm
│   ├── overlord/            # Meta-orchestrator & control plane
│   ├── minion/              # Worker agents
│   ├── dashboard/           # Streamlit monitoring
│   └── reviewer/            # PR review
└── tests/                   # 1507 tests
```

---

## 📜 AI-Native Coding Standards

Nebulus Atom projects enforce the following by default:
- **Type Hinting**: Mandatory for all function signatures.
- **Modular Logic**: Business logic lives in `services/` and `controllers/`, never in notebooks or main entry points.
- **Docstrings**: Google-style documentation for all public modules.
- **Automated Verification**: Strict adherence to MVC and SOLID principles.

---

## 🤝 Contributing

We are building the future of AI-native engineering. If you have ideas for improving agentic governance or swarm intelligence, please:
1. Fork the repo.
2. Create a feature branch off `develop`.
3. Open a Pull Request.

---

## 📄 License

See repository for license details.

---
*Built with ❤️ by [JLWestSr](https://github.com/jlwestsr)*
