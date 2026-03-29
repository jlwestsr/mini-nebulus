# Overlord LLM-Powered Command Parser Design

**Date:** 2026-02-03
**Status:** APPROVED
**Authors:** @jlwestsr, Claude Opus 4.5

## Goal

Replace the Overlord's regex-based command parser with an LLM-powered interpreter that understands natural language, maintains conversational context, and gracefully falls back to regex when needed.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Model | Local 8B (Llama 3.1 8B) | Fast, free, sufficient for intent extraction |
| Context | Short-term (10 messages, 30 min TTL) | Covers "do that again" without complexity |
| Fallback | LLM → Clarification → Regex | Resilient, good UX |
| Interface | Keep existing Command/CommandType | Minimal changes to Overlord main loop |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LLMCommandParser                      │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ LLMClient   │  │ ContextStore│  │ RegexFallback   │ │
│  │ (8B model)  │  │ (per-channel│  │ (existing       │ │
│  │             │  │  memory)    │  │  CommandParser) │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
├─────────────────────────────────────────────────────────┤
│                     parse(text, channel_id, user_id)    │
│                            ↓                            │
│                     Returns: Command                    │
└─────────────────────────────────────────────────────────┘
```

**Flow:**
1. Message arrives with channel/user context
2. Fetch recent conversation history (last 10 messages)
3. Build prompt with: system instructions + command schema + history + new message
4. Call 8B model for interpretation
5. Parse LLM response into `Command` object
6. If confidence low → return clarification request
7. If LLM fails/timeout → fall back to regex parser
8. Store message + result in context for future reference

## LLM Prompt Design

```
You are the Nebulus Overlord's command interpreter. Parse user messages into structured commands.

## Available Commands

1. STATUS - Check what minions are doing
2. WORK - Start a minion on an issue (requires: issue_number, optional: repo)
3. STOP - Stop a minion (requires: issue_number OR minion_id)
4. QUEUE - Show pending work
5. PAUSE - Pause automatic processing
6. RESUME - Resume automatic processing
7. HISTORY - Show recent completed work
8. REVIEW - Review a PR (requires: pr_number, optional: repo)
9. HELP - Show available commands

## Response Format

Respond with JSON only:
{"command": "WORK", "issue_number": 42, "repo": null, "confidence": 0.95}

If uncertain, set confidence < 0.7 and include "clarification" field with options.

## Context

Default repo: {default_repo}
Recent conversation:
{conversation_history}

## Examples

User: "hey can you start working on issue 42"
→ {"command": "WORK", "issue_number": 42, "confidence": 0.95}

User: "do the same for 43"
→ {"command": "WORK", "issue_number": 43, "confidence": 0.90}

User: "what's up"
→ {"command": "STATUS", "confidence": 0.85}

User: "take a look at the PR"
→ {"command": "UNKNOWN", "confidence": 0.4, "clarification": "Which PR? Please specify a number like 'review PR #42'"}
```

## Context Store

```python
@dataclass
class ConversationEntry:
    """Single message in conversation history."""
    timestamp: datetime
    user_id: str
    message: str
    parsed_command: Optional[Command]

class ContextStore:
    """In-memory conversation context per channel."""

    def __init__(self, max_entries: int = 10, ttl_minutes: int = 30):
        self.max_entries = max_entries
        self.ttl_minutes = ttl_minutes
        self._contexts: Dict[str, List[ConversationEntry]] = {}

    def add(self, channel_id: str, user_id: str, message: str,
            command: Optional[Command]) -> None:
        """Store a message and its parsed result."""

    def get_history(self, channel_id: str) -> List[ConversationEntry]:
        """Get recent messages for context, pruning expired entries."""

    def get_last_command(self, channel_id: str) -> Optional[Command]:
        """Get the most recent successful command (for 'do that again')."""

    def clear(self, channel_id: str) -> None:
        """Clear context for a channel."""
```

**Format for LLM prompt:**
```
Recent conversation:
[2 min ago] user123: "work on issue 42" → WORK #42
[1 min ago] user123: "what's the status" → STATUS
[now] user123: "do the same for 43"
```

## Fallback & Error Handling

```
Message received
      ↓
