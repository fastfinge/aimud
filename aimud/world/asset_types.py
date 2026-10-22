"""
What kinds of file the game keeps. docs/archived/assets.md 4.

A type is registered by the system that uses it, when that system is built:
`world` documents now, and sounds, images and AIML when MSP, MXP and character
chat arrive. Each says how to recognise a file of its kind, how to check one
really is one, which versions this server can use, how big one may be, and
the permit that governs a tool making one.

**A file is what its contents say, never what its name says.** The extension
a type declares is the one its files are served under, and nothing reads an
extension to decide what a file is: `sniff` looks at the first bytes, and
`check` parses the whole file.

**No type is code.** `register` refuses any type whose extension is on
`NEVER`, and a test walks the register for the same thing, so there is no
way to make a script, a page or an executable an asset by adding a type.
"""

import json

#: Extensions no type may have. Code, markup a browser runs, and anything a
#: machine executes: an asset is played, shown or read, never run.
NEVER = frozenset((
    "py", "pyc", "pyw", "pyz", "exe", "dll", "so", "dylib", "bat", "cmd",
    "com", "ps1", "sh", "bash", "js", "mjs", "cjs", "wasm", "jar", "class",
    "html", "htm", "xhtml", "svg", "svgz", "php", "asp", "aspx", "jsp", "cgi",
    "pl", "rb", "lua", "vbs", "msi", "apk", "app", "scr", "hta", "swf",
))

#: How much of a file `sniff` is shown.
HEAD = 64


class AssetType:
    """
    One kind of file. Subclass and register; see the module docstring.

    `served` is whether `/media/` serves files of this type. Every type so far
    is, by decision (docs/archived/assets.md 8), and the flag keeps that a decision
    per type rather than a property of the store.
    """

    key = ""
    label = ""
    #: What files of this type are served as. Never used to decide what a
    #: file is.
    extension = ""
    #: Every extension a file of this type may be served as, for a type whose
    #: files come in more than one format. `extension_for` picks among them.
    extensions = ()
    most_bytes = 0
    #: The `permits.MAKES` entry governing a tool making one, or "" for a
    #: type only players supply.
    permit = ""
    served = True

    def sniff(self, head):
        """Whether these first bytes could start a file of this type."""
        raise NotImplementedError

    def check(self, path):
        """
        Parse the whole file as this type: `(version, "")` for one that is,
        `("", why not)` for one that is not.
        """
        raise NotImplementedError

    def refuses(self, version):
        """Why this server cannot use this version, or ""."""
        return ""

    def extension_for(self, version):
        """
        What a file of this type, at this version, is served as.

        A version is whatever `check` read off the file, which for a sound is
        its codec: an Ogg file and a WAV are one type with two extensions,
        and the record already says which it is, so the store's name for the
        file comes from that rather than from a column of its own.
        """
        return self.extension

    def every_extension(self):
        return {self.extension, *self.extensions} - {""}

    def uses(self, asset):
        """
        What is using this asset, as `{"said": a short description, "world":
        the world root}`: so deleting it can say what would break, and the
        owner of each world can be warned when it is given up or goes.
        [] for a type nothing uses yet.
        """
        return []

    def used_in(self, world_root):
        """
        The assets of this type a world uses, for its export to list.
        docs/archived/assets.md 9. [] for a type no world uses yet.
        """
        return []


_types = {}


def register(asset_type):
    """
    Add a type. Refuses one whose extension is code, or whose key is taken:
    two systems claiming one key would each read the other's files.
    """
    key = str(asset_type.key or "")
    extension = str(asset_type.extension or "").lstrip(".").lower()
    if not key or not extension:
        raise ValueError("an asset type needs a key and an extension")
    for each in asset_type.every_extension():
        if str(each).lstrip(".").lower() in NEVER:
            raise ValueError(f"{each} files are code, and never an asset")
    if key in _types and type(_types[key]) is not type(asset_type):
        raise ValueError(f"asset type {key!r} is already registered")
    _types[key] = asset_type
    return asset_type


def get(key):
    """The type with this key, or None."""
    return _types.get(str(key or ""))


def every():
    """{key: type} for every registered type."""
    return dict(_types)


def recognise(head):
    """The types whose `sniff` accepts these first bytes."""
    return [found for found in _types.values() if found.sniff(head[:HEAD])]


def described():
    """Each type as somebody choosing a file would want it said."""
    return [(found.key, found.label, found.most_bytes)
            for found in _types.values()]


# ---------------------------------------------------------------------------
# world: a world document, as `export world` writes and `import world` reads
# ---------------------------------------------------------------------------

