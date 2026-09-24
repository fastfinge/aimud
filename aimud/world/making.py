"""
Everything a person can make, as one table.

`create world`, `create tokens` and `create pronouns` were each written out by
hand: a `Subject`, a `Use` per verb, a listing, a form, a deletion, a
confirmation. Eleven more things wanted making -- kinds, attributes,
conditions, actions, verb spellings, rules, items, rooms, ways out, people,
errands -- and writing forty-four more `Use` objects would not only be long,
it would put the answer to "what can be made here?" in fourteen places that
nothing can read at once.

Word lists and pronoun sets are here too, ported rather than left where they
were. Not for tidiness: a table only tested against the things it was shaped
around has not been tested. Carrying two it did not shape is what found the
three things it was missing (`opens`, `extras`, `owner`) and the three it had
quietly got wrong -- see docs/player-building.md, phase 1.

So a **maker** is a description of one creatable thing, and this is the table
of them. Five separate pieces of work read it, which is the whole reason it is
a table rather than fourteen modules each minding themselves:

* `commands/making_subject.py` turns each into a `Subject`, so `create kind`,
  `edit rule` and `delete item` arrive with their command lines, their menu
  entries and their permission checks already right;
* `menus.Picker` offers one register's contents inside another's form, with
  "none of these -- make one" opening the maker's own form;
* `preferences.confirmations` gives every maker that deletes or forgets
  something a setting to turn the asking off, because a list of those written
  by hand is one that is missing an entry the day somebody adds a maker;
* `export world` and `import world`, later, are this table serialised;
* a tool surface -- MCP, ACP -- wants exactly this list and nothing else.

**A maker owns no storage.** Every one of them writes through the function the
generators already call: `kinds.remember`, `traits.register`,
`verbs.register_state`, `actions.declare`, `rulebooks.add`, `effects.apply`.
That is what keeps a world somebody typed and a world a model wrote the same
world, and it is why this module is a table and not a layer.

**Registered by module**, as subjects are, and for the same reason: the forms
import the game, so they are read when first asked for rather than at import.
"""

from evennia.utils import logger

#: The modules that define makers, each with a `MAKERS` list. A plugin
#: appends its own.
MAKER_MODULES = [
    "world.makers.vocabulary",
    "world.makers.doing",
    "world.makers.rules",
    "world.makers.things",
    "world.makers.errands",
]

#: What a maker may answer to. Not every maker answers all four: a trait
#: cannot be deleted (see `Maker.remove`), and a room cannot be listed in a
#: menu of every room because the only one you may edit is the one you are in.
VERBS = ("create", "edit", "delete", "view", "reset")


