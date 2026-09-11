"""
The pronouns command: choose what you are called when somebody talks about you.

A sibling of `name`, and stored the same way: on the character, per world, so
a player can be one person in a haunted school and someone else aboard a
freighter. What differs is that a name is free text and a pronoun set is a
word from the world's register -- so this command both picks from that
register and, when nothing in it fits, adds to it.

`pronouns new` is the second half and the reason this is not four lines. A
world's register grows either because a model declared a set for a character
it invented or because a player said what theirs are, and both go through the
same `pronouns.register`. Neither is more entitled to the register than the
other.
"""

from commands.command import Command
from world import pronouns as pronoun_mod

#: The order the wizard asks in, and what to call each form for somebody who
#: has never had to name one. Deliberately by example rather than by grammar:
#: "possessive adjective" is correct and means nothing to most people, while
#: everybody can finish "___ sword".
ASKED = (
    ("subject", "___ picks up the sword", "she"),
    ("object", "you hand ___ the sword", "her"),
    ("adjective", "___ sword", "her"),
    ("possessive", "the sword is ___", "hers"),
    ("reflexive", "she cut ___", "herself"),
)


class CmdPronouns(Command):
    """
    Choose the pronouns other people use about you.

    Usage:
      pronouns
      pronouns <set>
      pronouns new

    Each world keeps its own sets, and each world remembers you separately.
    |wpronouns|n on its own lists what this world has and says which is yours.

    |wpronouns new|n walks through adding a set this world does not have yet.
    It asks for five forms and whether the verb after it is singular or
    plural -- "she picks up" against "they pick up" -- and the set it makes is
    then available to everybody here, characters included.
    """

    key = "pronouns"
    aliases = ["pronoun"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        room = caller.location
        world_root = room.db.world_root if room else None

        if world_root is None:
            caller.msg("You are not in a world that keeps pronouns.")
            return

        wanted = self.args.strip().lower()

        if not wanted:
            self._listing(caller, world_root)
            return

        if wanted in ("new", "add", "another"):
            self._ask(caller, world_root)
            return

        slug = pronoun_mod.give(caller, wanted, world_root)
        if not slug:
            caller.msg(
                f"This world keeps no pronoun set called |w{wanted}|n. "
                f"Type |wpronouns|n to see what it has, or |wpronouns new|n "
                f"to add one."
            )
            return

        entry = pronoun_mod.get(world_root, slug)
        caller.msg(f"People here will call you |w{pronoun_mod.spelled(entry)}|n.")

    def _listing(self, caller, world_root):
        """What this world has, and which of them is yours."""
        mine = pronoun_mod.of(caller, world_root)
        lines = [f"You go by |w{pronoun_mod.spelled(mine)}|n here.", ""]
        for slug, entry in sorted(pronoun_mod.vocabulary(world_root).items()):
            mark = "|w*|n" if slug == mine["subject"] else " "
            lines.append(f" {mark} |w{slug}|n — {pronoun_mod.spelled(entry)}"
                         f" — {entry.get('means', '')}")
        lines.append("")
        lines.append("|wpronouns <set>|n to pick one, |wpronouns new|n to add "
                     "one this world does not have.")
        caller.msg("\n".join(lines))

    def _ask(self, caller, world_root):
        """
        Walk through a new set, one form at a time.

        Through Evennia's own menu rather than a hand-rolled prompt loop: this
        is the same "ask a question and wait" the roadmap wants for
        disambiguation and for a rule that offers a choice, and there is no
        reason for this command to invent a second way of doing it.
        """
        from evennia.utils.evmenu import EvMenu

        EvMenu(caller, "commands.pronoun_cmds",
               startnode="_form", cmd_on_exit=None,
               world_root=world_root, gathered={}, step=0)


# ---------------------------------------------------------------------------
# The wizard, as EvMenu nodes
# ---------------------------------------------------------------------------

def _form(caller, raw_string, **kwargs):
    """Ask for one form, or finish when every form has been given."""
    menu = caller.ndb._evmenu
    step = menu.step
    if step >= len(ASKED):
        return _number(caller, raw_string, **kwargs)

    field, example, like = ASKED[step]
    text = (f"|wA new pronoun set|n ({step + 1} of {len(ASKED) + 1})\n\n"
            f"Fill in the blank: |w{example}|n\n"
            f"For she/her that word is |w{like}|n.\n\n"
            f"Type the word, or |wq|n to give up.")
    return text, ({"key": "_default", "goto": _took},)


def _took(caller, raw_string, **kwargs):
    """Keep what was typed and move on."""
    menu = caller.ndb._evmenu
    word = "".join(ch for ch in raw_string.strip().lower() if ch.isalpha())
    if not word:
        caller.msg("That is not a word. Try again.")
        return "_form"
    menu.gathered[ASKED[menu.step][0]] = word
    menu.step += 1
    return "_form"


def _number(caller, raw_string, **kwargs):
    """
    The sixth question, and the one nobody thinks to ask.

    Without it every sentence about the character reads "they picks up the
    sword". Asked in words rather than as "singular or plural", because the
    grammatical term is exactly what somebody answering this will not know.
    """
    menu = caller.ndb._evmenu
    subject = menu.gathered.get("subject", "they")
    return (
        f"|wOne last thing|n ({len(ASKED) + 1} of {len(ASKED) + 1})\n\n"
        f"Which of these is right?\n\n"
        f"  1. {subject} |wpicks|n up the sword\n"
        f"  2. {subject} |wpick|n up the sword\n",
        (
            {"key": ("1", "picks", "singular"), "goto": (_finish,
                                                         {"plural": False})},
            {"key": ("2", "pick", "plural"), "goto": (_finish,
                                                      {"plural": True})},
        ),
    )


def _finish(caller, raw_string, **kwargs):
    """Register the set and give it to whoever asked for it."""
    menu = caller.ndb._evmenu
    world_root = menu.world_root
    declared = dict(menu.gathered)
    declared["plural"] = bool(kwargs.get("plural"))
    declared["means"] = (f"for somebody who goes by {declared.get('subject')} "
                         f"and {declared.get('object')}")

    slug = pronoun_mod.register(world_root, declared)
    if not slug:
        caller.msg("That set was not complete enough to keep. Nothing changed.")
        return None

    pronoun_mod.give(caller, slug, world_root)
    entry = pronoun_mod.get(world_root, slug)
    caller.msg(
        f"This world now keeps |w{pronoun_mod.spelled(entry)}|n, and you go "
        f"by it. Anybody here can use it, characters included."
    )
    return None
