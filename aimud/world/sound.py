"""
Playing a sound to somebody. docs/archived/sound.md 3.

One door. Everything that makes a noise -- a menu, a rule, the room you are
standing in -- calls `play` or `stop` here, with an asset and a category,
and nothing outside this module knows that MSP exists or what GMCP calls
anything.

**What a session speaks is decided per session**, because one player may be
connected from Mudlet and from a web browser at once:

* `Client.Media`, over GMCP, when the client lists it in `Core.Supports`
  (`server/conf/inputfuncs.py`). Everything: any number of sounds, loops
  by key, fades, preloading, captions.
* MSP, when a telnet client agreed to option 90
  (`server/conf/telnet_msp.py`). One-shot sounds on `!!SOUND`, and one loop
  at a time on `!!MUSIC`, which is all MSP has.
* Nothing, for anything else -- an MCP agent among them. What they get
  instead is the text every sound also is (docs/archived/sound.md 7).

A client that understands both is sent `Client.Media` only, never both, or
it would play everything twice.

**A sound is fetched from this server by URL**, so without `ASSET_BASE_URL`
nothing is sent: a client given a path it cannot reach plays nothing and
says nothing, which is worse than not being asked.

**Panning** is done by the game, because no MUD protocol can pan: the web
client is told the pan and pans for itself, and every other client is sent a
copy of the sound genny panned to the nearest of seven places
(`world/sound_gen.py`). The first time a copy is wanted it is made in the
background and the sound plays from the centre. docs/archived/sound.md 3.4.
"""

import contextlib
import contextvars

from django.conf import settings

#: What every sound is filed under. A player sets a volume for each, and
#: each is MSP's `T=` and Client.Media's `tag`. `music` is reserved: nothing
#: plays music yet.
UI, EVENT, AMBIENCE, MUSIC = "ui", "event", "ambience", "music"
CATEGORIES = (UI, EVENT, AMBIENCE, MUSIC)

#: What a session can be sent.
MSP, MEDIA = "msp", "media"

#: The player's choice of protocol: work it out, or insist.
AUTO, OFF = "auto", "off"
PROTOCOL_CHOICES = (AUTO, MSP, MEDIA, OFF)

#: Account attributes, read here and set through `world/preferences.py`.
ON_ATTR = "sound_on"
PROTOCOL_ATTR = "sound_protocol"
PAN_ATTR = "sound_pan"
VOLUME_ATTR = "sound_volume_%s"

#: The protocol flags the Portal sets.
MSP_FLAG = "MSP"
MEDIA_FLAG = "CLIENT_MEDIA"

#: Telnet, plain or over TLS: the only sessions MSP can be written to.
_TELNET = ("telnet", "telnet/ssl", "ssl")

#: What MSP calls the priority of every sound. One value for all: with MSP
#: a lower priority cannot interrupt a higher one, and nothing here outranks
#: anything else.
_PRIORITY = 50

#: Where a session remembers which loop MSP's one music channel is playing,
#: since MSP can only stop the music, never a sound by name.
_MSP_MUSIC = "sound_msp_music"


# ---------------------------------------------------------------------------
# Who is listening, and what they asked for
# ---------------------------------------------------------------------------

def account_of(listener):
    """The account whose settings a listener's sounds follow, or None."""
    from evennia.accounts.accounts import DefaultAccount

    if isinstance(listener, DefaultAccount):
        return listener
    return getattr(listener, "account", None)


def _setting(account, attr, default):
    if account is None:
        return default
    value = account.attributes.get(attr)
    return default if value is None else value


def sound_on(account):
    return bool(_setting(account, ON_ATTR, True))


def chosen_protocol(account):
    found = _setting(account, PROTOCOL_ATTR, AUTO)
    return found if found in PROTOCOL_CHOICES else AUTO


def volume_for(account, category):
    """0 to 100: how loud this player wants this category."""
    try:
        found = int(_setting(account, VOLUME_ATTR % category, 100))
    except (TypeError, ValueError):
        return 100
    return max(0, min(100, found))


def pans(account):
    return bool(_setting(account, PAN_ATTR, True))


def speaks(session, account=None):
    """What this session can be sent: MEDIA, MSP, or "" for nothing."""
    if session is None:
        return ""
    if account is None:
        account = getattr(session, "account", None)
    if not sound_on(account):
        return ""
    flags = getattr(session, "protocol_flags", None) or {}
    telnet = str(getattr(session, "protocol_key", "")) in _TELNET
    choice = chosen_protocol(account)
    if choice == OFF:
        return ""
    if choice == MEDIA:
        return MEDIA
    if choice == MSP:
        return MSP if telnet else ""
    if flags.get(MEDIA_FLAG):
        return MEDIA
    if flags.get(MSP_FLAG) and telnet:
        return MSP
    return ""


def _web(session):
    """Whether this is the web client, which pans a sound for itself."""
    return str(getattr(session, "protocol_key", "")).startswith("webclient")


def hears(listener):
    """Whether any session of this listener would be sent a sound."""
    account = account_of(listener)
    return any(speaks(session, account) for session in _sessions(listener))


def _sessions(listener):
    handler = getattr(listener, "sessions", None)
    if handler is None:
        return []
    try:
        return list(handler.all())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# What a client is given
# ---------------------------------------------------------------------------