class Maker:
    """
    One thing a person can make, and everything four readers need to know.

    `listing(root)` is the one function they all want: what this world holds,
    as `(id, one line)` or `(id, one line, help)`. Every register answers a
    different shape today -- `traits.vocabulary` a dict, `rulebooks.all_rules`
    a list of records, `verbs.groups` a merge of seeds and additions -- so the
    adapter lives here and the registers are left alone.

    `new` and `edit` are forms. `edit` is a function of the thing's id,
    because editing a rule and editing another rule are two different forms
    over two different records.

    `remove=None` means there is no deleting one, and it is an answer rather
    than a gap: a trait half this world's rules test cannot be removed without
    breaking them silently, and suspending a rule -- which exists -- is the
    honest alternative. See docs/player-building.md 3.1.

    `in_world` is whether this maker means anything outside a generated world.
    Everything here is a fact about a world, so it defaults to True.
    """

    def __init__(self, key, words, label, listing=None, one=None, new=None,
                 edit=None, remove=None, delete_question=None,
                 reset=None, reset_question=None,
                 help="", none="", make_label="", offered=None, sole=False,
                 reached=None, opens_with="", opens=None, extras=None,
                 owner=True):
        from world import menus

        self.key = str(key)
        self.words = tuple(str(word).lower() for word in words)
        # Refused here rather than found later. A maker's key becomes a menu
        # entry in `create`'s own list, and `menus.Item` raises on a reserved
        # name -- but only when that list is drawn, which is a crash in front
        # of a player rather than a failure at import. `exit` is the one that
        # caught this: a perfectly natural name for a way out of a room, and
        # the word that quits every menu in the game.
        for name in (self.key,) + self.words:
            if name in menus.RESERVED:
                raise ValueError(
                    f"{name!r} is a menu key in every menu and cannot name a "
                    f"maker; {key!r} needs another word.")
        self.label = label
        self.listing = listing
        self.one = one
        self.new = new
        self.edit = edit
        self.remove = remove
        self.delete_question = delete_question
        # `reset(root, id)` forgets what a world settled about something,
        # where `edit` may not. The deliberate exception to "first answer
        # stands", made out loud, as `reset verb` already made it: a separate,
        # named, confirmed gesture that says what it invalidates before it
        # does it. See docs/player-building.md 6.4.
        self.reset = reset
        self.reset_question = reset_question
        self.help = help
        # What a picker over this register calls its last entry, and what the
        # `create` menu calls this maker. Both are read where a player is
        # choosing, so both are sentences rather than nouns.
        self.none = none or f"None of these -- make a new {key}"
        self.make_label = make_label or label
        self.offered = offered
        # A maker of something there is only ever one of to edit: the room you
        # are standing in. `edit room` needs no list and takes no id.
        self.sole = sole
        # `reached(caller)` is what a maker of *objects* answers instead of a
        # listing: the things in front of somebody, never the world. An item
        # is chosen by reaching for it, which is why `listing` is empty for
        # these and why `edit item lamp` can never mean a lamp elsewhere.
        # See docs/player-building.md 5.
        self.reached = reached
        # Which field `create kind datapad` puts the rest of the line in.
        # Named rather than worked out from the form: half these forms build
        # their items from the context, so there is no list to look in, and
        # "the first required field" would be a different field the day one
        # is added above it.
        self.opens_with = str(opens_with or "")
        # `opens(said)` is the same question answered by a maker whose command
        # line is more than one word going into one field: `create tokens
        # smell: what it is for = brine | tar` fills three. `opens_with` is
        # the short way of writing the common case.
        self.opens = opens
        # More entries in the view menu than one per thing this world holds.
        # A word list's "try some text" is the case: it is about the register
        # rather than about any one entry in it.
        self.extras = extras
        # Whether making or changing one is for whoever made the world. True
        # for everything the world is built out of; false for a pronoun set,
        # which is a fact about the person choosing it rather than about the
        # world, and which anybody standing here may add and go by.
        self.owner = bool(owner)

    def opening_draft(self, said):
        """What was typed after `create <thing>`, as a draft."""
        said = str(said or "").strip()
        if not said:
            return {}
        if self.opens is not None:
            return dict(self.opens(said) or {})
        return {self.opens_with: said} if self.opens_with else {}

    def extra_items(self, ctx):
        """Whatever else belongs in this maker's view menu."""
        if self.extras is None:
            return []
        try:
            return list(self.extras(ctx) or [])
        except Exception:
            logger.log_trace(f"making: {self.key}'s extra entries failed")
            return []

    def confirmations(self):
        """
        The confirmation keys this maker uses, for `settings confirmations`.

        Generated rather than written out beside the hand-written ones, for
        the reason the whole table exists: a list of confirmations kept by
        hand would be missing one the day somebody adds a maker, and a
        confirmation nobody can turn off is one the registry does not know
        about rather than one the player has chosen.
        """
        found = []
        if self.remove is not None:
            found.append((f"delete_{self.key}", f"Deleting a {self.key}",
                          f"A deleted {self.key} is gone."))
        if self.reset is not None:
            found.append((f"reset_{self.key}",
                          f"Forgetting what a {self.key} was settled as",
                          f"The world decides afresh the next time it needs "
                          f"to."))
        return found

    def targets(self, caller):
        """The objects in reach this maker can act on, as `(id, label)`."""
        if self.reached is None:
            return []
        try:
            return [(str(obj.id), obj.key) for obj in self.reached(caller)]
        except Exception:
            logger.log_trace(f"making: {self.key} could not look around")
            return []

    def find(self, caller, phrase):
        """(the object `phrase` names in reach, a complaint)."""
        from commands.subjects import thing_here

        if self.reached is None:
            return None, ""
        candidates = self.reached(caller)
        if not candidates:
            return None, f"There is no {self.key} here to work on."
        found, complaint = thing_here(caller, phrase)
        if found is not None and found not in candidates:
            return None, f"{found.key} is not something you can do that to."
        return found, complaint

    # -- what a world holds ------------------------------------------------

    def entries(self, world_root):
        """What this world holds, as `(id, label, help)` triples."""
        if self.listing is None or world_root is None:
            return []
        found = []
        try:
            listed = self.listing(world_root) or []
        except Exception:
            logger.log_trace(f"making: {self.key} could not be listed")
            return []
        for entry in listed:
            if isinstance(entry, str):
                found.append((entry, entry, ""))
                continue
            value, label, helped = (tuple(entry) + ("", ""))[:3]
            found.append((value, str(label or value), str(helped or "")))
        return found

    def options(self, world_root):
        """The same, as a `menus.Picker` wants it."""
        return self.entries(world_root)

    def answers(self, verb):
        if verb == "create":
            return self.new is not None
        if verb == "edit":
            return self.edit is not None
        if verb == "delete":
            return self.remove is not None
        if verb == "view":
            return self.one is not None or self.listing is not None
        if verb == "reset":
            return self.reset is not None
        return False

    def is_offered(self, ctx):
        return self.offered is None or bool(self.offered(ctx))


