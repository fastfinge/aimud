"""
What something sounds like, in a form. docs/sound.md 6.1.

One submenu, shared by every form that edits something ambience can be set
on -- this room, its area, a thing, a person, a sort of thing, a condition --
so the six cannot drift apart. It edits the live list, through the writer in
`world/sound.py` for that sort of thing, rather than a draft: like the rest
of those forms, a change is made the moment it is chosen, and whoever is
standing there hears it at once.

`where(ctx)` answers `(read, write)` for the thing being edited: `read()`
gives its ambience as stored, and `write(entries)` keeps a new list and
answers with what was kept. None when there is nothing to edit.
"""

from world import menus


def _said(entry):
    from world import sound

    asset = sound.resolve(entry.get("sound"))
    name = asset.name if asset is not None else "a sound that is missing"
    extra = []
    if int(entry.get("volume", 100)) != 100:
        extra.append(f"at {entry.get('volume')}")
    pan = int(entry.get("pan") or 0)
    if pan:
        extra.append(f"{'right' if pan > 0 else 'left'} {abs(pan)}")
    return name + (f" ({', '.join(extra)})" if extra else "")


def _add(ctx):
    from world import sound

    where = ctx.data.get("ambience_where")
    if where is None:
        raise menus.Refuse("There is nothing here to give a sound to.")
    read, write = where
    chosen = sound.resolve(ctx.draft.get("sound"))
    if chosen is None:
        raise menus.Refuse("Say which sound.")
    entry = {"sound": chosen.hash,
             "volume": ctx.draft.get("volume", 100)
             if ctx.draft.get("volume") is not None else 100,
             "pan": ctx.draft.get("pan") or 0}
    kept = write(list(read()) + [entry])
    if not any(found.get("sound") == chosen.hash for found in kept):
        raise menus.Refuse(f"{chosen.name} could not be kept.")
    return f"It now sounds like {_said(entry)}, among anything else."


def _new_form():
    from world import assets

    return menus.Form(
        key="new-ambience", title="A sound it keeps making", guided=True,
        intro="A sound that plays for as long as you are here, looping: "
              "wind, rain, a crowd, a fire. A sound made to loop works "
              "best. Anybody without sound reads its description instead.",
        items=[
            assets.picker("sound", "Which sound", "sound", required=True,
                          help="Any sound this server keeps. |wcreate "
                               "sound|n makes one."),
            menus.Field("volume", "How loud", kind=menus.NUMBER, minimum=0,
                        maximum=100,
                        help="0 to 100. The loudest sounds are the ones a "
                             "client with only a few channels plays."),
            menus.Field("pan", "From the left or the right",
                        kind=menus.NUMBER, minimum=-100, maximum=100,
                        help="-100 all the way left, 100 all the way right, "
                             "0 the centre: a sea to the east is heard on "
                             "the right."),
            menus.Action("keep", "Keep this sound", _add, after=menus.BACK),
        ],
    )


def _dropper(number):
    def drop(ctx):
        where = ctx.data.get("ambience_where")
        if where is None:
            return "There is nothing here to change."
        read, write = where
        entries = list(read())
        if not 0 <= number < len(entries):
            return "That one is already gone."
        gone = entries.pop(number)
        write(entries)
        return f"{_said(gone)} is taken out."

    return drop


def submenu(where, label="What it sounds like", help=""):
    """The submenu for a form: list, add and take out, live."""

    def items(ctx):
        found = [menus.Submenu("add", "Add a sound it keeps making",
                               _new_form(), fresh_draft=True,
                               help="One more sound, looping while anybody "
                                    "is here.")]
        current = ctx.data.get("ambience_where")
        entries = list(current[0]()) if current else []
        for number, entry in enumerate(entries):
            found.append(menus.Action(
                f"drop{number + 1}", f"Take out: {_said(entry)}",
                run=_dropper(number), help="Stops it making this sound."))
        return found

    def intro(ctx):
        current = ctx.data.get("ambience_where")
        entries = list(current[0]()) if current else []
        if not entries:
            return "|xSilent: nothing here says what it sounds like.|n"
        return "\n".join(f"  {number}. {_said(entry)}"
                         for number, entry in enumerate(entries, 1))

    def summary(ctx):
        current = where(ctx)
        entries = list(current[0]()) if current else []
        if not entries:
            return f"{label}: silent"
        return f"{label}: " + "; ".join(_said(entry) for entry in entries)

    form = menus.Form(key="ambience", title=label, intro=intro, items=items)
    return menus.Submenu(
        "ambience", summary, form,
        data=lambda ctx: {"ambience_where": where(ctx)},
        lock=lambda ctx: where(ctx) is not None,
        help=help or "Sounds it keeps making while anybody is near: heard "
                     "by a client that plays sounds, and read at the end of "
                     "look by everybody.")


# -- where, for each sort of thing -------------------------------------------

def of_object(get_obj):
    """A room, a thing or a person: its own attribute."""
    def where(ctx):
        from world import sound

        obj = get_obj(ctx)
        if obj is None:
            return None
        return (lambda: sound.own_ambience(obj),
                lambda entries: sound.set_ambience(obj, entries))

    return where


def of_zone(get_room):
    """The area the room you are in belongs to, if it belongs to one."""
    def where(ctx):
        from world import sound, zones

        room = get_room(ctx)
        root = getattr(getattr(room, "db", None), "world_root", None)
        zone_id = zones.slugify(getattr(getattr(room, "db", None), "zone", "")
                                or "")
        if root is None or not zone_id or zone_id not in (
                zones.all_zones(root) or {}):
            return None
        return (lambda: sound.zone_ambience(root, zone_id),
                lambda entries: sound.set_zone_ambience(root, zone_id,
                                                        entries))

    return where


def of_kind(root, kind):
    def where(ctx):
        from world import sound

        return (lambda: sound.kind_ambience(root, kind),
                lambda entries: sound.set_kind_ambience(root, kind, entries))

    return where


def of_condition(root, slug):
    def where(ctx):
        from world import sound

        return (lambda: sound.state_ambience(root, slug),
                lambda entries: sound.set_state_ambience(root, slug, entries))

    return where
