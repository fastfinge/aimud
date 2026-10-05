"""
Where asset files live. docs/archived/assets.md 8.

Five things, and nothing else in the game touches an asset's bytes except
through them: keep a file, open one, say whether one is kept, delete one, and
say where a client can fetch one. A file is named by the hash of its
contents and the extension of its type, so a name says nothing about who
added it, and changes whenever the content does.

`ASSET_STORE` in settings names the class. `LocalStore` is the only one
written. An S3 store, or anything else, is another subclass of `Store` with
nothing else in the game changed -- which is why no caller may build a path
of its own, and why nothing a player is shown ever contains one.
"""

import os
import shutil
import tempfile

from django.conf import settings


def file_name(hash_, extension):
    """`<hash>.<extension>`: the only name an asset's file ever has."""
    extension = str(extension or "").lstrip(".").lower()
    return f"{hash_}.{extension}" if extension else str(hash_)


class Store:
    """What every store answers. See the module docstring."""

    def put(self, hash_, extension, source):
        """
        Keep a file. `source` is bytes, or the path of a file to copy in.

        Keeping a file already kept is not an error: the name is the
        content, so it is the same file.
        """
        raise NotImplementedError

    def open(self, hash_, extension):
        """The file, open for reading in binary."""
        raise NotImplementedError

    def exists(self, hash_, extension):
        raise NotImplementedError

    def delete(self, hash_, extension):
        """Forget a file. Forgetting one that is not kept is not an error."""
        raise NotImplementedError

    def url(self, hash_, extension):
        """
        Where a client fetches it: a path on this server, such as
        `/media/assets/<hash>.json`. `assets.public_url` makes it absolute.
        """
        raise NotImplementedError


class LocalStore(Store):
    """
    Files under `MEDIA_ROOT/assets/`, served by Evennia at `/media/assets/`.

    `MEDIA_ROOT` is gitignored and Evennia's web server lists no directories,
    so a file is reachable only by somebody who knows its hash.
    """

    FOLDER = "assets"

    def __init__(self, root=None):
        self.root = root or os.path.join(settings.MEDIA_ROOT, self.FOLDER)

    def _path(self, hash_, extension):
        return os.path.join(self.root, file_name(hash_, extension))

    def put(self, hash_, extension, source):
        os.makedirs(self.root, exist_ok=True)
        target = self._path(hash_, extension)
        if os.path.exists(target):
            return
        # Written beside the target and renamed into place, so a crash
        # halfway leaves a stray temporary file rather than a truncated asset
        # under a name that promises its whole contents.
        handle, temporary = tempfile.mkstemp(dir=self.root, suffix=".part")
        try:
            with os.fdopen(handle, "wb") as out:
                if isinstance(source, (bytes, bytearray)):
                    out.write(source)
                else:
                    with open(source, "rb") as given:
                        shutil.copyfileobj(given, out)
            os.replace(temporary, target)
        except BaseException:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise

    def open(self, hash_, extension):
        return open(self._path(hash_, extension), "rb")

    def exists(self, hash_, extension):
        return os.path.isfile(self._path(hash_, extension))

    def delete(self, hash_, extension):
        try:
            os.remove(self._path(hash_, extension))
        except FileNotFoundError:
            pass

    def url(self, hash_, extension):
        base = str(settings.MEDIA_URL or "/media/").rstrip("/")
        return f"{base}/{self.FOLDER}/{file_name(hash_, extension)}"


_store = None


def store():
    """The store `ASSET_STORE` names, made once."""
    global _store
    if _store is None:
        from django.utils.module_loading import import_string

        _store = import_string(getattr(settings, "ASSET_STORE",
                                       "world.asset_store.LocalStore"))()
    return _store


def use(replacement):
    """
    Put a different store in place, returning the one it replaced.

    For tests, which want a temporary folder rather than the real media
    directory, and for nothing else.
    """
    global _store
    previous, _store = _store, replacement
    return previous