┌─────────────────┐
│ Try LLM parse   │──timeout/error──→ Regex fallback
└────────┬────────┘                         ↓
         ↓                            Return Command
   confidence >= 0.7?
      ↓          ↓
     YES         NO
      ↓          ↓
  Return      Has clarification?
  Command        ↓         ↓
               YES        NO
                ↓          ↓
           Ask user    Regex fallback
           to clarify
```

**Implementation:**

```python
class LLMCommandParser:
    CONFIDENCE_THRESHOLD = 0.7
    LLM_TIMEOUT = 5.0  # seconds - fast for chat UX

    async def parse(self, text: str, channel_id: str, user_id: str) -> ParseResult:
        try:
            result = await asyncio.wait_for(
                self._llm_parse(text, channel_id),
                timeout=self.LLM_TIMEOUT
            )

            if result.confidence >= self.CONFIDENCE_THRESHOLD:
                return ParseResult(command=result.command)

            if result.clarification:
                return ParseResult(needs_clarification=True,
                                   message=result.clarification)

            return self._regex_fallback(text)

        except (asyncio.TimeoutError, LLMError):
            return self._regex_fallback(text)

    def _regex_fallback(self, text: str) -> ParseResult:
        """Use existing CommandParser as fallback."""
        return ParseResult(command=self.regex_parser.parse(text))
```

## Configuration

```python
@dataclass
class OverlordLLMConfig:
    enabled: bool = True  # Can disable to use regex only
    base_url: str = "http://localhost:5000/v1"
    model: str = "llama-3.1-8b"
    timeout: float = 5.0
    confidence_threshold: float = 0.7
    context_max_entries: int = 10
    context_ttl_minutes: int = 30
```

Environment variables:
- `OVERLORD_LLM_ENABLED` - Toggle LLM parsing (default: true)
- `OVERLORD_LLM_MODEL` - Model name (default: llama-3.1-8b)
- `OVERLORD_LLM_TIMEOUT` - Timeout in seconds (default: 5.0)
- `OVERLORD_LLM_CONFIDENCE` - Confidence threshold (default: 0.7)

## Files to Create/Modify

**New Files:**

| File | Purpose | ~Lines |
|------|---------|--------|
| `nebulus_swarm/overlord/llm_parser.py` | LLMCommandParser, ContextStore, ParseResult | ~250 |
| `tests/test_llm_parser.py` | Unit tests for LLM parsing | ~150 |

**Modified Files:**

| File | Change |
|------|--------|
| `nebulus_swarm/overlord/main.py` | Replace `CommandParser` with `LLMCommandParser` |
| `nebulus_swarm/config.py` | Add `OverlordLLMConfig` |

**Unchanged:**
- `command_parser.py` - Retained as regex fallback

## Testing

```python
class TestLLMCommandParser:
    def test_parse_natural_work_command(self):
        """'hey start working on issue 42' → WORK #42"""

    def test_parse_with_context(self):
        """'do the same for 43' after WORK #42 → WORK #43"""

    def test_low_confidence_clarification(self):
        """Ambiguous message returns clarification request"""

    def test_fallback_on_timeout(self):
        """LLM timeout falls back to regex silently"""

    def test_context_expiry(self):
        """Old messages pruned after TTL"""

class TestContextStore:
    def test_max_entries_enforced(self):
    def test_ttl_expiry(self):
    def test_get_last_command(self):
```

## User Experience Examples

**Before (regex):**
- "work on #42" ✓
- "hey can you start on issue 42" ✗ UNKNOWN

**After (LLM):**
- "work on #42" ✓
- "hey can you start on issue 42" ✓
- "do the same for 43" ✓ (with context)
- "what's happening" ✓ → STATUS
- "stop that" ✓ (stops last started minion)
- "check the PR" → "Which PR? Please specify a number like 'review PR #42'"

---

**Document History:**
| Date | Author | Change |
|------|--------|--------|
| 2026-02-03 | @jlwestsr, Claude | Initial design |
