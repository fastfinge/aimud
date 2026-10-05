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
    if extension in NEVER:
        raise ValueError(f"{extension} files are code, and never an asset")
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
