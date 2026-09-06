"""
What a world says about itself.

A world has a short title, shown in listings, and a long description that is
put in front of every generator and every character in it. Keeping them apart
is what lets the description run to paragraphs without a world list becoming
unreadable.

The description may contain <user>, which stands for whoever is playing. It is
substituted at the moment the text is used, not when it is written, so "<user>
is the rightful heir" is true of whoever walks in -- and true under whatever
name they gave themselves in this world.
"""

import re

#: What the description calls the player.
#:
#: <user> is the spelling to recommend. {{user}} also works, because it is the
#: obvious thing to type and what the wizard first offered -- but Evennia
#: reserves "{{" as the escape for a literal brace, so the editor and every
#: other display eats one of them and shows "{user}}" while the stored text is
#: perfectly correct. That is alarming to look at, so anything that does not
#: collide with the markup is better.
USER_TOKEN = re.compile(
    r"\{\{\s*user\s*\}\}" r"|<\s*user\s*>" r"|\$user\b",
    re.IGNORECASE,
)

#: Stands in when nobody in particular is being addressed -- a room being
#: generated before anyone arrives, say.
ANONYMOUS = "the visitor"


def _root(obj):
    """The world root for a room, a world root, or None."""
    if obj is None:
        return None
    if obj.db.is_world_root:
        return obj
    return obj.db.world_root


def title(obj):
    """A world's short name, for listings."""
    root = _root(obj)
    if root is None:
        return "an unnamed world"
    stored = root.db.world_title
    if stored:
        return stored
    # Worlds made before titles existed have only their description.
    described = (root.db.world_description or "").strip()
    if described:
        first = described.splitlines()[0].strip()
        return first if len(first) <= 60 else first[:57].rstrip() + "..."
    return root.key


def user_name(world_root, viewer=None):
    """What {{user}} should say for this viewer."""
    if viewer is not None:
        naming = getattr(viewer, "world_name", None)
        if callable(naming):
            return naming(world_root) or viewer.key
        return viewer.key
    return ANONYMOUS


def description(obj, viewer=None):
    """
    A world's full description, with {{user}} resolved for `viewer`.

    Everything that puts the world in front of a model goes through here, so
    a description written in the second person about the player reads
    correctly to a room generator, an NPC, and a verb rule alike.
    """
    root = _root(obj)
    if root is None:
        return ""
    text = root.db.world_description or ""
    if not text:
        return ""
    return USER_TOKEN.sub(user_name(root, viewer), text)


def store(root, spec):
    """Write a world's title and description onto its root room."""
    if root is None:
        return
    if spec.get("title"):
        root.db.world_title = str(spec["title"]).strip()
    if spec.get("description"):
        root.db.world_description = str(spec["description"]).strip()


def apply_to_player(root, character, spec):
    """
    Give the player the name and appearance this world was set up with.

    Both are only defaults: a player may rename themselves afterwards, and
    the description is theirs to replace.
    """
    if root is None or character is None:
        return
    name = (spec.get("player_name") or "").strip()
    if name and not character.world_name(root):
        character.set_world_name(root, name)
    look = (spec.get("player_description") or "").strip()
    if look and not character.world_desc(root):
        character.set_world_desc(root, look)
