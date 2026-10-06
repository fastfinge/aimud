"""
Sounds, as a subject of the verbs. docs/sound.md 9.4.

  view sounds                  every sound this server keeps
  view sound <name>            hear it, and what it is
  create sound                 the ways to make one: genny, for now
  create sound genny           a form, built from genny's own catalog
  edit sound <name>            the same form, opened on how it was made

A sound is an asset, so it is kept, given up, adopted and deleted as one
(`commands/assets_subject.py`). What is here is what only a sound has:
hearing one, and making one.

**`create sound` is a menu of sources.** genny is the only one today;
Freesound, or a paid service, is another entry in `SOURCES` and touches
nothing else.

**The form is genny's catalog.** Which sound effects, instruments, drums and
effects there are, and every parameter each takes with its default and its
help, is read from genny when the form is drawn, so a newer genny adds what
it can do to this form without a line changed here.

**Assets never change**, so `edit sound` opens the form on the spec that made
the sound and saving it makes a new one. The old one stays until somebody
deletes it.
"""

import json

from commands.subjects import Subject, Use, account_of
from world import assets, menus


def _caller(ctx):
    return ctx.character or ctx.caller


def _account(ctx):
    return account_of(_caller(ctx))


def _has_account(ctx):
    return _account(ctx) is not None


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------

def detail(asset):
    """A sound, in words: what it is, how long, and how it was made."""
    from commands import assets_subject

    return assets_subject.detail(asset, None)


def _sound_named(said):
    return assets.named(said, type_="sound", status="present")


def view_run(cmd, ctx, words):
    from world import sound

    caller = cmd.caller
    said = " ".join(words).strip()
    if not said:
        found = list(assets.search("sound").exclude(origin="derived")[:200])
        if not found:
            caller.msg("There are no sounds yet. |wcreate sound|n makes "
                       "one.")
            return
        caller.msg("\n".join(f"|w{asset.name}|n -- {asset.description}"
                             for asset in found))
        return
    asset, why = _sound_named(said)
    if asset is None:
        caller.msg(why)
        return
    sound.heard(caller, asset, category=sound.UI, caption=False)
    caller.msg(detail(asset))


def view_items(ctx):
    return [menus.Submenu(
        "sounds", "Sounds this server keeps", menus.Form(
            key="sounds", title="Sounds", kind=menus.VIEW,
            intro=lambda ctx: "\n".join(
                f"|w{asset.name}|n -- {asset.description}"
                for asset in assets.search("sound").exclude(
                    origin="derived")[:200]) or "There are no sounds yet.",
            items=[]),
        help="Every sound, with what it sounds like. |wview sound <name>|n "
             "plays one.")]


# ---------------------------------------------------------------------------
# The genny form
# ---------------------------------------------------------------------------

#: How a sound can be made, and which catalog its "which" is chosen from.
HOW = [
    ("sfx", "A sound effect", "sfx"),
    ("instrument", "An instrument playing notes", "instruments"),
    ("drum", "A drum", "drums"),
    ("speech", "A voice saying something", "speech"),
    ("effects", "Effects on a sound this server keeps", None),
    ("spec", "A whole genny spec, written out", None),
]

#: What a parameter field's key is, in the draft.
PARAM = "p_"


def _catalog():
    from world import sound_gen

    return sound_gen.catalog() if sound_gen.available() else {}


def _how(ctx):
    return str(ctx.draft.get("how") or "")


def _register(ctx):
    return next((register for key, _label, register in HOW
                 if key == _how(ctx)), None)


def _which_options(ctx):
    register = _register(ctx)
    found = []
    for name, entry in sorted((_catalog().get(register) or {}).items()):
        extra = " ".join(str(entry.get(key)) for key in ("family", "range")
                         if entry.get(key))
        found.append((name, f"{name} -- {entry.get('desc', '')}"
                            + (f" ({extra})" if extra else "")))
    return found


