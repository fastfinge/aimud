"""
The score command: what is measurably true of you.

Deliberately plain text rather than bars and meters. A trait is a number and
sometimes a word for that number, and both read aloud correctly; a row of
hashes does not.
"""

from commands.command import Command
from world import traits


def _row(label, value, width):
    """One trait line, with a dotted leader so the figures line up."""
    room_for_leader = width - len(f"  {label} ")
    dots = ". " * max(0, room_for_leader // 2)
    pad = " " * max(0, room_for_leader - len(dots))
    return f"  |w{label}|n {pad}{dots}{value}"


class CmdScore(Command):
    """
    Everything measurable about you.

    Usage:
      score
      score <trait>

    Shows each of your traits, what it currently stands at, and the word this
    world uses for standing there. Anything changing on its own -- a poison
    working through you, a skill coming back with rest -- says so.

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

        entries = traits.all_of(caller)
        if wanted:
            entries = [(slug, trait) for slug, trait in entries
                       if wanted in slug or wanted in (trait.name or "").lower()]
            if not entries:
                caller.msg(f"You have nothing called {wanted}.")
                return

        if not entries:
            caller.msg(
                "Nothing about you is measured yet. Traits appear as you do "
                "things the world thinks worth keeping count of."
            )
            return

        labels = [(trait.name or slug.replace("_", " ")) for slug, trait in entries]
        width = max(len(label) for label in labels) + 6

        lines = ["|wYour score|n\n"]
        for (slug, trait), label in zip(entries, labels):
            lines.append(_row(label, _value_text(trait), width))
            # Where the difference came from. A defence of nine that is four
            # breastplate reads as something you can take off; without this it
            # reads as something you were born with.
            from world import gear

            granted = gear.describe(caller, slug)
            if granted:
                lines.append(f"  |x  from {granted}|n")

        world_root = traits._world_root(caller)
        described = traits.vocabulary(world_root)
        unearned = [slug for slug in described
                    if slug not in {s for s, _ in entries}]
        if unearned and not wanted:
            lines.append(
                f"\n|xThis world also keeps track of: "
                f"{', '.join(sorted(unearned))}.|n"
            )
        caller.msg("\n".join(lines))


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
