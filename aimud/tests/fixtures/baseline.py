"""
Record what the corpus measures today, so that a change to it can be noticed.

These are **observations, not invariants**, and the difference decides how they
are asserted. 72% one-way states is a fact about seven worlds built by the
engine the rulebook change replaces; the entire point of the work is to move it.
So the numbers live here, in one file that expects to be rewritten, and the test
that reads them asserts a *direction* -- refusals must not rise, one-way states
must not rise -- rather than an equality that would fail on the day the design
starts helping.

An `assertEqual(one_way, 45)` scattered through a test module is the trap: it
goes red when things improve, and whoever sees it red will "fix" the test.

Run it from the game directory after re-exporting, or after a deliberate change
that is expected to move a number:

    python tests/fixtures/baseline.py
"""

import json
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
GAME_DIR = HERE.parent.parent

#: Which way each figure should travel as the work lands. `down` and `up` are
#: ratchets; `zero` is a target the plan commits to reaching (see phase 13).
DIRECTIONS = {
    "rules": "any",
    "accepted": "any",
    "refused": "down",
    "refused_needs_a_place": "zero",
    "contested": "any",
    "verbs": "any",
    "one_way": "down",
    "unsettable": "zero",
    "dead_vocabulary": "down",
    "inert": "down",
    "pairs": "down",
    "forked": "zero",
}


def measure():
    sys.path.insert(0, str(GAME_DIR))
    from tests.support import worlds
    from world import rulecheck

    per_world, totals = {}, {name: 0 for name in DIRECTIONS}
    for label, record in sorted(worlds().items()):
        findings = rulecheck.scan(rulecheck.of_record(record))
        counts = dict(findings["counts"])
        counts.update({
            "one_way": len(findings["one_way"]),
            "unsettable": len(findings["unsettable"]),
            "dead_vocabulary": len(findings["dead_vocabulary"]),
            "inert": len(findings["inert"]),
            "pairs": len(findings["pairs"]),
            "forked": len(findings["forked"]),
            "refused_needs_a_place": len(
                findings["refusals"][rulecheck.REFUSAL_KINDS[1]]),
        })
        per_world[label] = {name: counts.get(name, 0) for name in DIRECTIONS}
        for name in DIRECTIONS:
            totals[name] += counts.get(name, 0)
    return per_world, totals


def main():
    per_world, totals = measure()
    record = {
        "recorded": date.today().isoformat(),
        "engine": "verb_rules",
        "note": ("Observations, not invariants. See the module docstring: the "
                 "test asserts a direction of travel, not equality."),
        "directions": DIRECTIONS,
        "totals": totals,
        "per_world": per_world,
    }
    path = HERE / "baselines.json"
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(f"{path}\n")
    for name in DIRECTIONS:
        print(f"  {name:24} {totals[name]:5}   should go {DIRECTIONS[name]}")


if __name__ == "__main__":
    main()
