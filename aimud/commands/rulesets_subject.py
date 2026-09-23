"""
Rulesets, as a subject of the verbs: `view rulesets`, `edit rulesets`.

A ruleset is a bundle of rules a world is built with rather than born with --
crafting, clothing, death -- and the two things anybody wants to do with them
are read what this world has and change it. Both are verbs this game already
has, so neither is a command of its own. See `world/rulesets.py`.

The same form is opened from the world wizard, where it is the one place the
choice is naturally made: `create world` asks for a description and a title,
and this belongs beside them. One form, two doors, so what the menu offers
cannot drift between making a world and editing one.
"""

from commands.subjects import Subject, Use, require_world
from world import menus, rulesets


def _root(ctx):
    """The world being set up, or the one being stood in."""
    if ctx.draft and ctx.draft.get("world_id"):
        from evennia.objects.models import ObjectDB

        try:
            return ObjectDB.objects.get(id=ctx.draft["world_id"])
        except ObjectDB.DoesNotExist:
            return None
    where = getattr(ctx.character or ctx.caller, "location", None)
    return getattr(where.db, "world_root", None) if where else None


def _wanted(ctx):
    """
    Which rulesets are switched on in whatever is being edited.

    A draft when there is one -- the wizard has no world yet -- and the world
    itself otherwise. One reader, so the toggles below do not have to know
    which of the two they are looking at.
    """
    if ctx.draft is not None and "rulesets" in ctx.draft:
        return list(ctx.draft.get("rulesets") or [])
    root = _root(ctx)
    return rulesets.chosen(root) if root is not None else rulesets.defaults()


def _set_wanted(ctx, names):
    """Write the choice back, to the draft or to the world."""
    names = sorted(set(names))
    if ctx.draft is not None and "rulesets" in ctx.draft:
        ctx.draft["rulesets"] = names
        return ""
    root = _root(ctx)
    if root is None:
        return "You are not in a world."
    for name in rulesets.chosen(root):
        if name not in names:
            rulesets.forget(root, name)
    rulesets.seed(root, names)
    return ""


def _toggle(name):
    """One ruleset as a yes-or-no field."""
    doc = rulesets.get(name) or {}

    def get(ctx):
        return name in _wanted(ctx)

    def put(ctx, value):
        wanted = set(_wanted(ctx))
        if value:
            wanted.add(name)
        else:
            wanted.discard(name)
        return _set_wanted(ctx, wanted)

    needs = ", ".join(doc.get("requires") or [])
    help_text = doc.get("means") or ""
    if needs:
        help_text += f" Needs: {needs}, which is switched on with it."
    return menus.Field(
        name, doc.get("title") or name, kind=menus.BOOLEAN,
        get=get, set=put, help=help_text)


def _items(ctx):
    return [_toggle(name) for name in sorted(rulesets.available())]


def _intro(ctx):
    chosen = _wanted(ctx)
    said = ", ".join(chosen) or "none"
    return (f"A ruleset is a bundle of rules a world is built with. "
            f"On now: {said}. Switching one off suspends its rules rather "
            f"than deleting them, so anything built on top of them survives "
            f"and switching it back on puts them back.")


FORM = menus.Form(
    key="rulesets", title="Rulesets", intro=_intro, items=_items,
    context=lambda ctx: ("Each entry is a bundle of rules, kinds, states and "
                         "figures a world can be built with. What one "
                         "requires is switched on with it."),
)


# ---------------------------------------------------------------------------
# The verbs
# ---------------------------------------------------------------------------

def view_run(cmd, ctx, words):
    root = require_world(cmd.caller)
    if root is None:
        return
    lines = [f"|w{len(rulesets.chosen(root))} in use|n, of "
             f"{len(rulesets.available())} this server offers."]
    for name in sorted(rulesets.available()):
        mark = "|gon |n" if name in rulesets.chosen(root) else "|xoff|n"
        lines.append(f"  {mark}  {rulesets.said(name)}")
    cmd.caller.msg("\n".join(lines))


def view_items(ctx):
    return [menus.Submenu("rulesets", "The rulesets this world uses", FORM,
                          help="Which bundles of rules this world was built "
                               "with, and which this server offers.")]


def edit_run(cmd, ctx, words):
    if require_world(cmd.caller) is None:
        return
    menus.open_menu(cmd.caller, FORM, session=cmd.session)


def edit_items(ctx):
    return [menus.Submenu("rulesets", "Which rulesets this world uses", FORM,
                          help="Switch a bundle of rules on or off. What a "
                               "ruleset requires comes with it.")]


SUBJECTS = [
    Subject(
        "rulesets", ("rulesets", "ruleset"),
        uses={"view": Use(view_run, view_items),
              "edit": Use(edit_run, edit_items)},
        help="Bundles of rules a world is built with: crafting, death, and "
             "whatever else this server offers.",
    ),
]
