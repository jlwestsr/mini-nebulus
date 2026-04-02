"""Structured return block parser for worker outputs."""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReturnBlock:
    status: str
    summary: str
    files_created: list[str]
    files_modified: list[str]
    tests_passed: Optional[str] = None
    tests_failed: Optional[str] = None
    blockers: Optional[str] = "None"
    next_action: str = "review"


def parse_return_block(output: str) -> Optional[ReturnBlock]:
    pattern = r"---NEBULUS-RETURN---\s+(.*?)\s+---END-NEBULUS-RETURN---"
    match = re.search(pattern, output, re.S)
    if not match:
        return None
    block_text = match.group(1)
    fields = {}
    for line in block_text.splitlines():
        if ": " in line:
            key, val = line.split(": ", 1)
            fields[key.strip().upper()] = val.strip()
    try:
        return ReturnBlock(
            status=fields.get("STATUS", "needs_review").lower(),
            summary=fields.get("SUMMARY", "No summary provided"),
            files_created=[
                f.strip()
                for f in fields.get("FILES_CREATED", "").split(",")
                if f.strip()
            ],
            files_modified=[
                f.strip()
                for f in fields.get("FILES_MODIFIED", "").split(",")
                if f.strip()
            ],
            tests_passed=fields.get("TESTS_PASSED"),
            tests_failed=fields.get("TESTS_FAILED"),
            blockers=fields.get("BLOCKERS", "None"),
            next_action=fields.get("NEXT_ACTION", "review").lower(),
        )
    except Exception:
        logger.debug("Failed to parse return block", exc_info=True)
        return None
