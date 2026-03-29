# Demo & Swarm Infrastructure Setup Guide

## Overview

This guide covers everything needed to run the full Nebulus Atom demo:
- **Act 1**: Core CLI Agent (interactive coding)
- **Act 2**: Nebulus Swarm (Slack → GitHub → Docker minions → PR)
- **Act 3**: Dashboards (Flight Recorder + Swarm Monitor)

---

## Act 1: Core Agent (Ready Now)

### Prerequisites
- Python 3.12+ with venv at `venv/`
- LLM server running at `NEBULUS_BASE_URL` (configured in `.env`)

### Quick Start
```bash
cd /home/jlwestsr/projects/west_ai_labs/nebulus-atom
source venv/bin/activate
python3 -m nebulus_atom.main start
```

### Demo Flow
1. Agent starts, health-checks the LLM server, shows banner
2. **Context pinning**: `pin_file nebulus_atom/config.py` then `/context`
3. **RAG search**: Ask "index the codebase" first, then "search for how tools are dispatched"
4. **Skill creation**: Ask "create a skill called word_count that counts words in a file"
5. **TDD loop**: Ask "start a TDD cycle: implement a function that reverses a string"
6. **Auto-execution**: `create_plan`, `add_task`, `execute_plan`

---

## Act 2: Swarm Setup

### Step 1: Create a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Click **"Generate new token"**
3. Settings:
   - **Token name**: `nebulus-swarm-demo`
   - **Expiration**: 30 days
   - **Repository access**: Select "Only select repositories" → pick your demo repo (Step 2)
   - **Permissions**:
     - Repository permissions:
       - **Contents**: Read and write
       - **Issues**: Read and write
       - **Pull requests**: Read and write
       - **Metadata**: Read-only (auto-granted)
4. Click **"Generate token"** and save it — you'll need it for `.env.swarm`

### Step 2: Create a Demo GitHub Repository

1. Create a new repo: https://github.com/new
   - **Name**: `nebulus-swarm-demo` (or similar)
   - **Visibility**: Public (for demo) or Private
   - **Initialize with README**: Yes
2. Clone it locally:
   ```bash
   git clone git@github.com:<your-username>/nebulus-swarm-demo.git /tmp/nebulus-swarm-demo
   ```
3. Seed it with a simple Python project and issues:

   ```bash
   cd /tmp/nebulus-swarm-demo

   # Create a basic project structure
   mkdir -p src tests
   cat > src/calculator.py << 'PYEOF'
   """Simple calculator module."""


   def add(a: float, b: float) -> float:
       """Add two numbers."""
       return a + b


   def subtract(a: float, b: float) -> float:
       """Subtract b from a."""
       return a - b
   PYEOF

   cat > tests/test_calculator.py << 'PYEOF'
   from src.calculator import add, subtract


   def test_add():
       assert add(2, 3) == 5


   def test_subtract():
       assert subtract(5, 3) == 2
   PYEOF

   cat > requirements.txt << 'PYEOF'
   pytest>=7.0.0
   PYEOF

   git add -A && git commit -m "feat: initial calculator project" && git push
   ```

4. Create demo issues using the GitHub CLI:
   ```bash
   gh issue create --repo <your-username>/nebulus-swarm-demo \
     --title "Add multiply function to calculator" \
     --body "Add a multiply(a, b) function to src/calculator.py that multiplies two numbers. Include a test in tests/test_calculator.py."

   gh issue create --repo <your-username>/nebulus-swarm-demo \
     --title "Add divide function with zero-division handling" \
     --body "Add a divide(a, b) function to src/calculator.py. It should raise ValueError if b is 0. Include tests for both normal division and the error case."

   gh issue create --repo <your-username>/nebulus-swarm-demo \
     --title "Add docstring to all test functions" \
     --body "Each test function in tests/test_calculator.py should have a one-line docstring describing what it tests."
   ```

### Step 3: Create a Slack App

1. Go to https://api.slack.com/apps and click **"Create New App"**
2. Choose **"From scratch"**
   - **App Name**: `Nebulus Swarm`
   - **Workspace**: Select your workspace
