"""
Playing a sound to somebody. docs/sound.md 3.

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
  instead is the text every sound also is (docs/sound.md 7).

A client that understands both is sent `Client.Media` only, never both, or
it would play everything twice.

**A sound is fetched from this server by URL**, so without `ASSET_BASE_URL`
nothing is sent: a client given a path it cannot reach plays nothing and
says nothing, which is worse than not being asked.

**Panning** is accepted and played from the centre until panned copies
exist (docs/sound.md 3.4, phase 5): no MUD protocol can pan by itself.
"""

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
    """An asset from an asset, a hash, or a built-in's `group/name`."""
    from world import assets

    if sound is None or hasattr(sound, "hash"):
        return sound
    said = str(sound)
    if "/" in said:
        return assets.builtin(said)
    return assets.find(said)


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

    sent = 0
    for session in ([session] if session is not None
                    else _sessions(listener)):
        speaking = speaks(session, account)
        if speaking == MEDIA:
            payload = {"name": name, "url": folder,
                       "type": "music" if category == MUSIC else "sound",
                       "tag": category, "volume": max(1, loud),
                       "loops": -1 if loop else 1,
                       "caption": str(asset.description or "")}
            if key:
                payload["key"] = str(key)
                payload["continue"] = True
            if fade:
                payload["fadein"] = int(fade)
            _send(session, client_media_play=((), payload))
        elif speaking == MSP:
            if loop:
                line = _msp_line("MUSIC", name, folder, loud, -1, category,
                                 keep=True)
                setattr(session.ndb, _MSP_MUSIC, str(key or name))
            else:
                line = _msp_line("SOUND", name, folder, loud, 1, category)
            _send(session, msp=((line,), {}))
        else:
            continue
        sent += 1
    if sent:
        assets.touch(asset)
    return sent


def stop(listener, key, fade=0):
    """Stop the sound playing under `key`, where it can be stopped."""
    sent = 0
    account = account_of(listener)
    for session in _sessions(listener):
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
#: docs/sound.md 8.
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
