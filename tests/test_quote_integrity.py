"""Quote-integrity tests for the published dogfood export.

Two tests, deliberately split:

* ``test_export_structure`` runs anywhere (including CI): it checks that every
  exported quote either carries no bracketed marker, or declares
  ``redacted: true`` with a ``redactions`` array that matches the markers in the
  quote one for one, one entry per occurrence. The marker set is closed and
  every entry has exactly the keys ``marker``, ``kind`` and ``reason``, so a
  literal cannot be smuggled into the array. It needs nothing machine-local.
* ``test_local_byte_integrity`` needs ``eval/dogfood/session.db`` (the source
  database) and ``eval/dogfood/redaction_rules.local.json`` (the machine-local
  literal rules), both gitignored, so it skips with an explicit reason in a
  fresh clone or CI. Where both are present it proves that each stored quote is
  byte-equal to ``captures.content[span_start:span_end]`` and that the exported
  quote is exactly ``quote_export.redact(...)`` of that source quote.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval/dogfood/results.json"
SESSION_DB = ROOT / "eval/dogfood/session.db"
RULES_FILE = ROOT / "eval/dogfood/redaction_rules.local.json"
QUOTE_EXPORT = ROOT / "eval/dogfood/quote_export.py"

REDACTED_RECORDS = 26
REDACTED_FACTS = 22
REDACTION_ENTRIES = 33

_MISSING = [
    name
    for name, path in (("eval/dogfood/session.db", SESSION_DB), ("eval/dogfood/redaction_rules.local.json", RULES_FILE))
    if not path.exists()
]


def _quote_export():
    spec = importlib.util.spec_from_file_location("quote_export", QUOTE_EXPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _results() -> dict:
    with RESULTS.open(encoding="utf-8") as handle:
        return json.load(handle)


def _records(data: dict):
    for row in data["rows"]:
        for record in row.get("memory_citations", []):
            yield row["id"], record


def test_export_structure():
    module = _quote_export()
    marker_kinds = {marker: kind for kind, marker in module.MARKERS.items()}
    marker_re = module.MARKER_RE
    data = _results()

    redacted_records = 0
    redacted_facts = set()
    entries_total = 0

    for question_id, record in _records(data):
        quote = record["quote"]
        markers = marker_re.findall(quote)
        redacted = record["redacted"]
        entries = record["redactions"]
        where = f"{question_id}/fact {record['fact_id']}"

        assert isinstance(redacted, bool), where
        assert isinstance(entries, list), where

        unknown = [marker for marker in markers if marker not in marker_kinds]
        assert not unknown, f"{where}: marker outside the closed set: {unknown}"

        if not markers:
            assert redacted is False, f"{where}: quote has no marker but claims redacted"
            assert entries == [], f"{where}: unmarked quote carries redaction entries"
            continue

        assert redacted is True, f"{where}: quote has markers but redacted is not true"
        redacted_records += 1
        redacted_facts.add(record["fact_id"])
        entries_total += len(entries)

        for entry in entries:
            assert set(entry) == {"marker", "kind", "reason"}, f"{where}: entry keys {sorted(entry)}"
            assert entry["marker"] in marker_kinds, f"{where}: marker outside the closed set"
            assert entry["kind"] == marker_kinds[entry["marker"]], f"{where}: marker/kind mismatch"
            assert isinstance(entry["reason"], str) and entry["reason"].strip(), where
            assert "[" not in entry["reason"] and "]" not in entry["reason"], where

        assert collections.Counter(entry["marker"] for entry in entries) == collections.Counter(markers), (
            f"{where}: redaction entries are not one for one with the markers in the quote"
        )

    assert redacted_records == REDACTED_RECORDS
    assert len(redacted_facts) == REDACTED_FACTS
    assert entries_total == REDACTION_ENTRIES


@pytest.mark.skipif(
    bool(_MISSING),
    reason=(
        "gitignored machine-local inputs absent (fresh clone/CI): " + ", ".join(_MISSING)
        + "; the local byte-integrity check needs both the source database and the literal rules file"
    ),
)
def test_local_byte_integrity():
    module = _quote_export()
    rules = module.load_rules(RULES_FILE)
    data = _results()
    connection = sqlite3.connect(SESSION_DB)
    connection.row_factory = sqlite3.Row

    checked = 0
    redacted = 0
    entries = 0
    for question_id, record in _records(data):
        fact = connection.execute(
            "SELECT f.quote, f.span_start, f.span_end, c.content"
            " FROM facts f JOIN captures c ON c.id = f.capture_id"
            " WHERE f.id = ?",
            (record["fact_id"],),
        ).fetchone()
        assert fact is not None, f"{question_id}/fact {record['fact_id']} missing from session.db"

        span_text = fact["content"][fact["span_start"]:fact["span_end"]]
        assert fact["quote"] == span_text, f"{question_id}/fact {record['fact_id']}: quote is not byte-equal to its span"

        expected_quote, expected_entries = module.redact(fact["quote"], rules)
        assert record["quote"] == expected_quote, (
            f"{question_id}/fact {record['fact_id']}: exported quote is not redact(source quote)"
        )
        assert record["redactions"] == expected_entries, (
            f"{question_id}/fact {record['fact_id']}: exported redactions differ from redact(source quote)"
        )
        assert record["redacted"] is bool(expected_entries), question_id

        checked += 1
        if expected_entries:
            redacted += 1
            entries += len(expected_entries)

    connection.close()
    print(
        f"byte-integrity: {checked} citation records match their session.db spans;"
        f" {redacted} are redacted with {entries} entries"
    )
    assert checked == 311
    assert redacted == REDACTED_RECORDS
    assert entries == REDACTION_ENTRIES
