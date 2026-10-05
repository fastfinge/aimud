"""
The shared folder's old spellings: `view exports` and `delete export`.

The folder became the `world` asset type (docs/archived/assets.md 13): `export world`
keeps a world asset, `import world` builds from one, and what is kept is
listed and removed like any other asset. These two words still answer, and
say what is typed now, the way retired commands already do
(`commands/unknown_cmd.py`), so anybody who learned them is not left with
"there is no such thing".
"""

from commands.subjects import Subject, Use


def view_run(cmd, ctx, words):
    from commands import assets_subject

    cmd.caller.msg("World documents are assets now: |wview assets world|n.")
    assets_subject.view_run(cmd, ctx, ["world"])


def delete_run(cmd, ctx, words):
    said = " ".join(words) or "<name>"
    cmd.caller.msg(f"World documents are assets now: |wdelete asset {said}|n.")


SUBJECTS = [
    Subject(
        "exports", ("exports", "export"),
        uses={"view": Use(view_run, lambda ctx: []),
              "delete": Use(delete_run, lambda ctx: [])},
        help="The old shared folder: world documents are assets now, under "
             "view assets world.",
    ),
]
