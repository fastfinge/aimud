"""
Subjects: what the verb commands act on.

`create`, `edit`, `delete`, `reset`, `view`, `import`, `export` and `enter` are
eight commands and nothing else. What each of them can be done to -- a world,
a start room, and later rules, word lists, rooms, kinds -- is a subject, and a
subject says which verbs it answers and how. That split is what lets a plugin
or a building command add `create room` without touching `create`.

**A subject's words are the parser's business too.** Inside a generated world
a verb command only takes the input when it is typed on its own or when the
next word names one of its subjects: `reset world` is ours, `reset the trap`
is the world's. The words come from here and from nowhere else, so what a
command claims can never change because a world has learned something. See
`server/conf/cmdparser.py` and docs/commands-and-settings.md §2.

**Registered by module.** `SUBJECT_MODULES` names the modules that define
subjects, each with a `SUBJECTS` list. Read when first asked for rather than
imported at the top, because the subjects import the commands' own helpers.
"""

from world import menus

#: Every verb there is a command for, in the order `help` lists them.
VERBS = ("create", "edit", "delete", "reset", "view", "import", "export",
         "enter")

#: The modules that define subjects. A plugin appends its own.
SUBJECT_MODULES = [
    "commands.world_subject",
    "commands.rules_subject",
    "commands.contents_subject",
    "commands.upkeep_subject",
    "commands.settings_subject",
    "commands.score_subject",
    "commands.rulesets_subject",
    "commands.term_subject",
    # Every maker in world/making.py, as one subject each. Last, so a maker
    # can never take a word one of the hand-written subjects above already
    # answers to: `named` prefers the longest match, and registration order
    # settles a tie.
    "commands.making_subject",
]


class Use:
    """
    What one subject does for one verb.

    `run(cmd, ctx, words)` handles the command line: `words` is what came
    after the subject word, possibly nothing. `items(ctx)` is what the subject
    puts in the verb's own menu -- usually one submenu, sometimes several
    entries (`enter` lists every world). `offered(ctx)` hides it from the menu
    for somebody it means nothing to.
    """

    def __init__(self, run, items, offered=None):
        self.run = run
        self.items = items
        self.offered = offered

    def is_offered(self, ctx):
        return self.offered is None or bool(self.offered(ctx))


class Subject:
    """
    Something the verbs act on, and the words that name it.

    `words` may be a function of nothing, for a subject named by something that
    is not fixed in code -- the start room answers to its own name, which is
    the server admin's to change.
    """

    def __init__(self, key, words, uses, help=""):
        self.key = key
        self._words = words
        self.uses = dict(uses)
        self.help = help

    def words(self):
        found = self._words() if callable(self._words) else self._words
        return tuple(str(word).lower() for word in found if word)

    def answers(self, verb):
        return verb in self.uses


_REGISTERED = None


def registered():
    """Every subject, in registration order."""
    global _REGISTERED
    if _REGISTERED is None:
        from importlib import import_module

        found = []
        for path in SUBJECT_MODULES:
            found.extend(getattr(import_module(path), "SUBJECTS", []))
        _REGISTERED = found
    return _REGISTERED


def for_verb(verb):
    return [subject for subject in registered() if subject.answers(verb)]


def named(verb, args):
    """
    (subject, the rest of what was typed) when `args` starts with a subject
    this verb answers to, or (None, args).

    A subject word may be several words -- a start room called "Town Square" --
    so the longest name that fits wins.
    """
    said = " ".join(str(args or "").split())
    lowered = said.lower()
    best, best_word = None, ""
    for subject in for_verb(verb):
        for word in subject.words():
            if (lowered == word or lowered.startswith(word + " ")) \
                    and len(word) > len(best_word):
                best, best_word = subject, word
    if best is None:
        return None, said
    return best, said[len(best_word):].strip()


def claims(verb, args):
    """
    Whether the command for `verb` takes this input, inside a world.

    Typed alone it does, and it opens its menu. Followed by one of its
    subjects it does. Anything else is somebody doing something in the world.
    """
    if not str(args or "").strip():
        return True
    subject, _rest = named(verb, args)
    return subject is not None


def verb_form(verb):
    """The menu a verb opens when it is typed alone: what it can be done to."""

    def items(ctx):
        found = []
        for subject in for_verb(verb):
            use = subject.uses[verb]
            if use.is_offered(ctx):
                found.extend(use.items(ctx))
        return found

    def intro(ctx):
        return "" if items(ctx) else f"There is nothing you can {verb} here."

    return menus.Form(key=verb, title=f"{verb.capitalize()} what?",
                      intro=intro, items=items,
                      command=lambda ctx: verb)


# ---------------------------------------------------------------------------
# Helpers every subject wants
# ---------------------------------------------------------------------------