def resolve(sound):
    """
    An asset from an asset, a hash, the start of one (the id a model is
    given, at least six characters and matching one asset only), or a
    built-in's `group/name`.
    """
    from world import assets

    if sound is None or hasattr(sound, "hash"):
        return sound
    said = str(sound).strip()
    if not said:
        return None
    if "/" in said:
        return assets.builtin(said)
    found = assets.find(said.lower())
    if found is None and len(said) >= 6:
        matches = list(assets.search(None, status=None).filter(
            hash__startswith=said.lower())[:2])
        found = matches[0] if len(matches) == 1 else None
    return found


def address(asset):
    """
    `(folder URL ending in /, file name)` for a client to fetch, or None.

    Both protocols take the two apart -- MSP's `U=` and Client.Media's `url`
    are the folder, and the name is said on its own -- so a client can keep
    one cache of everything it has fetched from here.
    """
    from world import assets

    if asset is None or asset.status != "present":
        return None
    url = assets.public_url(asset)
    if not url or "/" not in url:
        return None
    folder, name = url.rsplit("/", 1)
    return folder + "/", name


def configured():
    """Whether this server can send sounds at all."""
    return bool(str(getattr(settings, "ASSET_BASE_URL", "") or "").strip())


def _send(session, **kwargs):
    session.msg(**kwargs)


def _msp_line(command, name, folder, volume, loops, category, keep=False):
    parts = [name, f"V={volume}", f"L={loops}"]
    if keep:
        parts.append("C=1")
    else:
        parts.append(f"P={_PRIORITY}")
    parts += [f"T={category}", f"U={folder}"]
    return f"!!{command}(" + " ".join(parts) + ")"


def play(listener, sound, *, category, volume=100, pan=0, loop=False,
         key=None, fade=0, session=None):
    """
    Play a sound to every session of `listener` that can hear one.

    `listener` is a character or an account. `sound` is an asset, a hash or
    a built-in's `group/name`. `volume` is 0 to 100 before the player's own
    volume for `category`. `loop` keeps it going until `stop(key)`; `key`
    names a sound so that it can be stopped, and so that playing it again
    while it plays lets it carry on rather than start over. `fade` is in
    milliseconds. `session` plays it to that session alone: a menu is open
    in one window, not every window somebody has. Returns how many sessions
    it was sent to.
    """
    from world import assets

    asset = resolve(sound)
    where = address(asset)
    if where is None:
        return 0
    folder, name = where
    account = account_of(listener)
    if category not in CATEGORIES:
        category = EVENT
    loud = round(max(0, min(100, volume)) * volume_for(account, category)
                 / 100)
    if loud <= 0:
        return 0

    if not pans(account):
        pan = 0
    copies = {}

    def toward(session):
        """The asset and address this session is sent: panned, if it can be."""
        if not pan or _web(session):
            return asset, name, folder
        if "copy" not in copies:
            from world import sound_gen

            copies["copy"] = sound_gen.panned(asset, pan)
        found = copies["copy"]
        where_now = address(found) if found is not None else None
        if not where_now:
            return asset, name, folder
        return found, where_now[1], where_now[0]

    sent = 0
    for session in ([session] if session is not None
                    else _sessions(listener)):
        speaking = speaks(session, account)
        _heard_as, name_now, folder_now = (toward(session) if speaking
                                           else (asset, name, folder))
        if speaking == MEDIA:
            payload = {"name": name_now, "url": folder_now,
                       "type": "music" if category == MUSIC else "sound",
                       "tag": category, "volume": max(1, loud),
                       "loops": -1 if loop else 1,
                       "caption": str(asset.description or "")}
            if key:
                payload["key"] = str(key)
                payload["continue"] = True
            if fade:
                payload["fadein"] = int(fade)
            if pan and _web(session):
                # Ours: the web client pans for itself. No MUD client reads
                # it, and none is sent it.
                payload["pan"] = int(pan)
            _send(session, client_media_play=((), payload))
        elif speaking == MSP:
            if loop:
                line = _msp_line("MUSIC", name_now, folder_now, loud, -1,
                                 category, keep=True)
                setattr(session.ndb, _MSP_MUSIC, str(key or name))
            else:
                line = _msp_line("SOUND", name_now, folder_now, loud, 1,
                                 category)
            _send(session, msp=((line,), {}))
        else:
            continue
        sent += 1
    if sent:
        assets.touch(asset)
    return sent


def stop(listener, key, fade=0, session=None):
    """Stop the sound playing under `key`, where it can be stopped."""
    sent = 0
    account = account_of(listener)
    for session in ([session] if session is not None
                    else _sessions(listener)):
        speaking = speaks(session, account)
        if speaking == MEDIA:
            payload = {"key": str(key)}
            if fade:
                payload["fadeout"] = int(fade)
            _send(session, client_media_stop=((), payload))
        elif speaking == MSP:
            # MSP stops all music or all sounds and nothing in between, so
            # only the loop it is playing can be stopped by name.
            if getattr(session.ndb, _MSP_MUSIC, None) != str(key):
                continue
            setattr(session.ndb, _MSP_MUSIC, None)
            _send(session, msp=(("!!MUSIC(Off)",), {}))
        else:
            continue
        sent += 1
    return sent