class WorldDocument(AssetType):
    """
    A world document. docs/archived/import-and-export.md.

    Checked for being one, not for being importable here. Whether this server
    has the rulesets and services a world was built on is `import world`'s
    question, asked at import with its own answer, exactly as the shared
    folder always left it. A world needing a ruleset this server lacks is
    still a world somebody may want to keep.
    """

    key = "world"
    label = "A world document, as export world writes one"
    extension = "json"
    permit = ""

    @property
    def most_bytes(self):
        from world import exchange

        return exchange.MOST_BYTES

    def sniff(self, head):
        return bytes(head).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{")

    def check(self, path):
        from world import exchange

        try:
            with open(path, encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return "", f"it is not JSON this can read: {exc}"
        if not hasattr(doc, "keys"):
            return "", "it is not a world document"
        if str(doc.get("kind") or "") != exchange.KIND:
            return "", f"it is not a world; it says it is a {doc.get('kind')!r}"
        version = doc.get("aimud")
        if not isinstance(version, int) or isinstance(version, bool):
            return "", "it does not say which version of aimud wrote it"
        return str(version), ""

    def refuses(self, version):
        from world import exchange

        try:
            number = int(version)
        except (TypeError, ValueError):
            return "it does not say which version of aimud wrote it"
        if number > exchange.VERSION:
            return (f"it was written by aimud {number}, and this server reads "
                    f"{exchange.VERSION}")
        return ""


register(WorldDocument())


# ---------------------------------------------------------------------------
# sound: what MSP, Client.Media and the web client play.
# docs/archived/sound.md 4
# ---------------------------------------------------------------------------

#: What each codec a sound may be in is served as. A codec missing from here
#: is one no MUD client can be relied on to play, and is refused by name.
SOUND_CODECS = {"pcm": "wav", "vorbis": "ogg", "mp3": "mp3"}

#: How a codec is said to somebody whose file was refused.
_CODEC_SAID = {"opus": "Opus", "mp2": "MPEG layer II", "mp1": "MPEG layer I",
               "float": "floating-point WAV"}


class SoundFile(AssetType):
    """
    A sound, as a client fetches and plays it.

    Recognised by its first bytes, and then decoded from end to end by
    libsndfile (`soundfile`): a file that only starts like a sound is not one,
    and a client should never be the first thing to find out. Its version is
    its codec, which is also what decides the extension it is served under.
    """

    key = "sound"
    label = "A sound: WAV, Ogg Vorbis or MP3"
    extension = "ogg"
    extensions = tuple(SOUND_CODECS.values())
    most_bytes = 10 * 1024 * 1024
    permit = "sounds"

    def sniff(self, head):
        head = bytes(head)
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return True
        if head[:4] == b"OggS" or head[:3] == b"ID3":
            return True
        # A bare MPEG audio frame: eleven set bits of frame sync.
        return len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0

    def check(self, path):
        try:
            import soundfile
        except ImportError:
            return "", "this server cannot read sounds: soundfile is missing"
        try:
            info = soundfile.info(path)
            codec = _codec(info.format, info.subtype)
            if codec in SOUND_CODECS:
                # Decoded to the end, a block at a time: a header that
                # parses over a body that does not is the case this is for.
                for _block in soundfile.blocks(path, blocksize=65536):
                    pass
        except Exception as exc:
            return "", f"it is not a sound this can play: {exc}"
        if info.frames <= 0:
            return "", "it is a sound with nothing in it"
        return codec, ""

    def refuses(self, version):
        if version in SOUND_CODECS:
            return ""
        said = _CODEC_SAID.get(version, version or "a format nothing names")
        return (f"it is {said}, which MUD clients cannot all play. WAV, Ogg "
                f"Vorbis and MP3 can be")

    def extension_for(self, version):
        return SOUND_CODECS.get(str(version or ""), self.extension)

    def uses(self, asset):
        from world import sound

        return sound.uses(asset)

    def used_in(self, world_root):
        from world import sound

        return sound.used_in(world_root)


def _codec(format_, subtype):
    """The codec libsndfile found, said the way a sound's version is."""
    format_, subtype = str(format_ or "").upper(), str(subtype or "").upper()
    if format_ in ("WAV", "WAVEX"):
        return "pcm" if subtype.startswith("PCM_") else "float"
    if format_ == "OGG":
        return {"VORBIS": "vorbis", "OPUS": "opus"}.get(subtype, subtype.lower())
    if format_ == "MP3":
        return {"MPEG_LAYER_III": "mp3", "MPEG_LAYER_II": "mp2",
                "MPEG_LAYER_I": "mp1"}.get(subtype, "mp3")
    return format_.lower()


register(SoundFile())
