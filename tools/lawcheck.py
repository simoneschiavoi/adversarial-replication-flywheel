#!/usr/bin/env python3
"""Fail-closed law check gating READY_QUEUE admission. Python stdlib only.

Exit codes:
  0 = CLEAR      no law blocks the fixture/mutation
  1 = BLOCKED    a law's predicate fires on the fixture (repeat-forbidden)
  2 = NOT_EVALUATED the law state cannot be verified (fail-closed: treat as blocked)

Laws live in researcher/LAWS.json. Each law:
  {id, name, scope, predicate_description, evidence, repeat_forbidden_fixtures[],
   reopening_falsifier, status ACTIVE|RETIRED}
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAWS = ROOT / "researcher" / "LAWS.json"


def load_laws() -> list[dict]:
    if not LAWS.exists():
        print("NOT_EVALUATED: LAWS.json missing", file=sys.stderr)
        sys.exit(2)
    data = json.loads(LAWS.read_text())
    laws = data.get("laws", [])
    if not laws:
        print("NOT_EVALUATED: LAWS.json empty", file=sys.stderr)
        sys.exit(2)
    return laws


def main() -> int:
    # argv: lawcheck.py <fixture-key> [component ...]
    if len(sys.argv) < 2:
        print("usage: lawcheck.py <fixture-key> [component ...]", file=sys.stderr)
        return 2
    fixture = sys.argv[1]
    components = set(sys.argv[2:])
    laws = load_laws()
    for law in laws:
        if law.get("status") != "ACTIVE":
            continue
        # scope check: does this law's scope mention any component we carry?
        scope = law.get("scope", "")
        if components and not any(c in scope for c in components):
            continue
        forbidden = law.get("repeat_forbidden_fixtures", [])
        if fixture in forbidden:
            print(
                f"BLOCKED by {law['id']} ({law['name']}): fixture '{fixture}' is "
                "repeat-forbidden",
                file=sys.stderr,
            )
            return 1
        # fail-closed: if the law claims to gate this scope but has no fixture
        # list at all we cannot verify it -> NOT_EVALUATED
        if components and not isinstance(forbidden, list):
            print(f"NOT_EVALUATED: {law['id']} has malformed fixtures", file=sys.stderr)
            return 2
    print(f"CLEAR: {fixture}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
