# PR Review Integration Design

## Goal

When a Minion creates a PR, automatically run the full PR review pipeline and post results as a comment, leaving merge to humans.

## Flow

```
Minion completes work
    ↓
Creates PR
    ↓
Triggers ReviewWorkflow
    ↓
├── Run automated checks (tests, lint, security)
├── Run LLM code review
└── Compile full report
    ↓
Post review as PR comment
    ↓
Report success to Overlord (with review summary)
    ↓
Human reviews and merges
```

## Key Decisions

- Review runs inside the Minion container before it exits
- No auto-merge - humans always approve
- Full report posted: checks + LLM analysis + recommendation
- Review result included in Overlord completion report

## Implementation

### Integration Point

`nebulus_swarm/minion/main.py` in the `_create_pr()` method, immediately after the PR is created and before reporting completion.

### New Method: `_review_pr()`

```python
async def _review_pr(self, pr_number: int) -> Optional[WorkflowResult]:
    """Run PR review after creation."""
    config = ReviewConfig(
        github_token=self.config.github_token,
        llm_base_url=self.config.nebulus_base_url,
        llm_model=self.config.nebulus_model,
        auto_merge_enabled=False,  # Never auto-merge
        run_local_checks=True,
    )
    workflow = ReviewWorkflow(config)
    return await workflow.review_pr(self.config.repo, pr_number)
```

### Comment Format

```markdown
## 🤖 Minion Code Review

### Automated Checks
- ✅ Tests: 42 passed
- ⚠️ Linting: 2 warnings
- ✅ Security: No issues

### Code Review
[LLM analysis here]

### Recommendation
**APPROVE** (Confidence: 85%)

---
*Reviewed by Nebulus Swarm Minion `minion-test-003`*
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| LLM timeout | Post partial review (checks only), log warning |
| Checks fail to run | Post LLM review only, note checks skipped |
| Review post fails | Log error, still report PR success to Overlord |
| All review fails | Log error, PR still exists - human can review manually |

**Key Principle:** Review failures should never block PR creation. The PR is valuable even without automated review.

## Files to Modify

- `nebulus_swarm/minion/main.py` - Add `_review_pr()`, call after PR creation
- `nebulus_swarm/minion/github_client.py` - Add `post_pr_comment()` if not exists
- `tests/test_minion_agent.py` - Add review integration tests

## Testing

1. Unit test: `_review_pr()` method with mocked ReviewWorkflow
2. Integration test: Create real PR, verify comment posted
3. Error test: Verify graceful degradation when review fails