def _params(ctx):
    """The catalog's parameters for what is chosen, or {}."""
    register = _register(ctx)
    if register == "speech":
        entry = (_catalog().get("speech") or {}).get("speech") or {}
    elif register:
        entry = (_catalog().get(register) or {}).get(
            str(ctx.draft.get("which") or "")) or {}
    else:
        entry = {}
    return entry.get("params") or {}


def _value(text):
    """A parameter as typed: a number when it is one."""
    said = str(text).strip()
    for kind in (int, float):
        try:
            return kind(said)
        except ValueError:
            continue
    if said.lower() in ("true", "yes", "on"):
        return True
    if said.lower() in ("false", "no", "off"):
        return False
    return said


def _effects(text):
    """`reverb:mix=0.3 lowpass:cutoff=2000` as genny's effect chain."""
    chain = []
    for token in str(text or "").split():
        name, _colon, rest = token.partition(":")
        effect = {"type": name}
        for pair in filter(None, rest.split(",")):
            key, _equals, value = pair.partition("=")
            if key:
                effect[key] = _value(value)
        chain.append(effect)
    return chain


def spec_of(draft):
    """The genny spec a draft of the form says, or raise Refuse."""
    how = str(draft.get("how") or "")
    params = {key[len(PARAM):]: _value(value)
              for key, value in draft.items()
              if key.startswith(PARAM) and value not in (None, "")}
    which = str(draft.get("which") or "")
    if how == "spec":
        try:
            spec = json.loads(str(draft.get("spec") or ""))
        except ValueError as exc:
            raise menus.Refuse(f"That spec is not JSON this can read: {exc}")
        if not isinstance(spec, dict):
            raise menus.Refuse("A spec is one JSON object.")
        return spec
    if how == "sfx":
        layer = {"type": "sfx", "kind": which, "params": params}
    elif how == "instrument":
        layer = {"type": "seq", "inst": which,
                 "steps": str(draft.get("notes") or "C4"), "params": params}
    elif how == "drum":
        layer = {"type": "drum", "kind": which, "params": params}
    elif how == "speech":
        layer = {"type": "speech", "text": str(draft.get("text") or ""),
                 "params": params}
    elif how == "effects":
        from world import sound

        source = sound.resolve(draft.get("source"))
        if source is None:
            raise menus.Refuse("Say which sound the effects are on.")
        layer = {"type": "file", "path": source.hash}
    else:
        raise menus.Refuse("Say how it is made.")
    if how in ("sfx", "instrument", "drum") and not which:
        raise menus.Refuse("Say which one.")
    spec = {"layers": [layer]}
    chain = _effects(draft.get("fx"))
    if chain:
        spec["fx"] = chain
    if draft.get("bpm"):
        spec["bpm"] = draft["bpm"]
    if draft.get("seconds"):
        spec["duration"] = draft["seconds"]
    if draft.get("loop"):
        spec["loop"] = True
    return spec


def _param_fields(ctx):
    found = []
    for name, info in sorted(_params(ctx).items()):
        found.append(menus.Field(
            PARAM + name, name.replace("_", " "),
            help=f"{info.get('help', '')} The default is "
                 f"{info.get('default')}. Leave it for the default."))
    return found


def _render(ctx, keep):
    """Render what the form says: to try it, or to keep it."""
    from world import sound, sound_gen

    caller = _caller(ctx)
    account = _account(ctx)
    spec = spec_of(ctx.draft)
    _checked, wrong = sound_gen.check(spec)
    if wrong:
        raise menus.Refuse("; ".join(wrong).capitalize() + ".")
    name = " ".join(str(ctx.draft.get("name") or "").split())
    description = str(ctx.draft.get("description") or "").strip()
    if keep and not (name and description):
        raise menus.Refuse("A sound needs a name, and a description: the "
                           "description is all anybody without sound, or a "
                           "model, ever has of it.")
    draft = ctx.draft

    def done(asset, said):
        if keep:
            if asset.charged_to_id == getattr(account, "id", None) and (
                    asset.name.startswith("(trying)")
                    or asset.description == TRYING):
                assets.edit(asset, name=name, description=description)
                said = f"|w{asset.name}|n is kept, as a sound."
            draft.pop("tried", None)
            caller.msg(said)
        else:
            draft["tried"] = asset.hash
            caller.msg(f"Here is how it sounds. |x({sound_gen_seconds(asset)})|n")
        sound.heard(caller, asset, category=sound.UI, caption=not keep)

    def failed(why):
        caller.msg(f"That sound could not be made: {why}.")

    caller.msg("Making it..." if keep else "Making it, to hear...")
    sound_gen.render(
        spec, name=name if keep else f"(trying) {name or 'a sound'}",
        description=description if keep and description else TRYING,
        added_by=account, charged_to=account, on_done=done, on_fail=failed)
    return None