def preload(session, sounds):
    """
    Ask a client to fetch these now, so the first time one is wanted it is
    not waiting on a download. Only Client.Media can be asked; MSP fetches
    a sound the first time it is played.
    """
    if speaks(session) != MEDIA:
        return 0
    sent = 0
    for sound in sounds:
        where = address(resolve(sound))
        if where is None:
            continue
        folder, name = where
        _send(session, client_media_load=((), {"name": name, "url": folder}))
        sent += 1
    return sent


#: The moments a menu or the parser makes a sound at, each with the account
#: attribute holding a player's own choice and the sound the game ships.
#: docs/archived/sound.md 8.
OPEN, CLOSE, SELECT, ERROR, HUH = "open", "close", "select", "error", "huh"
MOMENTS = {OPEN: "menu/open", CLOSE: "menu/close", SELECT: "menu/select",
           ERROR: "menu/error", HUH: "menu/huh"}
MOMENT_ATTR = "sound_moment_%s"

#: What a player's choice holds to mean "no sound at all here".
SILENT = "silent"


def ui_sound(account, moment):
    """
    What this player hears at this moment: an asset, a built-in's
    `group/name`, or None for silence.

    A player's own choice is kept as a hash, or as a built-in's name so that
    a built-in changing with the game carries the choice with it. A choice
    whose asset has since gone falls back to the game's.
    """
    chosen = _setting(account, MOMENT_ATTR % moment, None)
    if chosen == SILENT:
        return None
    if chosen:
        found = resolve(chosen)
        if found is not None and found.status == "present":
            return found
    return MOMENTS.get(moment)


def ui_sounds(account):
    """The sounds this player's menus make: theirs, or the game's."""
    return [found for found in (ui_sound(account, moment)
                                for moment in MOMENTS) if found]


def cue(listener, moment, session=None):
    """Play the sound for a menu or parser moment, as this player has it."""
    found = ui_sound(account_of(listener), moment)
    if found is None:
        return 0
    return play(listener, found, category=UI, session=session)


def _presenter_class():
    """
    What a menu sounds like: `menus.Presenter`, with a sound at each moment.
    Built when installed, so importing this module never imports the menu
    engine.
    """
    from world import menus

    class Presenter(menus.Presenter):
        def _cue(self, menu, moment):
            try:
                cue(menu.caller, moment,
                    session=getattr(menu, "_session", None))
            except Exception:
                # A sound is never worth a menu: whatever went wrong here,
                # the menu carries on without it.
                from evennia.utils import logger

                logger.log_trace("sound: a menu sound failed")

        def opened(self, menu):
            self._cue(menu, OPEN)

        def chose(self, menu, item):
            self._cue(menu, SELECT)

        def refused(self, menu, text):
            self._cue(menu, ERROR)

        def confirmed(self, menu, key, answer):
            self._cue(menu, SELECT if answer else CLOSE)

        def closed(self, menu, why):
            self._cue(menu, CLOSE)

    Presenter.__name__ = Presenter.__qualname__ = "SoundPresenter"
    return Presenter


def install():
    """Give every menu its sounds. Called once, at server start."""
    from world import menus

    menus.PRESENTER = _presenter_class()()
    return menus.PRESENTER


def at_login(account, session):
    """
    A session has logged in: fetch the menu sounds now, and tell an admin
    once if nobody can hear anything because the server has no address.
    """
    from world import assets

    if session is None:
        return
    if not configured():
        if (assets.is_admin(account) and getattr(session, "protocol_flags",
                                                  None)
                and (session.protocol_flags.get(MEDIA_FLAG)
                     or session.protocol_flags.get(MSP_FLAG))):
            session.msg("Your client can play sounds, but this server cannot "
                        "send any until ASSET_BASE_URL is set to its own "
                        "address, such as https://mud.example.com:4001, in "
                        "server/conf/settings.py.")
        return
    preload(session, ui_sounds(account))


# ---------------------------------------------------------------------------
# Who hears a sound, and who reads it. docs/archived/sound.md 3.4, 5, 7
# ---------------------------------------------------------------------------

#: Who a `play_sound` is for, said the way a rule listing says it. Anything
#: else is a role: whoever filled that part of what was typed.
ACTOR, OTHERS, EVERYONE = "actor", "others", "everyone"
HEARERS_SAID = {ACTOR: "whoever acted", OTHERS: "everyone else here",
                EVERYONE: "everyone here"}

#: Where a sound comes from, as a pan. The map is north-up, the way audio
#: games draw theirs: east is right, west left, north and south the centre.
PANS = {"east": 100, "west": -100, "northeast": 50, "southeast": 50,
        "northwest": -50, "southwest": -50}

#: A caption setting, per kind of sound: always, never, or only for a
#: connection that is not playing sounds.
ON, AUTO_CAPTIONS = "on", "auto"
CAPTION_CHOICES = (AUTO_CAPTIONS, ON, OFF)
CAPTIONS_ATTR = "sound_captions_%s"


