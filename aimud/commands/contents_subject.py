"""
What a world holds, as subjects: its areas, its people, its word lists and
its pronoun sets.

  view zones                           the areas of this world and how full
  create npc                           a character for this room
  view tokens [<list>]                 the word lists this world keeps
  view tokens try <text>               what some text comes to, here
  create tokens [<list>[: <means>] = <entry> | <entry>]
  delete tokens [<list>] [yes]
  create pronouns                      a pronoun set this world does not have

These were `zones`, `npcgen`, `tokens` and `pronouns new`. Anyone may read a
world's word lists; making and removing them, and adding people, are for
whoever made the world, because the world pays for its own people.
"""

from commands.subjects import (Subject, Use, answered, asking, in_world,
                               names_for, owns_here, require_owner,
                               require_world)
from world import lore, menus
from world import sponsor as sponsor_mod


def _caller(ctx):
    return ctx.character or ctx.caller


def _root(ctx):
    room = getattr(_caller(ctx), "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# view zones
# ---------------------------------------------------------------------------

def zones_report(caller, root):
    """
    Every area of the world, nested, with how full each is.

    An area that has reached its planned size takes no more rooms, and the
    next room built at its edge starts somewhere new instead.
    """
    from world import zones

    if not zones.all_zones(root):
        return "This world has no areas recorded yet."
    location = getattr(caller, "location", None)
    here = zones.slugify(location.db.zone) if location else ""
    lines = [f"|wAreas of {lore.title(root)}:|n", ""]

    def line(zone_id, level):
        record = zones.get(root, zone_id)
        filled, size = len(record["rooms"]), record["budget"]
        if not zones.placed(root, zone_id):
            state = "|xnot built yet|n"
        elif zones.finished(root, zone_id):
            state = "|yfinished|n"
        elif zones.full(root, zone_id):
            state = "|yfull; its parts are still growing|n"
        else:
            state = f"|g{size - filled} to go|n"
        indent = "  " + "    " * level
        mark = " |g[you are here]|n" if zone_id == here else ""
        out = [f"{indent}|w{record['name']}|n -- {filled}/{size} rooms, "
               f"{state}{mark}"]
        if record["purpose"]:
            out.append(f"{indent}    |x{record['purpose']}|n")
        if record.get("singleton_types"):
            out.append(f"{indent}    |xonly one of: "
                       f"{', '.join(record['singleton_types'])}|n")
        return "\n".join(out)

    def branch(zone_id, level):
        if zone_id != zones.ROOT:
            lines.append(line(zone_id, level))
        for child in sorted(zones.children_of(root, zone_id),
                            key=lambda z: zones.name_of(root, z)):
            branch(child, level + (0 if zone_id == zones.ROOT else 1))

    branch(zones.ROOT, 0)
    return "\n".join(lines)


def view_zones_run(cmd, ctx, words):
    root = require_world(cmd.caller)
    if root is not None:
        cmd.caller.msg(zones_report(cmd.caller, root))


# ---------------------------------------------------------------------------
# create npc
# ---------------------------------------------------------------------------

def make_npc(caller):
    """
    Generate a character for the room the caller is in. Returns what to say.

    The world pays for its own people -- the same sponsor every character's
    own turns are paid by.
    """
    room = caller.location
    if not room or not room.db.is_ai_room:
        return "You can only generate characters in generated rooms."
    for obj in room.contents:
        if obj.db.is_npc:
            return f"There is already a character here ({obj.key})."
    if room.ndb.generating_npc:
        return "A character is already being generated for this room."

    payer = sponsor_mod.of(caller)
    try:
        payer.key()
    except ValueError as err:
        return str(err)

    room.ndb.generating_npc = True
    caller.msg("Generating a character for this room...")

    def on_success(npc):
        room.ndb.generating_npc = False
        room.msg_contents(f"|g{npc.key} has arrived.|n", exclude=None)

    def on_error(err):
        room.ndb.generating_npc = False
        caller.msg(f"|rCharacter generation failed: {err}|n")

    from world import busy
    from world.npc_gen import generate_npc

    wait = busy.start(caller, "generating a character for this room")
    generate_npc(sponsor=payer, room=room,
                 on_success=busy.closing(wait, on_success),
                 on_error=busy.closing(wait, on_error))
    return None


def create_npc_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "add people to it"):
        return
    said = make_npc(caller)
    if said:
        caller.msg(said)


def create_npc_items(ctx):
    return [menus.Action("npc", "A character for this room",
                         run=lambda ctx: make_npc(_caller(ctx)),
                         after=menus.CLOSE, aliases=("character",),
                         help="Generates a character who belongs in this room "
                              "and this world. A room holds one.",
                         command=lambda ctx: "create npc")]


# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

def tokens_listing(root):
    from world import token_lists

    kept = token_lists.vocabulary(root)
    if not kept:
        return "This world keeps no word lists yet. |wcreate tokens|n makes one."
    lines = ["Word lists this world keeps:", ""]
    for name, entry in sorted(kept.items()):
        lines.append(f"  |w{{{name}}}|n -- {token_lists.spelled(entry)} -- "
                     f"{entry.get('means', '')}")
    return "\n".join(lines)


def token_list(root, name):
    from world import token_lists

    entry = token_lists.get(root, name)
    if entry is None:
        return f"This world keeps no list called |w{name}|n."
    lines = [f"|w{{{name.lower()}}}|n -- {entry.get('means', '')}",
             f"Kept: {entry.get('scope')}"
             + (f", as a condition in the group |w{entry['group']}|n"
                if entry.get("group") else ""), ""]
    for item in entry["entries"]:
        weight = item.get("weight", 1)
        sets = (item.get("sets") or {}).get("states") or []
        lines.append(f"  {item['text']}"
                     + (f"  (weight {weight:g})" if weight != 1 else "")
                     + (f"  sets {', '.join(sets)}" if sets else ""))
    return "\n".join(lines)


def try_text(caller, root, text):
    from world import tokens

    if not text.strip():
        return "Try what? |wview tokens try It smells of {smell}.|n"
    shown = tokens.text(text, tokens.Context(viewer=caller, world_root=root,
                                             purpose="display"))
    return f"That comes to: {shown}"


def _list_names(root):
    from world import token_lists

    return sorted(token_lists.vocabulary(root))


TRY_TOKENS = menus.Form(
    key="try-tokens", title="Try some text",
    items=[menus.Field(
        "text", "Text to try",
        get=lambda ctx: None,
        set=lambda ctx, value: try_text(_caller(ctx), _root(ctx), value or ""),
        prompt="Type some text with a list in braces, like It smells of {smell}",
        help="Shows what a piece of text comes to for you, here, with each "
             "list in braces replaced by one of its entries.")],
)

VIEW_TOKENS = menus.Form(
    key="tokens", title="Word lists", kind=menus.VIEW,
    intro=lambda ctx: tokens_listing(_root(ctx)),
    items=lambda ctx: [
        menus.Submenu("try", "Try some text", TRY_TOKENS,
                      command=lambda ctx: "view tokens try <text>")
    ] + [
        menus.Action(f"list-{name}", name,
                     run=lambda ctx, name=name: token_list(_root(ctx), name),
                     aliases=names_for(name),
                     command=lambda ctx, name=name: f"view tokens {name}")
        for name in _list_names(_root(ctx))],
    choices_line="Choose:",
)


def view_tokens_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None:
        return
    if not words:
        menus.open_menu(caller, VIEW_TOKENS, session=cmd.session)
        return
    if words[0].lower() == "try":
        caller.msg(try_text(caller, root, " ".join(words[1:])))
        return
    caller.msg(token_list(root, " ".join(words)))


def add_list(root, name, means, entries):
    from world import token_lists

    name = name.strip().lower()
    if not name or not entries:
        return ("A word list needs a name and at least one entry: "
                "|wcreate tokens smell = brine | tar|n.")
    used = token_lists.register(root, name, {
        "means": means.strip() or f"a word list called {name}",
        "entries": entries,
    })
    if not used:
        return (f"|w{name}|n could not be kept. A list needs a name nothing "
                f"else here uses, and entries that finish.")
    if used != name:
        return (f"This world already keeps |w{used}|n, which is the same list. "
                f"Nothing changed.")
    return f"This world now keeps |w{{{used}}}|n."


def _split_entries(text):
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


def _keep_list(ctx):
    draft = ctx.draft
    said = add_list(_root(ctx), draft.get("name") or "", draft.get("means") or "",
                    _split_entries(draft.get("entries")))
    if not said.startswith("This world now keeps"):
        raise menus.Refuse(said)
    return said


NEW_TOKENS = menus.Form(
    key="new-tokens", title="A new word list",
    intro="A description that says {name} has one entry of the list chosen "
          "for it, and keeps that choice.",
    discard="Throw away this word list?",
    items=[
        menus.Field("name", "Name", required=True,
                    help="What descriptions write in braces: smell for {smell}."),
        menus.Field("means", "What it is for",
                    help="One line saying what the list is for, so the next "
                         "model to see it uses it the same way."),
        menus.Field("entries", "Entries", required=True,
                    prompt="Type the entries separated by a bar, like brine | "
                           "tar | fish",
                    help="The words or phrases the list chooses between."),
        menus.Action("keep", "Keep this list", run=_keep_list,
                     after=menus.CLOSE,
                     command=lambda ctx: "create tokens <list> = <entry> | "
                                         "<entry>"),
    ],
)


