"""
The measurement §7.1 deferred: would ConceptNet have proposed what a world settled?

The spec holds back the *paid* uses of the second lexicon -- affordance priors in
every item, npc and clothing prompt -- until a replay says they earn their tokens,
because prompt text is paid for every object for the life of every world. This is
that replay.

Three numbers decide it, and the spec names them:

    coverage   of the affordances a world actually granted a kind, what fraction
               would `ReceivesAction`, `UsedFor` and `CapableOf` have proposed?
    precision  of what the corpus proposes, what fraction did the world grant --
               as against refuse, or never mention at all?
    novelty    what fraction of the proposals say something the taxonomy does not
               already imply through `lexicon.implied_affordances`?

A low precision is not fatal on its own: a prior is a suggestion a generator may
disagree with. A low *novelty* is fatal, because a prior that only repeats the
floor is tokens spent on something already free.

The spec also writes down in advance what it expects, so that it can be wrong on
the record: **good on ordinary nouns -- bread, door, rope, paper -- and poor on
exactly the invented genre vocabulary that §7 is about**, because crowdsourced
commonsense has never heard of a datapad either. Which would mean it improves the
easy case and not the hard one.

Run it:  python tests/fixtures/conceptnet_replay.py
"""

import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
GAME_DIR = HERE.parent.parent

#: The three relations the spec names. `ReceivesAction` is the one whose
#: definition is this codebase's own sentence about affordances; the other two
#: are what a thing is for and what it can do, which a generator also asks.
RELATIONS = ("ReceivesAction", "UsedFor", "CapableOf")


def _setup():
    sys.path.insert(0, str(GAME_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.settings")
    import django

    django.setup()


def worlds():
    """Every exported world, as its registers."""
    found = []
    for path in sorted((HERE / "worlds").glob("world-*.json")):
        found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


def proposed_for(word):
    """
    The verbs the corpus would propose for a word, folded to real verbs.

    Its values are participles and phrases -- "eaten", "tying things" -- so each
    is reduced through `affordances.known_verb`, which is strict: a stem that is
    not really a verb is dropped rather than invented.
    """
    from world import affordances, commonsense

    found = set()
    for relation in RELATIONS:
        for said in commonsense.forward(word, relation, limit=24):
            head = str(said).split()[:1]
            if not head:
                continue
            # The first word only. Scanning deeper for anything that folds to a
            # verb was the first version of this and it measured the parser
            # rather than the corpus: "feed baby" yielded `fee`, "lower person"
            # yielded `unwield`, and a sword came back with `look`. These three
            # relations all lead with their verb -- "filled with fluids",
            # "storing liquids", "tying things" -- so the head is the answer and
            # anything else is noise inflating the denominator.
            verb = affordances.known_verb(head[0])
            if verb:
                found.add(verb)
    return found


def floor_for(kind):
    """What the taxonomy already implies, which a prior must beat to be worth it."""
    from world import affordances, lexicon

    found = set()
    for word in lexicon.implied_affordances(kind) or []:
        verb = affordances.known_verb(word)
        if verb:
            found.add(verb)
    return found


def _word_of(kind):
    from world import lexicon

    return lexicon.word_of(kind) or str(kind).split(".")[0]


def _invented(kind):
    """
    Whether this is a word the dictionary has never heard of.

    The distinction the spec's prediction turns on: a `datapad` is exactly what
    §7 is about, and exactly what a crowdsourced corpus is least likely to know.
    """
    from world import lexicon

    return not lexicon.known(_word_of(kind))


def measure():
    from world import commonsense

    if not commonsense.available():
        return None

    rows = []
    for record in worlds():
        for kind, spec in (record.get("kind_specs") or {}).items():
            granted, refused = set(), set()
            for verb, allowed in (spec.get("affordances") or {}).items():
                (granted if allowed else refused).add(str(verb))
            if not granted and not refused:
                continue
            proposals = proposed_for(_word_of(kind))
            rows.append({
                "world": record.get("label", "?"),
                "kind": kind,
                "invented": _invented(kind),
                "granted": granted,
                "refused": refused,
                "proposed": proposals,
                "floor": floor_for(kind),
            })
    return rows


def summarise(rows, only=None):
    """Coverage, precision and novelty over a selection of the rows."""
    chosen = [r for r in rows if only is None or r["invented"] == only]
    if not chosen:
        return None

    granted = sum(len(r["granted"]) for r in chosen)
    found = sum(len(r["granted"] & r["proposed"]) for r in chosen)
    proposed = sum(len(r["proposed"]) for r in chosen)
    agreed = sum(len(r["proposed"] & r["granted"]) for r in chosen)
    contradicted = sum(len(r["proposed"] & r["refused"]) for r in chosen)
    beyond_floor = sum(len(r["proposed"] - r["floor"]) for r in chosen)
    silent = sum(1 for r in chosen if not r["proposed"])

    return {
        "kinds": len(chosen),
        "silent": silent,
        "granted": granted,
        "proposed": proposed,
        "coverage": round(100.0 * found / granted, 1) if granted else 0.0,
        "precision": round(100.0 * agreed / proposed, 1) if proposed else 0.0,
        "contradicted": contradicted,
        "novelty": round(100.0 * beyond_floor / proposed, 1) if proposed else 0.0,
    }


def report(rows):
    lines = []

    def block(name, found):
        if not found:
            lines.append(f"{name}: nothing to measure")
            return
        lines.append(f"{name}")
        lines.append(f"  {found['kinds']} kinds, {found['silent']} of which the "
                     f"corpus says nothing about at all")
        lines.append(f"  {found['granted']} affordances granted, "
                     f"{found['proposed']} proposed")
        lines.append(f"  coverage  {found['coverage']}%  "
                     f"(of what a world granted, how much would have been "
                     f"offered)")
        lines.append(f"  precision {found['precision']}%  "
                     f"(of what is offered, how much a world granted)")
        lines.append(f"  novelty   {found['novelty']}%  "
                     f"(of what is offered, how much the taxonomy does not "
                     f"already imply)")
        lines.append(f"  {found['contradicted']} proposals a world had "
                     f"explicitly refused")

    block("Everything", summarise(rows))
    lines.append("")
    block("Ordinary words the dictionary knows", summarise(rows, only=False))
    lines.append("")
    block("Invented words it does not", summarise(rows, only=True))
    return "\n".join(lines)


def worst(rows, limit=10):
    """The kinds where the corpus contradicted a world most, for reading."""
    ranked = sorted(rows, key=lambda r: -len(r["proposed"] & r["refused"]))
    lines = []
    for row in ranked[:limit]:
        clash = row["proposed"] & row["refused"]
        if not clash:
            break
        lines.append(f"  {row['kind']}: world refused {', '.join(sorted(clash))}")
    return "\n".join(lines) or "  (none)"


def main():
    _setup()
    rows = measure()
    if rows is None:
        print("No second lexicon. `commonsense fetch` first.")
        return
    print(report(rows))
    print("\nWhere the corpus and a world disagreed outright:")
    print(worst(rows))


if __name__ == "__main__":
    main()