_REGISTERED = None


def registered():
    """Every maker, in registration order."""
    global _REGISTERED
    if _REGISTERED is None:
        from importlib import import_module

        found = []
        for path in MAKER_MODULES:
            try:
                module = import_module(path)
            except Exception:
                # Loudly, and then on. One plugin with a typo in it must not
                # take the rest of the building commands down with it -- but a
                # maker that quietly is not there is the worst shape of bug
                # there is, because `create` simply does not offer the thing
                # and nothing anywhere says why.
                logger.log_trace(f"making: {path} could not be loaded, so "
                                 f"whatever it makes cannot be made")
                continue
            found.extend(getattr(module, "MAKERS", []))
        _REGISTERED = found
    return _REGISTERED


def forget():
    """Drop the cache, for a test that changes what is registered."""
    global _REGISTERED
    _REGISTERED = None


def get(key):
    """The maker called `key`, or None."""
    return next((m for m in registered() if m.key == key), None)


def for_verb(verb):
    return [maker for maker in registered() if maker.answers(verb)]


# ---------------------------------------------------------------------------
# Pickers over a register
# ---------------------------------------------------------------------------

def picker(key, label, maker, world=None, make=True, options=None, none=None,
           **kwargs):
    """
    A `menus.Picker` over one maker's register.

    `world(ctx)` finds the world root; it defaults to the room the caller is
    standing in, which is right everywhere this is used. `make=False` offers
    only what is there, for a picker inside the very form that makes one --
    a kind hanging beneath another kind must not offer to make a third from
    inside itself, because the draft it would answer is the one being filled.

    `options` and `none` override the maker's own, for a picker that lists
    something narrower than the whole register: the senses of one word, the
    conditions in one group.
    """
    from world import menus

    finder = world or root_of

    def listing(ctx):
        if options is not None:
            return options(ctx) if callable(options) else options
        found = get(maker)
        return found.options(finder(ctx)) if found else []

    def making(ctx):
        if make is False:
            return None
        if callable(make):
            return make(ctx)
        found = get(maker)
        return found.new if found else None

    def label_for_none(ctx):
        if none is not None:
            return none(ctx) if callable(none) else none
        found = get(maker)
        return found.none if found else "Make a new one"

    return menus.Picker(key, label, options=listing,
                        make=making, none=label_for_none, **kwargs)