def create_tokens_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "change its word lists"):
        return
    rest = " ".join(words)
    if not rest:
        from commands.subjects import verb_form

        menus.open_menu(caller, verb_form("create"), session=cmd.session,
                        path=["tokens"])
        return
    left, sep, right = rest.partition("=")
    name, _, means = left.partition(":")
    if not sep:
        caller.msg("Give the entries after an equals sign: |wcreate tokens "
                   "smell = brine | tar|n.")
        return
    caller.msg(add_list(root, name, means, _split_entries(right)))


def remove_list(root, name):
    from world import token_lists

    removed, complaint = token_lists.unregister(root, name.strip())
    return f"|w{name.strip()}|n is gone." if removed else complaint


def _delete_list_question(name):
    return (f"Delete the word list {name}? Descriptions that use it lose it.")


DELETE_TOKENS = menus.Form(
    key="delete-tokens", title="Delete which word list?",
    intro=lambda ctx: "" if _list_names(_root(ctx))
    else "This world keeps no word lists.",
    items=lambda ctx: [
        menus.Action(f"list-{name}", name,
                     run=lambda ctx, name=name: remove_list(_root(ctx), name),
                     confirm="delete_tokens",
                     question=_delete_list_question(name), after=menus.CLOSE,
                     aliases=names_for(name),
                     command=lambda ctx, name=name: f"delete tokens {name}")
        for name in _list_names(_root(ctx))],
)


def delete_tokens_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "change its word lists"):
        return
    words, yes = answered(words)
    if not words:
        from commands.subjects import verb_form

        menus.open_menu(caller, verb_form("delete"), session=cmd.session,
                        path=["tokens"])
        return
    name = " ".join(words)
    asking(cmd, _delete_list_question(name), "delete_tokens",
           f"delete tokens {name}", lambda: caller.msg(remove_list(root, name)),
           already=yes)


# ---------------------------------------------------------------------------
# create pronouns
# ---------------------------------------------------------------------------

def _new_pronouns():
    from commands.pronoun_cmds import NEW_SET

    return NEW_SET


def create_pronouns_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None:
        return
    from commands.subjects import verb_form

    menus.open_menu(caller, verb_form("create"), session=cmd.session,
                    path=["pronouns"])


def create_pronouns_items(ctx):
    return [menus.Submenu(
        "pronouns", "A pronoun set this world does not have", _new_pronouns(),
        fresh_draft=True, data=lambda ctx: {"world_root": _root(ctx)},
        help="Walks through the five forms and the verb after them. The set "
             "is then there for everybody here, and you go by it.")]


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

SUBJECTS = [
    Subject(
        "zones", ("zones", "zone", "areas"),
        uses={"view": Use(view_zones_run, lambda ctx: [menus.Action(
            "zones", "The areas of this world",
            run=lambda ctx: zones_report(_caller(ctx), _root(ctx)),
            after=menus.CLOSE, command=lambda ctx: "view zones",
            help="Every area, what it holds, and how full it is.")],
            offered=in_world)},
        help="The areas of the world you are in, and how full each one is.",
    ),
    Subject(
        "npc", ("npc", "npcs", "character"),
        uses={"create": Use(create_npc_run, create_npc_items,
                            offered=owns_here)},
        help="A character generated for the room you are in.",
    ),
    Subject(
        "tokens", ("tokens", "token", "wordlists", "wordlist"),
        uses={
            "view": Use(view_tokens_run, lambda ctx: [menus.Submenu(
                "tokens", "Word lists", VIEW_TOKENS,
                help="The word lists this world keeps, and trying them out.")],
                offered=in_world),
            "create": Use(create_tokens_run, lambda ctx: [menus.Submenu(
                "tokens", "A word list", NEW_TOKENS, fresh_draft=True,
                help="A list of words a description chooses between.")],
                offered=owns_here),
            "delete": Use(delete_tokens_run, lambda ctx: [menus.Submenu(
                "tokens", "A word list", DELETE_TOKENS,
                help="Remove a word list this world keeps.")],
                offered=owns_here),
        },
        help="The word lists this world keeps.",
    ),
    Subject(
        "pronouns", ("pronouns", "pronoun"),
        uses={"create": Use(create_pronouns_run, create_pronouns_items,
                            offered=in_world)},
        help="A pronoun set this world does not have yet.",
    ),
]