def pan_toward(direction, room=None):
    """
    -100 to 100 for a direction, or for a way out of `room` that names one;
    0 for anything that names none.
    """
    from world.worldgen import canonical_direction

    said = str(direction or "").strip().lower()
    if not said:
        return 0
    found = canonical_direction(said)
    if found is None and room is not None:
        for way in getattr(room, "exits", []) or []:
            names = [str(way.key).lower()] + [str(alias).lower() for alias
                                              in way.aliases.all()]
            if said in names:
                for name in names:
                    found = canonical_direction(name) or next(
                        (canonical_direction(word) for word in name.split()
                         if canonical_direction(word)), None)
                    if found:
                        break
                break
    return PANS.get(found or "", 0)


def captions(account, session, kind):
    """Whether this session reads a caption for this kind of sound."""
    chosen = _setting(account, CAPTIONS_ATTR % kind, AUTO_CAPTIONS)
    if chosen == ON:
        return True
    if chosen == OFF:
        return False
    return not speaks(session, account)


def caption_of(asset):
    """A sound as a line of text: its description, in brackets."""
    said = " ".join(str(getattr(asset, "description", "") or "").split())
    return f"|x({said.rstrip('.')})|n" if said else ""


def heard(listener, sound, *, category, volume=100, pan=0, loop=False,
          key=None, fade=0, caption=True):
    """
    `play`, and the caption for each session that wants one instead.

    Per session, because one player may be in Mudlet and an agent at once:
    the window with speakers hears it, and the one without reads it. Only
    somebody with a session is ever given a caption, so an NPC's working
    memory never fills with brackets.
    """
    asset = resolve(sound)
    if asset is None or asset.status != "present":
        return 0
    account = account_of(listener)
    kind = AMBIENCE if category == AMBIENCE else EVENT
    sent = 0
    for session in _sessions(listener):
        sent += play(listener, asset, category=category, volume=volume,
                     pan=pan, loop=loop, key=key, fade=fade, session=session)
        if caption and captions(account, session, kind):
            line = caption_of(asset)
            if line:
                listener.msg(line, session=session)
    return sent


class _Gathering:
    """The sounds the effects being applied make, until they are heard."""

    def __init__(self, into):
        self.into = into


_gathering = contextvars.ContextVar("sound_gathering", default=None)


@contextlib.contextmanager
def gathering(sounds=None, actor=None, room=None, roles=None):
    """
    Collect what `play_sound` effects play while this is open.

    Given a list, the sounds wait in it for the event the caller delivers.
    Given none, they are heard when this closes -- unless a gathering is
    already open further out, which then has them: a tool call's own effects
    belong to the event of the verb that called it.
    """
    outer = _gathering.get()
    if sounds is None and outer is not None:
        yield outer.into
        return
    mine = [] if sounds is None else sounds
    token = _gathering.set(_Gathering(mine))
    try:
        yield mine
    finally:
        _gathering.reset(token)
    if sounds is None and mine:
        hear(mine)
        del mine[:]


def add_effect(effect, actor=None, room=None, roles=None):
    """A `play_sound` effect, kept for the event or heard now."""
    asset = resolve(effect.get("sound"))
    if asset is None:
        return None
    try:
        volume = int(effect.get("volume", 100))
    except (TypeError, ValueError):
        volume = 100
    if effect.get("direction"):
        pan = pan_toward(effect.get("direction"), room)
    else:
        try:
            pan = int(effect.get("pan") or 0)
        except (TypeError, ValueError):
            pan = 0
    found = {"asset": asset, "to": str(effect.get("to") or EVERYONE),
             "volume": max(0, min(100, volume)),
             "pan": max(-100, min(100, pan)),
             "actor": actor, "room": room, "roles": dict(roles or {})}
    open_now = _gathering.get()
    if open_now is not None:
        open_now.into.append(found)
    else:
        hear([found])
    return found


def _can_hear(obj):
    """Somebody, rather than something: a chair has a `msg` and no ears."""
    if _sessions(obj):
        return True
    from world.quests import is_person

    try:
        return bool(is_person(obj))
    except Exception:
        return False


def hearers(found):
    """Everybody a gathered sound is for."""
    actor, room, to = found.get("actor"), found.get("room"), found.get("to")
    present = [one for one in (getattr(room, "contents", None) or [])
               if _can_hear(one)]
    if to == ACTOR:
        return [actor] if actor is not None else []
    if to == OTHERS:
        return [one for one in present if one is not actor]
    if to == EVERYONE:
        if actor is not None and actor not in present:
            present.append(actor)
        return present
    named = (found.get("roles") or {}).get(to)
    return [named] if named is not None and hasattr(named, "msg") else []


def hear(sounds):
    """Play gathered sounds to whoever each is for. Each listener once."""
    for found in list(sounds or []):
        for listener in hearers(found):
            try:
                heard(listener, found["asset"], category=EVENT,
                      volume=found["volume"], pan=found["pan"])
            except Exception:
                from evennia.utils import logger

                logger.log_trace("sound: an event's sound failed")


# ---------------------------------------------------------------------------
# Which worlds use which sounds. docs/archived/sound.md 4.1
# ---------------------------------------------------------------------------

def world_roots():
    """Every world on the server."""
    from evennia.objects.models import ObjectDB

    return [root for root in ObjectDB.objects.get_by_attribute(
        key="is_world_root") if root.db.is_world_root]