def word_form(key, title, label, keep, help="", intro="", prompt=None):
    """
    A one-question form that answers a picker with whatever was typed.

    The "none of these -- type your own" a closed list sometimes wants: an
    affordance may be any verb, and refusing one because it is not in a list
    the game wrote would be the game deciding what a world may be about.
    `keep(ctx, text)` returns `(value, what to say)` or raises `menus.Refuse`.
    """
    from world import menus

    return menus.Form(
        key=key, title=title, guided=True, intro=intro,
        items=[
            menus.Field("text", label, required=True, prompt=prompt,
                        help=help),
            keeper("keep", "Use it",
                   lambda ctx: keep(ctx, str(ctx.draft.get("text") or ""))),
        ],
    )


def caller_of(ctx):
    return ctx.character or ctx.caller


def root_of(ctx):
    """The world the menu is being used in."""
    given = (ctx.data or {}).get("world_root")
    if given is not None:
        return given
    room = getattr(caller_of(ctx), "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Lists inside a form
# ---------------------------------------------------------------------------

def listing_field(key, label, add_form, describe, help="", add_label="",
                  empty="none yet", most=0):
    """
    One form item for a list kept in the draft: add one, or take one out.

    A rule's conditions and its effects are both this, and so are an NPC's
    traits and a kind's affordances. It is a `Submenu` whose form is built
    afresh every time it is drawn, because what it shows is what the draft
    holds now, and `add_form` answers with `menus.Picked` -- so one form
    serves both this and a picker.

    `describe(ctx, entry)` says one entry in a line.
    """
    from world import menus

    def entries_of(ctx):
        return list(ctx.draft.get(key) or [])

    def items(ctx):
        entries = entries_of(ctx)
        found = []
        if not most or len(entries) < most:
            found.append(menus.Submenu(
                "add", add_label or f"Add one",
                add_form(ctx) if callable(add_form) else add_form,
                into=key, append=True, fresh_draft=True,
                help="Adds one more to the list."))
        for number, entry in enumerate(entries):
            found.append(menus.Action(
                f"drop{number + 1}",
                f"Take out: {describe(ctx, entry)}",
                run=_dropper(key, number),
                help="Takes this one out of the list."))
        return found

    def intro(ctx):
        entries = entries_of(ctx)
        if not entries:
            return f"|x{empty}|n"
        return "\n".join(f"  {number}. {describe(ctx, entry)}"
                         for number, entry in enumerate(entries, 1))

    def summary(ctx):
        entries = entries_of(ctx)
        if not entries:
            return f"{label}: {empty}"
        if len(entries) == 1:
            return f"{label}: {describe(ctx, entries[0])}"
        return f"{label}: {len(entries)} of them"

    form = menus.Form(key=f"list-{key}", title=label, intro=intro, items=items)
    return menus.Submenu(key, summary, form, help=help)


def _dropper(key, number):
    def drop(ctx):
        entries = list(ctx.draft.get(key) or [])
        if not 0 <= number < len(entries):
            return "That one is already gone."
        entries.pop(number)
        ctx.draft[key] = entries
        ctx.dirty = True
        return "Taken out."

    return drop


def keeper(key, label, keep, command=None, **kwargs):
    """
    The action that finishes a maker's form, answering whoever opened it.

    `keep(ctx)` writes and returns `(value, what to say)`, or raises
    `menus.Refuse`. The value is what a picker was waiting for; with nobody
    waiting the menu simply says it and goes back, which is what `create kind`
    typed on its own should do.
    """
    from world import menus

    def run(ctx):
        value, said = keep(ctx)
        return menus.Picked(value, said)

    action = menus.Action(key, label, run=run, command=command, **kwargs)
    # Marked so that a command line giving everything can run it without
    # opening a menu at all -- "give all the arguments and there is no menu",
    # which is the rule every other command in the game already keeps.
    action.keeps = True
    return action


def finisher(form, ctx):
    """The action that finishes a form, or None."""
    for item in form.items_for(ctx):
        if getattr(item, "keeps", False):
            return item
    return None
