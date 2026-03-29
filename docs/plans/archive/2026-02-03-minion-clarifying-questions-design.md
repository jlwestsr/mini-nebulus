# Minion Clarifying Questions via Slack Design

**Date:** 2026-02-03
**Status:** APPROVED
**Authors:** @jlwestsr, Claude Opus 4.5

## Goal

Allow Minions to ask clarifying questions via Slack when issue requirements are unclear, pause for human input, and resume work with the answer. Questions are an optimization, never a blocker - every failure path ends with the Minion continuing using its best judgment.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| When to ask | Before or during work, max 3 questions | Covers both vague issues and mid-work decisions |
| Wait mechanism | Keep alive, poll, 10 min timeout | Simple, no idle waste due to timeout |
| Answer routing | QUESTION event + GET endpoint | Extends existing Reporter pattern |
| Slack UX | Threaded conversations | Natural, supports multiple Minions |
| Agent mechanism | Reuse task_blocked, change lifecycle | Minimal new components |

## Architecture

```
BEFORE:
Agent calls task_blocked(question) → Minion dies → Human sees GitHub comment

AFTER:
Agent calls task_blocked(question) → Minion pauses
  → Reporter sends QUESTION event to Overlord
  → Overlord posts to Slack thread
  → Human replies in thread
  → Overlord stores answer
  → Minion polls, gets answer
  → Answer injected into agent conversation
  → Agent resumes work
  → (after 3 questions OR 10 min timeout → auto-continue)
```

## Reporter Changes

New event type and two new methods:

```python
class EventType(Enum):
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    COMPLETE = "complete"
    ERROR = "error"
    QUESTION = "question"  # NEW

async def question(
    self, question_text: str, blocker_type: str, question_id: str
) -> bool:
    """Send a question to the Overlord for human input."""
    payload = ReportPayload(
        minion_id=self.minion_id,
        event=EventType.QUESTION,
        issue=self.issue_number,
        message=question_text,
        data={
            "blocker_type": blocker_type,
            "question_id": question_id,
        },
    )
    return await self._send_report(payload)

async def poll_answer(
    self, question_id: str, timeout: int = 600, interval: int = 15
) -> Optional[str]:
    """Poll the Overlord for an answer to a pending question."""
    elapsed = 0
    while elapsed < timeout:
        session = await self._get_session()
        url = f"{self.callback_url.rsplit('/', 1)[0]}/answer/{self.minion_id}"
        async with session.get(url, params={"question_id": question_id}) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("answered"):
                    return data["answer"]
        await asyncio.sleep(interval)
        elapsed += interval
    return None  # Timed out
```

## Overlord Changes

### Pending Questions Store

```python
@dataclass
class PendingQuestion:
    minion_id: str
    question_id: str
    issue_number: int
    repo: str
    question_text: str
    thread_ts: str  # Slack thread timestamp for matching replies
    asked_at: datetime
    answer: Optional[str] = None
    answered: bool = False
```

### QUESTION Event Handler

In `/minion/report`:

```python
elif event == "question":
    question_id = report_data.get("question_id")
    question_text = message

    # Post to Slack as a threaded message
    thread_ts = await self.slack.post_question(
        minion_id, issue_number, question_text, timeout_minutes=10
    )

    # Store pending question
    self._pending_questions[minion_id] = PendingQuestion(
        minion_id=minion_id,
        question_id=question_id,
        issue_number=issue_number,
        repo=repo,
        question_text=question_text,
        thread_ts=thread_ts,
        asked_at=datetime.now(),
    )
```

### Answer Endpoint

```python
# GET /minion/answer/{minion_id}
async def _answer_handler(self, request):
    minion_id = request.match_info["minion_id"]
    pending = self._pending_questions.get(minion_id)
    if not pending or not pending.answered:
        return web.json_response({"answered": False})
    return web.json_response({
        "answered": True,
        "answer": pending.answer,
    })
```

### Slack Thread Reply Matching

When a message arrives in a thread, check if `thread_ts` matches a pending question:

```python
# In SlackBot thread reply handler
for pending in self._pending_questions.values():
    if pending.thread_ts == thread_ts and not pending.answered:
        pending.answer = reply_text
        pending.answered = True
        break
```

### Slack Message Format

```
🤔 Minion `abc-123` on #42 has a question:

> The issue says "improve performance" but doesn't specify which
> endpoint. Should I focus on /api/users (slowest at 2.3s) or
> /api/search (most traffic)?

Reply in this thread to answer. Auto-continuing in 10 minutes.
```

## Minion Lifecycle Changes

Modified `_do_work()` with question loop:

```python
MAX_QUESTIONS = 3
QUESTION_TIMEOUT = 600  # 10 minutes

questions_asked = 0

while True:
    result: AgentResult = agent.run()

    if result.status == AgentStatus.COMPLETED:
        return True

    elif result.status == AgentStatus.BLOCKED and result.question:
        questions_asked += 1

        if questions_asked > MAX_QUESTIONS:
            agent.inject_message("No more questions available. Use your best judgment.")
            continue

        question_id = f"q-{self.config.minion_id}-{questions_asked}"
        await self.reporter.question(result.question, result.blocker_type, question_id)

        answer = await self.reporter.poll_answer(question_id, timeout=QUESTION_TIMEOUT)

        if answer:
            agent.inject_message(f"Human response: {answer}")
        else:
            agent.inject_message(
                "No response received within 10 minutes. Use your best judgment."
            )
        # Loop continues - agent.run() resumes with injected context

    else:
        # ERROR or TURN_LIMIT or BLOCKED without question
        return False
```

### MinionAgent.inject_message()

New method to append context to conversation history:

```python
def inject_message(self, text: str) -> None:
    """Inject a user message into conversation history for next run."""
    self._history.append({"role": "user", "content": text})
```

### System Prompt Update

Add to prompt_builder.py:

```
When requirements are unclear or you face a decision with multiple valid approaches,
call `task_blocked` with a question in the `question` field. You may receive a
human response and continue working. Limit questions to what's truly necessary.
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Overlord down when question sent | Reporter returns False → inject "use best judgment", continue |
| Slack post fails | Overlord logs warning → Minion times out, continues |
| Human never replies | poll_answer() returns None after 10 min → continue |
| Multiple questions rapid-fire | Cap at 3 questions per Minion run |
| Overlord restarts during poll | In-memory questions lost → Minion times out, continues |
| Thread reply from wrong user | Accept any reply in the thread (team collaboration) |

## Files to Create/Modify

| File | Change |
|------|--------|
| `nebulus_swarm/minion/reporter.py` | Add QUESTION event, `question()`, `poll_answer()` |
| `nebulus_swarm/minion/main.py` | Rework `_do_work()` with question loop |
| `nebulus_swarm/minion/agent/minion_agent.py` | Add `inject_message()` method |
| `nebulus_swarm/minion/agent/prompt_builder.py` | Update system prompt |
| `nebulus_swarm/overlord/main.py` | Handle QUESTION event, add answer endpoint, thread matching |
| `nebulus_swarm/overlord/slack_bot.py` | Add `post_question()`, thread reply handler |
| `tests/test_minion_question.py` | New test file |

## Testing

- Reporter question/poll_answer methods (mocked HTTP)
- Overlord QUESTION event handling and answer endpoint
- Minion question loop with mock answers
- Timeout auto-continue behavior
- Max questions cap enforcement (3 questions then auto-continue)
- Thread reply matching in SlackBot

---

**Document History:**
| Date | Author | Change |
|------|--------|--------|
| 2026-02-03 | @jlwestsr, Claude | Initial design |
