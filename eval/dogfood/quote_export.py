"""Export dogfood quotes for publication with bracketed redaction markers.

This module is the production redaction function used by
``eval/dogfood/results.json``. It replaces every machine-local literal that the
publication scrub removes (network address, filesystem path, model label, route
label, tool name, agent name) with a bracketed marker, and returns one
``{marker, kind, reason}`` entry per marker occurrence.

The marker set, the reasons and the redaction engine are public. The literal
values are not: they live in a machine-local, gitignored rules file beside the
source database (``eval/dogfood/redaction_rules.local.json``). Nothing in this
module spells a private value out, so a reader of the public tree cannot
recover a redacted literal from the source, and the publish guard never has to
allowlist one.

The rules file is JSON, with one entry per kind::

    {"rules": [{"kind": "address", "pattern": "<regex>"}, ...]}

``kind`` must be one of the keys of ``MARKERS``. A machine without the file can
still run the CI structural test in ``tests/test_quote_integrity.py``; the local
byte-integrity test and the export CLI skip or fail with an explicit reason.

Run ``python3 eval/dogfood/quote_export.py --help`` for the CLI.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "eval/dogfood/redaction_rules.local.json"

# Closed set of markers. Any bracketed token in an exported quote must be one
# of these; the CI test in tests/test_quote_integrity.py enforces that.
MARKERS = {
    "address": "[redacted address]",
    "path": "[redacted path]",
    "model label": "[redacted model label]",
    "route label": "[redacted route label]",
    "tool name": "[redacted tool name]",
    "agent name": "[redacted agent name]",
}

REASONS = {
    "address": "machine-local network address replaced with a bracketed marker",
    "path": "machine-local filesystem path replaced with a bracketed marker",
    "model label": "local model alias replaced with a bracketed marker",
    "route label": "local provider route alias replaced with a bracketed marker",
    "tool name": "external coding-agent harness name replaced with a bracketed marker",
    "agent name": "internal agent name replaced with a bracketed marker",
}

# Matches any bracketed token that claims to be a redaction marker, so the CI
# test can reject a marker outside the closed set. Ordinary square brackets in
# a quote (for example a package extra such as ``cairn[mcp]``) are not markers.
MARKER_RE = re.compile(r"\[redacted [^\[\]]*\]")

MISSING_RULES = (
    "{path} is machine-local and gitignored, and is absent (fresh clone/CI); "
    "create it beside session.db with one {{\"kind\", \"pattern\"}} entry per redaction kind"
)


def load_rules(path: pathlib.Path | None = None) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Load ``(kind, compiled pattern)`` rules from the machine-local JSON file.

    Raises ``FileNotFoundError`` when the file is absent and ``ValueError`` when
    a rule names a kind outside ``MARKERS`` or a pattern does not compile.
    """
    rules_path = pathlib.Path(path) if path is not None else RULES_PATH
    if not rules_path.exists():
        raise FileNotFoundError(MISSING_RULES.format(path=rules_path))
    with rules_path.open(encoding="utf-8") as handle:
        spec = json.load(handle)

    rules: list[tuple[str, re.Pattern[str]]] = []
    for item in spec["rules"]:
        kind = item["kind"]
        if kind not in MARKERS:
            raise ValueError(f"{rules_path}: unknown redaction kind {kind!r}")
        rules.append((kind, re.compile(item["pattern"])))
    missing = sorted(set(MARKERS) - {kind for kind, _ in rules})
    if missing:
        raise ValueError(f"{rules_path}: no rule for redaction kind(s) {missing}")
    return tuple(rules)


def redact(text: str, rules: tuple[tuple[str, re.Pattern[str]], ...] | None = None) -> tuple[str, list[dict[str, str]]]:
    """Return ``(redacted_text, entries)`` with one entry per marker occurrence.

    ``rules`` defaults to the machine-local rules file. Raises ``ValueError`` if
    two rules overlap, which would make the one-entry-per-occurrence contract
    ambiguous.
    """
    if rules is None:
        rules = load_rules()

    matches = []
    for kind, pattern in rules:
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), kind))
    matches.sort()

    out: list[str] = []
    entries: list[dict[str, str]] = []
    cursor = 0
    for start, end, kind in matches:
        if start < cursor:
            raise ValueError(f"overlapping redaction rules at offset {start}")
        out.append(text[cursor:start])
        out.append(MARKERS[kind])
        entries.append({"marker": MARKERS[kind], "kind": kind, "reason": REASONS[kind]})
        cursor = end
    out.append(text[cursor:])
    return "".join(out), entries


def _load_results(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def export(results_path: pathlib.Path, db_path: pathlib.Path, write: bool, rules_path: pathlib.Path | None = None) -> dict:
    """Re-derive every citation quote from the source database and redact it.

    The source quote must be byte-equal to ``captures.content[span_start:span_end]``;
    the exported quote is ``redact(source_quote)``. Records the scrub never
    touched come out byte-identical with an empty ``redactions`` array.
    """
    rules = load_rules(rules_path)
    data = _load_results(results_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    summary = {"records": 0, "redacted_records": 0, "redacted_facts": set(), "entries": 0, "rows": []}

    for row in data["rows"]:
        for record in row.get("memory_citations", []):
            summary["records"] += 1
            fact = connection.execute(
                "SELECT f.quote, f.span_start, f.span_end, c.content"
                " FROM facts f JOIN captures c ON c.id = f.capture_id"
                " WHERE f.id = ?",
                (record["fact_id"],),
            ).fetchone()
            if fact is None:
                raise SystemExit(f"fact {record['fact_id']} missing from {db_path}")
            span_text = fact["content"][fact["span_start"]:fact["span_end"]]
            if span_text != fact["quote"]:
                raise SystemExit(f"fact {record['fact_id']}: stored quote is not byte-equal to its span")
            quote, entries = redact(fact["quote"], rules)
            record["quote"] = quote
            record["redacted"] = bool(entries)
            record["redactions"] = entries
            if entries:
                summary["redacted_records"] += 1
                summary["redacted_facts"].add(record["fact_id"])
                summary["entries"] += len(entries)
                summary["rows"].append(
                    {
                        "question": row["id"],
                        "fact_id": record["fact_id"],
                        "span": record["span"],
                        "kinds": [entry["kind"] for entry in entries],
                    }
                )

    connection.close()
    summary["redacted_facts"] = sorted(summary["redacted_facts"])
    if write:
        with results_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
    return summary


def _table(rows: list[dict]) -> str:
    lines = [
        "| record | fact id | span | kinds |",
        "|---|---|---|---|",
    ]
    for item in rows:
        start, end = item["span"]
        kinds = ", ".join(item["kinds"])
        lines.append(f"| {item['question']} | {item['fact_id']} | {start}–{end} | {kinds} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=pathlib.Path, default=ROOT / "eval/dogfood/results.json")
    parser.add_argument("--db", type=pathlib.Path, default=ROOT / "eval/dogfood/session.db")
    parser.add_argument("--rules", type=pathlib.Path, default=RULES_PATH)
    parser.add_argument("--write", action="store_true", help="rewrite the results file in place")
    parser.add_argument("--table", action="store_true", help="print the 26-row markdown table")
    args = parser.parse_args(argv)

    try:
        summary = export(args.results, args.db, args.write, args.rules)
    except FileNotFoundError as error:
        print(f"quote-export: {error}", file=sys.stderr)
        return 2
    print(
        f"records={summary['records']} redacted_records={summary['redacted_records']}"
        f" redacted_facts={len(summary['redacted_facts'])} entries={summary['entries']}"
        f" written={args.write}"
    )
    if args.table:
        print()
        print(_table(summary["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