def named_in(world_root):
    """
    {hash: what uses it} for every sound a world names: its rules'
    `play_sound`s, and the ambience of its rooms, zones, kinds, states and
    things.
    """
    from world import rulebooks

    found = {}
    if world_root is None:
        return found
    for rule in rulebooks.all_rules(world_root):
        for effect in rule.get("effects") or []:
            if hasattr(effect, "get") and effect.get("type") == "play_sound":
                asset = resolve(effect.get("sound"))
                if asset is not None:
                    found.setdefault(asset.hash, f"a rule, {rule.get('id')}")
    for hash_, said in ambience_named_in(world_root).items():
        found.setdefault(hash_, said)
    return found


def ambience_named_in(world_root):
    """{hash: what uses it} for a world's ambience, wherever it is said."""
    from evennia import search_tag

    from world import kinds, verbs

    found = {}

    def note(entries, said):
        for entry in _entries(entries):
            asset = resolve(entry.get("sound"))
            if asset is not None:
                found.setdefault(asset.hash, said)

    # The stored records, read as they are: `zones.all_zones` builds the
    # tree the first time it is asked, and a question asked while a world is
    # being exported must not change the world being exported.
    for zone_id, record in dict(getattr(world_root.db, "zones", None)
                                or {}).items():
        if hasattr(record, "get"):
            note(record.get(AMBIENCE_ATTR), f"the ambience of {zone_id}")
    for kind in (getattr(world_root.db, kinds.ATTR, None) or {}):
        note(kind_ambience(world_root, kind), f"the ambience of {kind}")
    for slug in verbs.vocabulary(world_root):
        note(state_ambience(world_root, slug), f"the ambience of {slug}")
    places = list(search_tag(str(world_root.id), category="ai_world"))
    if world_root not in places:
        places.append(world_root)
    for room in places:
        note(own_ambience(room), f"the ambience of {room.key}")
        for obj in room.contents:
            note(own_ambience(obj), f"the ambience of {obj.key}")
    return found


def used_in(world_root):
    """The sound assets a world uses, for its export to list."""
    from world import assets

    return [asset for asset in (assets.find(hash_)
                                for hash_ in named_in(world_root))
            if asset is not None]


def uses(asset):
    """What uses this sound, world by world: `{"said", "world"}` each."""
    from world import lore

    found = []
    for root in world_roots():
        said = named_in(root).get(asset.hash)
        if said:
            found.append({"said": f"{lore.title(root)}: {said}",
                          "world": root})
    return found


# ---------------------------------------------------------------------------
# Ambience: what a place, and what is in it, sounds like.
# docs/archived/sound.md 6
# ---------------------------------------------------------------------------
#
# Data, never rules. A room, a zone, a kind, a condition or one thing says
# what it sounds like as a list of `{sound, volume, pan}`, and this works out
# from them what somebody standing somewhere should hear. Nothing ticks:
# `refresh` is called by the doors a change already comes through -- a move,
# a condition changing, the ambience itself being written -- and sends each
# session only the difference.

#: The attribute a room, a thing or a person keeps its own ambience in, and
#: the key a zone's record, a kind's spec and a condition's entry keep it
#: under.
AMBIENCE_ATTR = "ambience"

#: The most loops anybody hears at once, loudest first.
MOST_LOOPS = 4

#: Milliseconds a loop fades over when it starts or stops.
CROSSFADE = 1000

#: Where a session remembers what it is hearing: {hash: (volume, pan)}, and
#: for MSP, which one loop.
_HEARING = "sound_ambience"


def clean_ambience(entries):
    """
    A list of `{sound, volume, pan}`, each naming a sound this server keeps
    by its hash. A built-in's `group/name` or the start of a hash is read
    and kept as the whole hash; anything naming nothing is dropped.
    """
    found = []
    for entry in entries or []:
        if not hasattr(entry, "get"):
            entry = {"sound": entry}
        asset = resolve(entry.get("sound"))
        if asset is None or asset.type != "sound":
            continue
        try:
            volume = max(0, min(100, int(entry.get("volume", 100))))
        except (TypeError, ValueError):
            volume = 100
        try:
            pan = max(-100, min(100, int(entry.get("pan") or 0)))
        except (TypeError, ValueError):
            pan = 0
        found.append({"sound": asset.hash, "volume": volume, "pan": pan})
    return found


def _entries(raw):
    """A stored ambience list, read without trusting it."""
    try:
        return [dict(entry) for entry in (raw or []) if hasattr(entry, "get")]
    except TypeError:
        return []


# -- what each sort of thing says ------------------------------------------

def own_ambience(obj):
    """What one room, thing or person itself sounds like."""
    return _entries(getattr(getattr(obj, "db", None), AMBIENCE_ATTR, None))


def zone_ambience(world_root, zone_id):
    from world import zones

    record = zones.get(world_root, zone_id) or {}
    return _entries(record.get(AMBIENCE_ATTR) if hasattr(record, "get")
                    else None)


def kind_ambience(world_root, kind):
    from world import kinds

    return _entries((kinds.spec(world_root, kind) or {}).get(AMBIENCE_ATTR))


def state_ambience(world_root, slug):
    from world import verbs

    entry = verbs.vocabulary(world_root).get(slug) or {}
    return _entries(entry.get(AMBIENCE_ATTR) if hasattr(entry, "get")
                    else None)


# -- writing it, through one door each -------------------------------------

