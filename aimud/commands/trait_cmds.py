"""
The score command: what is measurably true of you.

Deliberately plain text rather than bars and meters. A trait is a number and
sometimes a word for that number, and both read aloud correctly; a row of
hashes does not.
"""

from commands.command import Command
from world import menus, traits


def _row(label, value):
    """
    One trait line: its name, then where it stands.

    A colon, not a dotted leader. The dots lined the figures up for somebody
    looking, and a screen reader reads every one of them out first.
    """
    return f"  |w{label}|n: {value}"


class CmdScore(Command):
    """
    Everything measurable about you.

    Usage:
      score
      score <trait>

    |wscore|n is the short way to type |wview score|n: everything after either
    works the same, so |wview score light|n and |wscore light|n are one trait
    either way.

    Shows each of your traits, what it currently stands at, and the word this
    world uses for standing there. Anything changing on its own -- a poison
    working through you, a skill coming back with rest -- says so. On its own
    it then offers each trait by number, for |wscore <trait>|n without typing
    the name.

    You gain traits by doing things. Nothing here is set at the start; a world
    invents what it needs as its rules are worked out, so two worlds will keep
    track of quite different things about you.
    """

    key = "score"
    aliases = ["traits", "sheet"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        wanted = self.args.strip().lower()
        if wanted:
            caller.msg(score(caller, wanted))
            return
        menus.open_menu(caller, SCORE, session=self.session)


def score(caller, wanted=""):
    """Every trait, or those matching `wanted`, as the score reads."""
    entries = traits.all_of(caller)
    if wanted:
        entries = [(slug, trait) for slug, trait in entries
                   if wanted in slug or wanted in (trait.name or "").lower()]
        if not entries:
            return f"You have nothing called {wanted}."

    if not entries:
        return ("Nothing about you is measured yet. Traits appear as you do "
                "things the world thinks worth keeping count of.")

    from world import gear

    lines = ["|wYour score|n", ""]
    for slug, trait in entries:
        label = trait.name or slug.replace("_", " ")
        lines.append(_row(label, _value_text(trait)))
        # Where the difference came from. A defence of nine that is four
        # breastplate reads as something you can take off; without this it
        # reads as something you were born with.
        granted = gear.describe(caller, slug)
        if granted:
            lines.append(f"  |x  from {granted}|n")

    world_root = traits._world_root(caller)
    described = traits.vocabulary(world_root)
    unearned = [slug for slug in described
                if slug not in {s for s, _ in entries}]
    if unearned and not wanted:
        lines.append(f"\n|xThis world also keeps track of: "
                     f"{', '.join(sorted(unearned))}.|n")
    return "\n".join(lines)


def _caller(ctx):
    return ctx.character or ctx.caller


def _trait_items(ctx):
    found = []
    for slug, trait in traits.all_of(_caller(ctx)):
        label = trait.name or slug.replace("_", " ")
        found.append(menus.Action(
            f"trait-{slug}", label,
            run=lambda ctx, slug=slug: score(_caller(ctx), slug),
            topic=slug,
            command=lambda ctx, slug=slug: f"score {slug}"))
    return found


def _score_form():
    return menus.Form(key="score", title="Your score", kind=menus.VIEW,
                      intro=lambda ctx: score(_caller(ctx)),
                      items=_trait_items, choices_line="One of them:")


def _value_text(trait):
    """A trait's standing, as a person would say it."""
    text = traits._round(trait.value)
    high = getattr(trait, "max", None)
    if high is not None:
        text += f"/{traits._round(high)}"

    worded = traits._worded(trait)
    if worded:
        text += f" |x({worded})|n"

    rate = getattr(trait, "rate", 0) or 0
    if rate:
        direction = "rising" if rate > 0 else "falling"
        text += f" |y— {direction} on its own|n"
    return text


SCORE = _score_form()