#: What a sound made only to be tried is described as, until it is kept.
TRYING = "A sound being tried in the making, not kept yet."


def sound_gen_seconds(asset):
    seconds = (asset.made_with or {}).get("seconds")
    return f"{seconds} seconds" if seconds else "made"


def _forget_tried(ctx, why):
    """A sound tried and not kept is not kept."""
    tried = assets.find(ctx.draft.get("tried"))
    if tried is not None and tried.description == TRYING \
            and not assets.uses_of(tried):
        try:
            assets.delete(tried)
        except assets.Refused:
            pass


def _spec_sponsor(ctx):
    """
    Who pays for `~` on the spec: whoever pays here, where this world lets a
    model make sounds. docs/sound.md 9.5.
    """
    from world import sponsor as sponsor_mod

    try:
        found = sponsor_mod.of(_caller(ctx))
        return found if found is not None and found.will("sounds") else None
    except Exception:
        return None


def _spec_context(ctx):
    """What a model writing a spec is told: the format, and genny's names."""
    from world import manual

    found = _catalog()
    names = "; ".join(f"{section}: " + ", ".join(sorted(found.get(section)
                                                         or {}))
                      for section in ("sfx", "instruments", "drums", "fx"))
    return (manual.SOUND + "\nWhat genny has -- " + names
            + "\nWrite one spec, as JSON, for the sound the name and "
              "description say.")


def _how_locks(*keys):
    return lambda ctx: _how(ctx) in keys


def genny_form():
    from world import sound

    return menus.Form(
        key="new-sound-genny", title="A sound made with genny",
        guided=True, on_close=_forget_tried,
        sponsor=_spec_sponsor, context=_spec_context,
        intro="genny makes a sound from a description of it: instruments, "
              "drums, sound effects, a voice, and effects on any of them. "
              "Try it to hear it before you keep it. A whole spec can say "
              "anything genny can; |whelp sound|n says how.",
        items=lambda ctx: [
            menus.Field("name", "What it is called", required=True,
                        help="What players pick it by: rain on a tin roof."),
            menus.Field("description", "What it sounds like",
                        kind=menus.LONG_TEXT, required=True,
                        help="Said instead of the sound to anybody who "
                             "cannot hear it, and all a model knows of it."),
            menus.Field("how", "How it is made", kind=menus.CHOICE,
                        required=True,
                        choices=[menus.Choice(key, label)
                                 for key, label, _register in HOW]),
            menus.Picker("which", "Which one", options=_which_options,
                         lock=_how_locks("sfx", "instrument", "drum"),
                         help="From genny's own list, with what each is."),
            menus.Field("notes", "Notes", lock=_how_locks("instrument"),
                        help="C4 E4 G4:0.5 -- a note, a colon and how long; "
                             "[C4,E4,G4] for a chord; -:0.2 for a rest."),
            menus.Field("bpm", "Tempo", kind=menus.NUMBER, minimum=20,
                        maximum=300, lock=_how_locks("instrument"),
                        help="Beats a minute. With one, note lengths are in "
                             "beats rather than seconds."),
            menus.Field("text", "What it says", lock=_how_locks("speech"),
                        help="A few words: letters, numbers and short game "
                             "words come out clearest."),
            assets.picker("source", "Which sound", "sound",
                          lock=_how_locks("effects"),
                          help="The effects below are put on this one, and "
                               "the result is a new sound."),
            menus.Field("spec", "The spec", kind=menus.LONG_TEXT,
                        lock=_how_locks("spec"), suggestible=True,
                        help="One genny spec, as JSON: layers, effects, "
                             "length. |whelp sound|n says what may be in "
                             "one. A file layer names a sound by its id."),
            *_param_fields(ctx),
            menus.Field("fx", "Effects",
                        lock=_how_locks("sfx", "instrument", "drum",
                                        "speech", "effects"),
                        help="Space-separated, each name:setting=value,...: "
                             "reverb:mix=0.3 lowpass:cutoff=2000. The ones "
                             "there are: " + ", ".join(sorted(
                                 _catalog().get("fx") or {}))),
            menus.Field("seconds", "How long", kind=menus.NUMBER,
                        minimum=0.05, maximum=60,
                        help="Seconds. Left out, as long as it rings."),
            menus.Field("loop", "Made to loop?", kind=menus.BOOLEAN,
                        help="Yes makes it loop with no seam, for a sound a "
                             "place keeps making: wind, rain, a crowd."),
            menus.Action("try", "Try it", lambda c: _render(c, keep=False),
                         help="Makes it and plays it to you. It is not kept "
                              "unless you keep it."),
            menus.Action("keep", "Keep it", lambda c: _render(c, keep=True),
                         after=menus.CLOSE, command="create sound genny"),
        ])