3. **Enable Socket Mode**:
   - Go to **Socket Mode** in the left sidebar
   - Toggle **"Enable Socket Mode"** ON
   - Create an app-level token:
     - **Token Name**: `nebulus-socket`
     - **Scope**: `connections:write`
   - Save the token (starts with `xapp-`) — this is your `SLACK_APP_TOKEN`
4. **Add Bot Scopes**:
   - Go to **OAuth & Permissions**
   - Under "Bot Token Scopes", add:
     - `chat:write`
     - `channels:history`
     - `channels:read`
     - `app_mentions:read`
5. **Enable Events**:
   - Go to **Event Subscriptions**
   - Toggle **"Enable Events"** ON
   - Under "Subscribe to bot events", add:
     - `message.channels`
     - `app_mention`
6. **Install to Workspace**:
   - Go to **Install App**
   - Click **"Install to Workspace"** and authorize
   - Copy the **Bot User OAuth Token** (starts with `xoxb-`) — this is your `SLACK_BOT_TOKEN`
7. **Get Channel ID**:
   - In Slack, right-click the channel → "View channel details"
   - The Channel ID is at the bottom (starts with `C`)
   - Invite the bot: `/invite @Nebulus Swarm`

### Step 4: Configure Environment

Create `.env.swarm` in the project root:

```bash
cat > .env.swarm << 'EOF'
# Slack
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here
SLACK_CHANNEL_ID=C0123456789

# GitHub
GITHUB_TOKEN=github_pat_your-token-here
GITHUB_WATCHED_REPOS=your-username/nebulus-swarm-demo

# LLM Backend (same as core agent)
NEBULUS_BASE_URL=http://192.168.4.30:8080/v1
NEBULUS_API_KEY=admin
NEBULUS_MODEL=qwen3-coder-30b
NEBULUS_TIMEOUT=600
NEBULUS_STREAMING=false

# Minion Settings
MAX_CONCURRENT_MINIONS=2

# Cron (disable for demo — trigger manually via Slack)
CRON_ENABLED=false

# Model Routing (optional)
ROUTING_ENABLED=false

# PR Reviewer (optional)
REVIEWER_ENABLED=false
EOF
```

### Step 5: Build Docker Images

```bash
cd /home/jlwestsr/projects/west_ai_labs/nebulus-atom

# Build the minion image first (Overlord spawns these)
docker build -t nebulus-minion:latest -f nebulus_swarm/minion/Dockerfile .

# Build the overlord image
docker build -t nebulus-overlord:latest -f nebulus_swarm/overlord/Dockerfile .
```

### Step 6: Start the Swarm

```bash
# Start the Overlord
docker-compose -f docker-compose.swarm.yml up -d overlord

# Check it's running
docker logs -f overlord

# Verify health
curl http://localhost:8080/health
```

### Step 7: Demo Commands in Slack

```
work on your-username/nebulus-swarm-demo#1
```
This will:
1. Queue the issue
2. Spawn a minion container
3. Clone the repo
4. Read the issue
5. Write code
6. Create a PR
7. Report back in Slack

Other commands:
```
status          # Show active minions
queue           # Show pending work
history         # Show completed work
cancel <id>     # Kill a minion
sweep           # Process entire queue
```

---

## Act 3: Dashboards

### Flight Recorder (Core Agent)
```bash
source venv/bin/activate
python3 -m nebulus_atom.main dashboard
# Opens at http://localhost:8501
```

### Swarm Dashboard
```bash
source venv/bin/activate
streamlit run nebulus_swarm/dashboard/app.py
# Opens at http://localhost:8502
```

Note: The Swarm Dashboard reads from the Overlord's SQLite state database.
For local development, you may need to mount or copy the state DB.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Agent says "Cannot reach LLM server" | Check that your LLM server is running and `NEBULUS_BASE_URL` is correct |
| Agent shows "Model not found" | Run `curl $NEBULUS_BASE_URL/models` and update `NEBULUS_MODEL` in `.env` |
| Slack bot doesn't respond | Verify Socket Mode is enabled and `SLACK_APP_TOKEN` starts with `xapp-` |
| Minion can't clone repo | Check `GITHUB_TOKEN` has Contents read/write permission |
| Minion can't create PR | Check `GITHUB_TOKEN` has Pull requests read/write permission |
| Docker build fails | Ensure Docker is running: `docker info` |
| Dashboard shows no data | Run the agent first to generate telemetry data |