def set_ambience(obj, entries):
    """What a room, a thing or a person sounds like. Returns what was kept."""
    kept = clean_ambience(entries)
    if kept:
        obj.attributes.add(AMBIENCE_ATTR, kept)
    else:
        obj.attributes.remove(AMBIENCE_ATTR)
    refresh_around(obj)
    return kept


def set_zone_ambience(world_root, zone_id, entries):
    from world import zones

    zone_id = zones.slugify(zone_id)
    every = zones.all_zones(world_root)
    if zone_id not in every:
        return []
    kept = clean_ambience(entries)
    record = dict(every[zone_id])
    if kept:
        record[AMBIENCE_ATTR] = kept
    else:
        record.pop(AMBIENCE_ATTR, None)
    every[zone_id] = record
    world_root.db.zones = every
    refresh_world(world_root)
    return kept


def set_kind_ambience(world_root, kind, entries):
    from world import kinds

    kind = kinds.canonical(kind)
    if not world_root or not kind:
        return []
    kept = clean_ambience(entries)
    store = dict(getattr(world_root.db, kinds.ATTR, None) or {})
    entry = dict(store.get(kind) or {})
    if kept:
        entry[AMBIENCE_ATTR] = kept
    else:
        entry.pop(AMBIENCE_ATTR, None)
    store[kind] = entry
    setattr(world_root.db, kinds.ATTR, store)
    refresh_world(world_root)
    return kept


def set_state_ambience(world_root, slug, entries):
    from world import verbs

    vocab = verbs.vocabulary(world_root)
    if not world_root or slug not in vocab:
        return []
    kept = clean_ambience(entries)
    entry = dict(vocab[slug] or {})
    if kept:
        entry[AMBIENCE_ATTR] = kept
    else:
        entry.pop(AMBIENCE_ATTR, None)
    vocab[slug] = entry
    world_root.db.state_vocabulary = vocab
    refresh_world(world_root)
    return kept


# -- working out what somebody hears ---------------------------------------

def _world_of(obj):
    try:
        return obj.db.world_root
    except AttributeError:
        return None


def _kinds_with_ambience(world_root, obj):
    """
    The ambience of the most specific kind of `obj` that has any. A kind's
    hyponyms share it: a pine forest sounds like a forest unless somebody
    said otherwise.
    """
    from world import kinds

    best, best_depth = [], -1
    for kind in kinds.of(obj):
        own = kind_ambience(world_root, kind)
        if own:
            return own
        for ancestor in kinds.ancestors(world_root, kind):
            found = kind_ambience(world_root, ancestor)
            if found:
                depth = len(kinds.ancestors(world_root, ancestor))
                if depth > best_depth:
                    best, best_depth = found, depth
    return best


def place_layer(room):
    """
    What the place itself sounds like: the room's own, or else its nearest
    zone's, or else its kind's. One answer, because a room that says what
    it sounds like means exactly that.
    """
    from world import zones

    if room is None:
        return []
    own = own_ambience(room)
    if own:
        return own
    world_root = _world_of(room)
    if world_root is None:
        return []
    zone_id = zones.slugify(getattr(room.db, "zone", "") or "")
    for each in zones.ancestry(world_root, zone_id) if zone_id else []:
        found = zone_ambience(world_root, each)
        if found:
            return found
    return _kinds_with_ambience(world_root, room)


def _conditions_of(world_root, obj):
    from world import verbs

    found = []
    for slug in sorted(verbs.states(obj) or ()):
        found += state_ambience(world_root, slug)
    return found


def thing_layer(obj, world_root):
    """What one thing sounds like: its own, its conditions', its kind's."""
    return (own_ambience(obj) + _conditions_of(world_root, obj)
            + _kinds_with_ambience(world_root, obj))


def things_layer(room, listener=None):
    """
    What everything here sounds like: the place's own conditions and its
    zones', what is in it, and what the listener carries. Not what is
    inside something else, which is muffled to nothing.
    """
    from world import zones

    world_root = _world_of(room)
    if room is None or world_root is None:
        return []
    found = _conditions_of(world_root, room)
    zone_id = zones.slugify(getattr(room.db, "zone", "") or "")
    for each in zones.ancestry(world_root, zone_id) if zone_id else []:
        for slug in sorted(zones.states(world_root, each)):
            found += state_ambience(world_root, slug)
    present = [obj for obj in room.contents
               if not getattr(obj, "destination", None)]
    if listener is not None:
        present += [obj for obj in listener.contents if obj not in present]
    for obj in present:
        found += thing_layer(obj, world_root)
    return found


def ambience_for(listener, room=None):
    """
    `(place, everything)`: what the listener's place sounds like, and every
    loop they hear -- one per sound, the loudest of each, at most
    `MOST_LOOPS`, loudest first. Each is `(asset, volume, pan)`.
    """
    if room is None:
        room = getattr(listener, "location", None)
    place = _merged(place_layer(room))
    every = _merged(place_layer(room) + things_layer(room, listener))
    return place, every[:MOST_LOOPS]


def _merged(entries):
    best = {}
    for entry in entries:
        asset = resolve(entry.get("sound"))
        if asset is None or asset.status != "present":
            continue
        volume, pan = int(entry.get("volume", 100)), int(entry.get("pan", 0))
        held = best.get(asset.hash)
        if held is None or volume > held[1]:
            best[asset.hash] = (asset, volume, pan)
    return sorted(best.values(), key=lambda found: (-found[1],
                                                    found[0].hash))


