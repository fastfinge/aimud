"""
What a world says about itself.

A world has a short title, shown in listings, and a long description that is
put in front of every generator and every character in it. Keeping them apart
is what lets the description run to paragraphs without a world list becoming
unreadable.

It also has *guidance*: a separate note for each generator, given only to that
one. The description says what the world is, and everyone needs it; guidance
says what one generator in particular must do about it, and nobody else has
any use for. "Every character is a vampire" is wasted on the room writer and
crowds out what it did need to read, so it goes to the character generator
alone. That is what keeps the shared description short enough to be attended
to while each task still gets as much detail as it wants.

The description may contain <user>, which stands for whoever is playing. It is
substituted at the moment the text is used, not when it is written, so "<user>
is the rightful heir" is true of whoever walks in -- and true under whatever
name they gave themselves in this world. Guidance is substituted the same way.
"""

import re
from collections import namedtuple

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


#: One generator a world can be given instructions of its own.
#:
#: key    — how it is stored, and the name of the model function it feeds
#: label  — what the wizard calls it
#: hint   — one line in the wizard on what belongs here, with an example
#: header — the line the guidance is given under in the prompt itself
Facet = namedtuple("Facet", "key label hint header")

FACETS = (
    Facet(
        "rooms", "Rooms",
        "what the places are like: \"the world takes place entirely underground\"",
        "Instructions for the rooms of this world",
    ),
    Facet(
        "npcs", "Characters",
        "who is found here: \"every character is a vampire\"",
        "Instructions for the characters of this world",
    ),
    Facet(
        "items", "Items",
        "what is lying about: \"there are no firearms; everything is salvage\"",
        "Instructions for the items of this world",
    ),
    Facet(
        "dialogue", "Dialogue",
        "how characters speak and act: \"nobody says the emperor's name aloud\"",
        "Instructions for how the characters of this world speak and behave",
    ),
    Facet(
        "validation", "Rules",
        "what is possible here: \"this is a world of technology; magic does not exist\"",
        "The rules of this world — what is and is not possible in it",
    ),
)

FACETS_BY_KEY = {facet.key: facet for facet in FACETS}


def _root(obj):
    """The world root for a room, a world root, or None."""
    if obj is None or isinstance(obj, dict):
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


def raw_description(obj):
    """
    A world's description exactly as written, <user> and all.

    This is for whatever will store the text or resolve the token itself
    later. Anything about to put it in front of a model wants `description`.
    """
    root = _root(obj)
    return (root.db.world_description or "") if root else ""


def description(obj, viewer=None):
    """
    A world's full description, with {{user}} resolved for `viewer`.

    Everything that puts the world in front of a model goes through here, so
    a description written in the second person about the player reads
    correctly to a room generator, an NPC, and a verb rule alike.

    `obj` may also be a wizard spec, so that the first room of a world can be
    generated from one before the world exists to read it off.
    """
    if isinstance(obj, dict):
        text = obj.get("description") or ""
        return USER_TOKEN.sub(user_name(None, viewer), text) if text else ""
    root = _root(obj)
    if root is None:
        return ""
    text = root.db.world_description or ""
    if not text:
        return ""
    return USER_TOKEN.sub(user_name(root, viewer), text)


def _guidance_map(obj):
    """Every facet's guidance for a world, from a room, a root, or a spec."""
    if isinstance(obj, dict):
        return obj.get("guidance") or {}
    root = _root(obj)
    return (root.db.world_guidance or {}) if root else {}


def guidance(obj, facet, viewer=None):
    """
    What this world tells one generator, with {{user}} resolved, or "".

    `facet` is a key from FACETS. An unknown key simply has no guidance, so
    naming a facet a world was never set up with is harmless.
    """
    text = str(_guidance_map(obj).get(facet) or "").strip()
    if not text:
        return ""
    return USER_TOKEN.sub(user_name(_root(obj), viewer), text)


def guidance_block(obj, facet, viewer=None):
    """
    One facet's guidance as a labelled block, ready to drop into a prompt.

    Empty when the world says nothing about that facet, so a prompt may
    interpolate it unconditionally and gain no stray heading over nothing.
    """
    text = guidance(obj, facet, viewer)
    if not text:
        return ""
    known = FACETS_BY_KEY.get(facet)
    return f"{known.header if known else 'Instructions'}:\n{text}\n\n"


def clean_guidance(raw):
    """
    A guidance mapping holding only known facets, and only text worth sending.

    Blank entries are dropped rather than stored empty, so nothing downstream
    has to tell an unset facet from one set to whitespace.
    """
    cleaned = {}
    for facet in FACETS:
        text = str((raw or {}).get(facet.key) or "").strip()
        if text:
            cleaned[facet.key] = text
    return cleaned


def store(root, spec):
    """
    Write a world's title, description and guidance onto its root room.

    A field the spec does not mention is left alone, so a partial spec -- the
    bare description older callers pass -- changes only what it names. A field
    it does mention may be emptied, which is how `worldedit` takes a title or
    a piece of guidance away again. The description is the exception: it is
    what the whole world is generated from, and there is no world without it.
    """
    if root is None:
        return
    if "title" in spec:
        root.db.world_title = str(spec["title"] or "").strip()
    if spec.get("description"):
        root.db.world_description = str(spec["description"]).strip()
    if "guidance" in spec:
        root.db.world_guidance = clean_guidance(spec.get("guidance"))


def spec_of(root, character=None):
    """
    Everything a world was set up with, in the shape the wizard uses.

    This is what `worldedit` opens and what `worldreset` rebuilds from: a
    reset that forgot the guidance would quietly undo half the wizard.
    """
    if root is None:
        return {"title": "", "description": "", "player_name": "",
                "player_description": "", "guidance": {}}
    return {
        "title": root.db.world_title or "",
        "description": root.db.world_description or "",
        "player_name": (character.world_name(root) if character else "") or "",
        "player_description": (character.world_desc(root) if character else "") or "",
        "guidance": dict(root.db.world_guidance or {}),
    }


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