#: The ways a sound can be made: (key, label, form, help). Freesound, or a
#: paid service, is one more line here.
SOURCES = [
    ("genny", "Made by genny, here, for nothing", genny_form,
     "Instruments, drums, sound effects and a voice, with effects, made on "
     "this server and costing nothing but a moment."),
]


def _sources_form():
    return menus.Form(
        key="new-sound", title="A new sound",
        intro="Where it comes from. A file somebody has already is |wcreate "
              "asset|n, or the website's upload page.",
        items=lambda ctx: [
            menus.Submenu(key, label, form(), fresh_draft=True,
                          command=f"create sound {key}", help=help)
            for key, label, form, help in SOURCES])


def create_run(cmd, ctx, words):
    said = " ".join(words).strip().lower()
    for key, _label, form, _help in SOURCES:
        if said == key:
            menus.open_menu(cmd.caller, form(), session=cmd.session)
            return
    if said:
        cmd.caller.msg(f"There is no way to make a sound called {said}. "
                       f"There is: " + ", ".join(key for key, *_rest
                                                 in SOURCES) + ".")
        return
    menus.open_menu(cmd.caller, _sources_form(), session=cmd.session)


def create_items(ctx):
    if not _has_account(ctx):
        return []
    return [menus.Submenu("sound", "A sound", _sources_form(),
                          command="create sound",
                          help="Made here, by genny, for nothing.")]


# ---------------------------------------------------------------------------
# edit: the form, on how it was made
# ---------------------------------------------------------------------------

def draft_of(asset):
    """The form's draft for a sound genny made: its whole spec."""
    spec = dict((asset.made_with or {}).get("spec") or {})
    return {"name": f"{asset.name} (changed)",
            "description": asset.description, "how": "spec",
            "spec": json.dumps(spec, indent=1)}


def edit_run(cmd, ctx, words):
    said = " ".join(words).strip()
    if not said:
        cmd.caller.msg("Which sound? |wview sounds|n lists them.")
        return
    asset, why = _sound_named(said)
    if asset is None:
        cmd.caller.msg(why)
        return
    if not (asset.made_with or {}).get("spec"):
        cmd.caller.msg(f"{asset.name} was not made by genny, so there is no "
                       f"spec to change. |wedit asset {asset.hash[:8]}|n "
                       f"changes its name and description.")
        return
    menus.open_menu(cmd.caller, genny_form(), session=cmd.session,
                    draft=draft_of(asset))


def edit_items(ctx):
    return []


SUBJECTS = [
    Subject(
        "sounds", ("sounds", "sound"),
        uses={"view": Use(view_run, view_items, offered=_has_account),
              "create": Use(create_run, create_items, offered=_has_account),
              "edit": Use(edit_run, edit_items, offered=_has_account)},
        help="Sounds: hear one, or make one with genny.",
    ),
]