def described(loops):
    """The loops, as one sentence a reader can take in."""
    said = [" ".join(str(asset.description or "").split()).rstrip(".")
            for asset, _volume, _pan in loops]
    said = [line for line in said if line]
    if not said:
        return ""
    return "You hear: " + "; ".join(said) + "."


def heard_here(listener, room=None):
    """What `look` ends with: what can be heard here, or ""."""
    _place, every = ambience_for(listener, room)
    said = described(every)
    return f"|x{said}|n" if said else ""


# -- telling a session -----------------------------------------------------

def _wants_anything(account, session):
    return bool(speaks(session, account) or captions(account, session,
                                                     AMBIENCE))


def refresh(listener):
    """
    Bring what this listener hears up to where they are now, sending each
    session only what changed. A sound that is in both places carries on;
    one that has stopped applying fades out; a new one fades in.
    """
    sessions = _sessions(listener)
    if not sessions:
        return
    account = account_of(listener)
    wanting = [session for session in sessions
               if _wants_anything(account, session)]
    for session in sessions:
        if session not in wanting:
            _silence(session)
            setattr(session.ndb, _HEARING, None)
    if not wanting:
        return
    place, every = ambience_for(listener)
    for session in wanting:
        _refresh_session(listener, account, session, place, every)


def _hearing(session):
    """
    What a session was last told it hears: `{"via": the protocol its loops
    went by, or "", "loops": {hash: (volume, pan)}, "msp": hash or ""}`.
    """
    found = getattr(session.ndb, _HEARING, None)
    if not isinstance(found, dict) or "loops" not in found:
        return {"via": "", "loops": {}, "msp": ""}
    return found


def _silence(session):
    """
    Stop every loop a session was sent, by the protocol it was sent with --
    which is the one to use when somebody has just turned sound off, or
    changed how it is sent.
    """
    had = _hearing(session)
    if had["via"] == MEDIA and had["loops"]:
        _send(session, client_media_stop=((), {"tag": AMBIENCE,
                                                "fadeout": CROSSFADE}))
    if had["via"] == MSP and had["msp"]:
        _send(session, msp=(("!!MUSIC(Off)",), {}))
    had["via"], had["msp"] = "", ""


def moved(obj, source=None):
    """
    Something moved: refresh both ends, the room it left and the one it is
    in now, each counted from the outside of whatever it is in.
    """
    rooms = []
    for place in (source, getattr(obj, "location", None)):
        while getattr(place, "location", None) is not None:
            place = place.location
        if place is not None and place not in rooms:
            rooms.append(place)
    for room in rooms:
        refresh_room(room)
    if getattr(obj, "location", None) is None and _sessions(obj):
        refresh(obj)


def _refresh_session(listener, account, session, place, every):
    had = _hearing(session)
    speaking = speaks(session, account)
    if had["via"] and had["via"] != speaking:
        # How sounds are sent changed under it: what the old way started,
        # the old way stops.
        _silence(session)
    want = {asset.hash: (volume, pan) for asset, volume, pan in every}
    by_hash = {asset.hash: asset for asset, _volume, _pan in every}
    playing = had["loops"] if had["via"] == speaking else {}

    if speaking == MEDIA:
        for hash_ in playing:
            if hash_ not in want:
                stop(listener, "ambience-" + hash_, fade=CROSSFADE,
                     session=session)
        for hash_, (volume, pan) in want.items():
            if playing.get(hash_) == (volume, pan):
                continue
            play(listener, by_hash[hash_], category=AMBIENCE, volume=volume,
                 pan=pan, loop=True, key="ambience-" + hash_,
                 fade=0 if hash_ in playing else CROSSFADE, session=session)
    msp_now = ""
    if speaking == MSP:
        top = place[0] if place else None
        msp_now = top[0].hash if top is not None else ""
        if top is None:
            if had["msp"] and had["via"] == MSP:
                stop(listener, "ambience", session=session)
        elif not (had["via"] == MSP and had["msp"] == msp_now):
            play(listener, top[0], category=AMBIENCE, volume=top[1],
                 pan=top[2], loop=True, key="ambience", session=session)

    if captions(account, session, AMBIENCE):
        gone = [hash_ for hash_ in had["loops"] if hash_ not in want]
        new = [hash_ for hash_ in want if hash_ not in had["loops"]]
        line = _crossing_said(gone, new, by_hash)
        if line:
            listener.msg(line, session=session)

    setattr(session.ndb, _HEARING, {"via": speaking, "loops": dict(want),
                                    "msp": msp_now})


def _crossing_said(gone, new, by_hash):
    from world import assets

    def name(hash_):
        asset = by_hash.get(hash_) or assets.find(hash_)
        said = " ".join(str(getattr(asset, "description", "") or "")
                        .split()).rstrip(".")
        return said[:1].lower() + said[1:] if said else ""

    faded = [name(hash_) for hash_ in gone if name(hash_)]
    heard_now = [name(hash_) for hash_ in new if name(hash_)]
    parts = []
    if faded:
        parts.append("Fading: " + "; ".join(faded) + ".")
    if heard_now:
        parts.append("You hear: " + "; ".join(heard_now) + ".")
    return f"|x{' '.join(parts)}|n" if parts else ""


