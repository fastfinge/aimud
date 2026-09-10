"""
Take the registers out of the live database and write them down as fixtures.

Worlds are disposable and this is not. Every measurement in `docs/` was taken
from the seven worlds in the development database -- 326 rules, 307 kinds, the
state vocabularies -- and it is the only generated rule data that exists. A
`worldreset` ends it. So it is exported here, where tests can assert against
real generated data rather than against examples somebody made up, and where it
survives the reset that phase 13 of the plan is going to do on purpose.

Run it from the game directory, with the virtualenv's python:

    python tests/fixtures/export.py

It is idempotent and safe to re-run: each world is written to its own file,
named by position rather than by title, and anything already there is replaced.

**What is taken, and what is deliberately left.** Only the machine-readable
registers -- the rules, the kinds, the words a world invented. Not prose: no
room descriptions, no world description, no character names, no narrations. That
is partly size (the prose is most of a world and none of it is what a rule test
asserts on) and partly that the prose is the player's, while the registers are
the engine's. A world's title becomes its position, so what is committed says
nothing about what anybody was playing.
"""

import json
import os
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
GAME_DIR = HERE.parent.parent

#: The attributes that make up a world's registers. Everything a rule, a kind or
#: a condition is read out of, and nothing else.
REGISTERS = (
    "verb_rules",
    "kind_specs",
    "state_vocabulary",
    "state_groups",
    "trait_vocabulary",
    "rule_failures",
)


def _setup():
    sys.path.insert(0, str(GAME_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.settings")
    import django

    django.setup()
    import evennia

    evennia._init()


def _plain(value):
    """An Attribute's contents as plain JSON-able Python."""
    from evennia.utils.dbserialize import deserialize

    value = deserialize(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)          # a dbref or anything else: its name will do


def export():
    from evennia.objects.models import ObjectDB

    out = HERE / "worlds"
    out.mkdir(exist_ok=True)
    for stale in out.glob("world-*.json"):
        stale.unlink()

    roots = [obj for obj in ObjectDB.objects.all()
             if obj.attributes.has("is_world_root")]
    roots.sort(key=lambda obj: obj.id)

    written = []
    for position, root in enumerate(roots, 1):
        label = f"world-{position:02d}"
        record = {
            "label": label,
            "exported": date.today().isoformat(),
            "engine": "verb_rules",      # the shape this corpus was made by
            "rooms": sum(1 for o in ObjectDB.objects.all()
                         if o.attributes.has("world_root")
                         and o.db.world_root == root),
        }
        for name in REGISTERS:
            record[name] = _plain(getattr(root.db, name, None) or {})

        path = out / f"{label}.json"
        path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
        written.append((label, path, record))

    return written


def main():
    _setup()
    written = export()
    print(f"{len(written)} world(s) -> {HERE / 'worlds'}\n")
    total_rules = total_kinds = total_states = 0
    for label, path, record in written:
        rules = len(record["verb_rules"])
        kinds = len(record["kind_specs"])
        states = len(record["state_vocabulary"])
        total_rules += rules
        total_kinds += kinds
        total_states += states
        print(f"  {label}  rules={rules:4} kinds={kinds:4} states={states:3}"
              f"  rooms={record['rooms']:3}"
              f"  {path.stat().st_size / 1024:6.1f} KiB")
    print(f"\n  total     rules={total_rules:4} kinds={total_kinds:4} "
          f"states={total_states:3}")


if __name__ == "__main__":
    main()
