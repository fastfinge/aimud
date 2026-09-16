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
from world import menus
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

        Through the game's menu engine, as a guided form: each form is asked
        in turn, and once all six are in, the whole set is shown to be kept or
        corrected. See world.menus.
        """
        from world import menus

        menus.open_menu(caller, NEW_SET, session=self.session,
                        world_root=world_root)


# ---------------------------------------------------------------------------
# The wizard, as a form
# ---------------------------------------------------------------------------

def _word(ctx, text):
    """One pronoun form: letters only, as the register stores it."""
    word = "".join(ch for ch in text.strip().lower() if ch.isalpha())
    if not word:
        return None, "That is not a word. Try again."
    return word, ""


def _form_field(field, example, like):
    return menus.Field(
        field, example, prompt="Type the word that fills in the blank",
        help=f"For she/her that word is {like}.",
        parse=_word, required=True,
    )


def _number_choices(ctx):
    """
    The sixth question, and the one nobody thinks to ask.

    Without it every sentence about the character reads "they picks up the
    sword". Asked in words rather than as "singular or plural", because the
    grammatical term is exactly what somebody answering this will not know.
    """
    subject = ctx.draft.get("subject") or "they"
    return [
        menus.Choice(False, f"{subject} picks up the sword",
                     keys=("picks", "singular")),
        menus.Choice(True, f"{subject} pick up the sword",
                     keys=("pick", "plural")),
    ]


def _keep(ctx):
    """Register the set and give it to whoever asked for it."""
    world_root = ctx.world_root
    declared = {field: ctx.draft.get(field) for field, _example, _like in ASKED}
    declared["plural"] = bool(ctx.draft.get("plural"))
    declared["means"] = (f"for somebody who goes by {declared.get('subject')} "
                         f"and {declared.get('object')}")

    slug = pronoun_mod.register(world_root, declared)
    if not slug:
        return "That set was not complete enough to keep. Nothing changed."

    pronoun_mod.give(ctx.character, slug, world_root)
    entry = pronoun_mod.get(world_root, slug)
    return (f"This world now keeps |w{pronoun_mod.spelled(entry)}|n, and you "
            f"go by it. Anybody here can use it, characters included.")


NEW_SET = menus.Form(
    key="pronouns",
    title="A new pronoun set",
    intro="Change any form by its number, or keep the set.",
    guided=True,
    discard="Throw away this pronoun set?",
    items=[
        *(_form_field(field, example, like) for field, example, like in ASKED),
        menus.Field("plural", "The verb after it", kind=menus.CHOICE,
                    prompt="Which of these is right?",
                    choices=_number_choices, required=True,
                    show=lambda ctx, value: "not answered yet" if value is None
                    else _number_choices(ctx)[1 if value else 0].label),
        menus.Action("keep", "Keep this set", run=_keep, after=menus.CLOSE),
    ],
)


