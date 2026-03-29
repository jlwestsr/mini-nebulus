# Phase 7: Minion Agent Design

## Overview

The Minion agent is the autonomous coding brain that powers Nebulus Swarm Minions. It runs inside Docker containers, receives GitHub issues, and implements solutions through iterative LLM-guided tool execution.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Autonomy level | Full agentic workflow | Matches Claude Code capability |
| Skill storage | Repo at `.nebulus/skills/` | Version controlled, PR reviewable |
| Tool implementation | Reuse nebulus_atom ToolRegistry | Proven, consistent behavior |
| Completion signal | Explicit `task_complete` tool | Clear, agent-controlled |
| Skill PR approval | Human required | Safety for privileged operation |

## Architecture

```
┌─────────────────────────────────────────────┐
│              MinionAgent                     │
│  (orchestrates the agentic loop)            │
├─────────────────────────────────────────────┤
│              ToolExecutor                    │
│  (executes tools, manages file state)       │
├─────────────────────────────────────────────┤
│              LLMClient                       │
│  (OpenAI-compatible API to Nebulus)         │
└─────────────────────────────────────────────┘
```

## Agent Loop

```
1. Build messages: system prompt + conversation history
              ↓
2. Call LLM with tools schema
              ↓
3. Parse response for tool calls
              ↓
4. If task_complete → return success with summary
   Else → execute tools, append results, check limits, loop
```

**Safety nets:**
- Turn limit: 50 turns (configurable)
- Timeout: 30 minutes (container-level)
- Error threshold: 3 consecutive tool errors → stop

## Tool Schema

**File Operations:**
- `read_file` - Read file contents with line range support
- `write_file` - Create or overwrite a file
- `edit_file` - Replace specific text in a file
- `list_directory` - List files/folders in a path
- `search_files` - Grep for pattern across files
- `glob_files` - Find files matching a pattern

**Execution:**
- `run_command` - Execute shell command with timeout

**Completion:**
- `task_complete` - Signal work is done
- `task_blocked` - Signal cannot proceed, explain why

**Skills:**
- `list_skills` - Show available skills
- `use_skill` - Load skill instructions into context

All file operations scoped to `/workspace`.

## Skill System

Skills stored in `.nebulus/skills/` as YAML:

```yaml
name: add-api-endpoint
description: Add a new REST API endpoint
version: 1.0.0
tags: [api, backend]

triggers:
  keywords: [endpoint, api, route]
  file_patterns: ["**/routes.py"]

instructions: |
  When adding an API endpoint:
  1. Check existing patterns
  2. Create route handler
  3. Add validation
  4. Write tests
```

## Skill Guardrails

When PR touches `.nebulus/skills/`:
1. Auto-apply `skill-change` label
2. Block auto-merge
3. Run schema validation
4. Run security scan for forbidden patterns
5. Require human approval

**Forbidden patterns in skill instructions:**
- Destructive commands: `rm -rf`
- Remote code execution: `curl|sh`
- Dynamic code execution functions
- Dynamic import functions
- System paths: `/etc/`, `~/.ssh`
- Token references: `GITHUB_TOKEN`

## Error Handling

| Scenario | Tool/Action | Overlord Response |
|----------|-------------|-------------------|
| Work complete | `task_complete` | Create PR, trigger review |
| Cannot proceed | `task_blocked` | Comment on issue, remove label |
| Tool errors (3x) | Auto-detected | Mark `needs-attention` |
| Turn limit | Auto-detected | Mark `needs-attention` |
| Timeout | Watchdog | Mark `needs-attention` |

## File Structure

```
nebulus_swarm/minion/
├── agent/
│   ├── minion_agent.py    # Core agent loop
│   ├── llm_client.py      # OpenAI SDK wrapper
│   ├── tool_executor.py   # Tool execution
│   ├── prompt_builder.py  # System prompt construction
│   └── tools.py           # Tool definitions
└── skills/
    ├── loader.py          # Skill loading
    ├── validator.py       # Schema validation
    └── schema.py          # Pydantic models
```

## Implementation Steps

1. LLM Client & Basic Agent Loop
2. Tool Definitions & Executor
3. Prompt Builder & Integration
4. Skill System Foundation
5. Skill Guardrails
6. Tests & Documentation

## Estimated Size

~1,300 new lines + ~100 lines modified