def names_for(*names):
    """Names an entry may answer to, less any that every menu already uses."""
    kept = []
    for name in names:
        name = str(name or "").strip().lower()
        if name and name not in menus.RESERVED and not name.isdigit() \
                and name not in kept:
            kept.append(name)
    return tuple(kept)


def owns(account, world_root):
    """Whether `account` may change what `world_root` is made of."""
    from evennia.accounts.accounts import DefaultAccount

    from world import sponsor

    if not isinstance(account, DefaultAccount) or world_root is None:
        return False
    return bool(account.is_superuser
                or sponsor.creator_of(world_root) == account)


def account_of(caller):
    """The account behind whoever typed, or None."""
    return menus.account_of(caller)


def world_here(caller):
    """The world the caller is standing in, or None."""
    room = getattr(caller, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


def in_world(ctx):
    """For `Use.offered`: only inside a world."""
    return world_here(ctx.character or ctx.caller) is not None


def owns_here(ctx):
    """For `Use.offered`: only inside a world this account made."""
    caller = ctx.character or ctx.caller
    return owns(account_of(caller), world_here(caller))


def is_builder(caller):
    """Whether the caller holds Builder or Admin, as the upkeep tools need."""
    try:
        return bool(caller.locks.check_lockstring(
            caller, "dummy:perm(Builder) or perm(Admin)"))
    except Exception:
        return False


def builder(ctx):
    """For `Use.offered`: only for a Builder or Admin."""
    return is_builder(ctx.character or ctx.caller)


def require_world(caller):
    """The world the caller is in, or None having told them they are not."""
    root = world_here(caller)
    if root is None:
        caller.msg("You are not in a generated world.")
    return root


def require_owner(caller, root, what="change it"):
    """Whether the caller may change `root`, telling them if not."""
    if owns(account_of(caller), root):
        return True
    caller.msg(f"Only whoever made this world can {what}.")
    return False


def require_builder(caller):
    if is_builder(caller):
        return True
    caller.msg("That is for builders.")
    return False


#: Typed on the end of a line to answer its yes/no in advance.
ANSWERS = ("yes", "confirm")


def answered(words):
    """(words without a trailing yes, whether there was one)."""
    if words and words[-1].lower() in ANSWERS:
        return list(words[:-1]), True
    return list(words), False


def asking(cmd, question, key, command, do, already=False):
    """
    Run `do` now, or once it has been confirmed.

    `already` is a trailing `yes` on the line. `command` is what to type with
    `yes` on the end, for somebody who cannot be shown a yes/no.
    """
    if already:
        return do()
    return menus.confirm(cmd.caller, question, do, key=key,
                         session=cmd.session, command=command)


def said(caller, text):
    """Send text if there is any: a helper for handlers that return prose."""
    if text:
        caller.msg(text)


# ---------------------------------------------------------------------------
# Finding what somebody meant, among what they can reach
# ---------------------------------------------------------------------------

def reachable(caller, people=None):
    """
    Everything the caller could be talking about: what is in reach, and no more.

    The one rule the building commands keep and the reason they keep it:
    `edit item lamp` in a world with forty lamps edits the one in front of you
    or asks which, and can never silently edit one on the other side of the
    map. There is no search of the world by name anywhere in building.

    Reach already follows containment and already stops at a closed lid, so
    "the coin in the chest" resolves and the coin in the shut box does not.
    """
    from world import relations

    try:
        found = [obj for obj in relations.reachable(caller) if obj is not caller]
    except Exception:
        location = getattr(caller, "location", None)
        found = [obj for obj in (getattr(location, "contents", None) or [])
                 if obj is not caller]
    if people is True:
        return [obj for obj in found if _is_person(obj)]
    if people is False:
        return [obj for obj in found
                if not _is_person(obj) and not _is_exit(obj)]
    return found


def _is_person(obj):
    from world import quests

    return quests.is_person(obj)


def _is_exit(obj):
    return bool(getattr(obj, "destination", None))


def thing_here(caller, phrase, people=None):
    """
    (what `phrase` names among what is in reach, a complaint).

    Matched by `naming.resemblance`, the same measure the parser uses, so a
    slip of the finger or of the ear reaches the right thing and a merely
    plausible match is offered back rather than guessed at. Nothing here
    conjures: building acts on what is already there.
    """
    from world import naming

    candidates = reachable(caller, people=people)
    if not candidates:
        return None, "There is nothing here to work on."
    phrase = str(phrase or "").strip()
    if not phrase:
        return None, ""
    found, score = naming.best_match(caller, phrase, candidates=candidates)
    if found is None:
        return None, (f"You see no {phrase} here. Building only reaches what "
                      f"is in front of you.")
    return found, ""
