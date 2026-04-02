from nebulus_swarm.overlord.return_parser import parse_return_block


def test_parse_none():
    assert parse_return_block("just some random output") is None


def test_parse_malformed_no_end():
    output = """
---NEBULUS-RETURN---
STATUS: complete
SUMMARY: done
"""
    assert parse_return_block(output) is None


def test_parse_valid():
    output = """
---NEBULUS-RETURN---
STATUS: complete
SUMMARY: all tests passed: 12/12
FILES_CREATED: src/new.py
FILES_MODIFIED: README.md, src/old.py
TESTS_PASSED: 12/12
TESTS_FAILED: 0
BLOCKERS: None
NEXT_ACTION: review
---END-NEBULUS-RETURN---
"""
    block = parse_return_block(output)
    assert block is not None
    assert block.status == "complete"
    assert block.summary == "all tests passed: 12/12"
    assert block.files_created == ["src/new.py"]
    assert block.files_modified == ["README.md", "src/old.py"]
    assert block.tests_passed == "12/12"
    assert block.tests_failed == "0"
    assert block.blockers == "None"
    assert block.next_action == "review"


def test_parse_blocked():
    output = """
---NEBULUS-RETURN---
STATUS: blocked
BLOCKERS: need api key
---END-NEBULUS-RETURN---
"""
    block = parse_return_block(output)
    assert block.status == "blocked"
    assert block.blockers == "need api key"


def test_parse_error():
    output = """
---NEBULUS-RETURN---
STATUS: error
SUMMARY: disk full
---END-NEBULUS-RETURN---
"""
    block = parse_return_block(output)
    assert block.status == "error"
    assert block.summary == "disk full"


def test_parse_empty_files():
    output = """
---NEBULUS-RETURN---
STATUS: complete
FILES_CREATED:
FILES_MODIFIED:
---END-NEBULUS-RETURN---
"""
    block = parse_return_block(output)
    assert block.files_created == []
    assert block.files_modified == []
