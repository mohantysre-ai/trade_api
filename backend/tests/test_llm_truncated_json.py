import json

from app.services.llm_client import _close_truncated_json


def test_close_truncated_json_dangling_backslash_is_valid():
    closed = _close_truncated_json('{"key": "value\\')
    parsed = json.loads(closed)
    assert parsed["key"] == "value\\"


def test_close_truncated_json_balanced_object():
    closed = _close_truncated_json('{"key": "value", "nested": {"a": 1')
    assert json.loads(closed) == {"key": "value", "nested": {"a": 1}}


def test_close_truncated_json_completed_backslash_then_quote():
    closed = _close_truncated_json('{"key": "value\\\\')
    parsed = json.loads(closed)
    assert parsed["key"] == "value\\"