def forget_hearing(session):
    """
    A session no longer playing this character: stop what it was hearing,
    and start afresh whenever it plays somebody again.
    """
    _silence(session)
    setattr(session.ndb, _HEARING, None)


def refresh_room(room):
    """Everybody listening in this room."""
    for obj in list(getattr(room, "contents", None) or []):
        if _sessions(obj):
            refresh(obj)


def refresh_around(obj):
    """Whoever could hear this thing: everybody in its room, or itself."""
    room = getattr(obj, "location", None)
    if room is None:
        refresh_room(obj)
        return
    # Up to the room, through whatever it is inside: a thing in a box is
    # silent, and taking it out of one is a change its room hears.
    while getattr(room, "location", None) is not None:
        room = room.location
    refresh_room(room)
    if _sessions(obj):
        refresh(obj)


def refresh_world(world_root):
    """Everybody playing in this world, after its ambience was rewritten."""
    from evennia.server.sessionhandler import SESSIONS

    seen = set()
    for session in SESSIONS.get_sessions():
        puppet = getattr(session, "puppet", None)
        if puppet is None or puppet.id in seen:
            continue
        seen.add(puppet.id)
        room = getattr(puppet, "location", None)
        if room is not None and _world_of(room) == world_root:
            refresh(puppet)


def refresh_account(account):
    """Every character this account is playing, after a setting changed."""
    if account is None:
        return
    seen = set()
    for session in _sessions(account):
        puppet = getattr(session, "puppet", None)
        if puppet is not None and puppet.id not in seen:
            seen.add(puppet.id)
            refresh(puppet)


# -- ambience as a document says it ----------------------------------------
#
# A world document or a ruleset names its sounds and may arrive before them:
# an import fetches a world's sounds alongside it, and a missing one is
# fetched again later. So what a document says is kept as it says it -- a
# hash, or a built-in's `group/name` read as the built-in's hash -- and never
# dropped for not being here yet. `clean_ambience` is for a person choosing
# from what is here.

def written_ambience(entries):
    """A document's ambience list, shaped, with built-ins read as hashes."""
    from world import assets

    found = []
    for entry in entries or []:
        if not hasattr(entry, "get"):
            continue
        said = str(entry.get("sound") or "").strip()
        if "/" in said:
            builtin = assets.builtin(said)
            said = builtin.hash if builtin is not None else ""
        if not said:
            continue
        try:
            volume = max(0, min(100, int(entry.get("volume", 100))))
            pan = max(-100, min(100, int(entry.get("pan") or 0)))
        except (TypeError, ValueError):
            continue
        found.append({"sound": said.lower(), "volume": volume, "pan": pan})
    return found


def write_kind_ambience(world_root, kind, entries):
    """`set_kind_ambience`, for a document: kept by hash, not checked."""
    from world import kinds

    kind = kinds.canonical(kind)
    written = written_ambience(entries)
    if not world_root or not kind or not written:
        return []
    store = dict(getattr(world_root.db, kinds.ATTR, None) or {})
    entry = dict(store.get(kind) or {})
    entry[AMBIENCE_ATTR] = written
    store[kind] = entry
    setattr(world_root.db, kinds.ATTR, store)
    return written


def write_state_ambience(world_root, slug, entries):
    """`set_state_ambience`, for a document: kept by hash, not checked."""
    from world import verbs

    written = written_ambience(entries)
    vocab = verbs.vocabulary(world_root)
    if not world_root or slug not in vocab or not written:
        return []
    entry = dict(vocab[slug] or {})
    entry[AMBIENCE_ATTR] = written
    vocab[slug] = entry
    world_root.db.state_vocabulary = vocab
    return written


# ---------------------------------------------------------------------------
# A sound measured, for anybody who cannot hear it. docs/archived/sound.md 4.2
# ---------------------------------------------------------------------------

def measure(asset):
    """
    How long a sound is, how many channels, and -- with genny's measures --
    how loud and how sharp: enough for a model, or a player without sound,
    to tell a half-second chirp from a minute of rain, and a gentle one from
    one that bites. "" when it cannot be read.
    """
    import io

    import soundfile

    from world import assets

    if asset is None or asset.type != "sound" or asset.status != "present":
        return ""
    try:
        with assets.opened(asset) as handle:
            data, rate = soundfile.read(io.BytesIO(handle.read()))
    except Exception:
        return ""
    seconds = len(data) / float(rate)
    channels = 1 if data.ndim == 1 else data.shape[1]
    said = (f"{seconds:.2f} seconds, {'mono' if channels == 1 else 'stereo'}, "
            f"{rate} Hz.")
    made = asset.made_with or {}
    if made.get("loop"):
        said += " Made to loop."
    try:
        from genny import analysis

        found = analysis.describe(data, rate)
    except Exception:
        return said
    sharp = found.get("sharpness", 0.0)
    feel = ("soft" if sharp < 1.6 else "bright" if sharp <= 2.0
            else "sharp enough to bite")
    return (said + f" Peak {found['peak_db']:.1f} dB, loudness "
            f"{found['loudness']:.1f}; {feel} (sharpness {sharp:.2f}, "
            f"{found['above_5k'] * 100:.0f}% of it above 5 kHz).")
