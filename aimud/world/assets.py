"""
Assets: files the game keeps for its players and its tools. docs/archived/assets.md.

`add` is the one writer. An upload on the website, a URL fetched by `create
asset`, a file named by an imported world, and a file a tool made all arrive
here as a file on disk, and are checked the same way before anything is kept:
that it is a type this server keeps (by its contents, never its name), that
its version is one this server can use, that it is no bigger than its type
allows, and that whoever is paying for it has room. Only then is it stored,
by the hash of its contents.

**Charged once, to whoever paid for it to exist** (docs/archived/assets.md 7). The
player who added it, the importer, or the account whose key paid for a tool
to make it. Adding a file the server already has charges nobody, and reusing
an asset never moves its charge.

**Nobody is shown a path.** Every message here names an asset by its name,
and a file by its type; the store's own folders never reach a player.
"""

import hashlib
import os
import tempfile

from django.conf import settings


class Refused(Exception):
    """Why a file was not kept, as sentences a player can act on."""

    def __init__(self, complaints):
        self.complaints = [str(said) for said in complaints]
        super().__init__("; ".join(self.complaints))


def _model():
    from assets.models import Asset

    return Asset


# ---------------------------------------------------------------------------
# Sizes, as people read them
# ---------------------------------------------------------------------------

def size_said(size):
    """`2.4 MB`, `512 KB`, `90 bytes`: a size as somebody would say it."""
    size = int(size or 0)
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= scale:
            amount = size / scale
            return f"{amount:.1f} {unit}" if amount < 10 else f"{amount:.0f} {unit}"
    return f"{size} byte{'s' if size != 1 else ''}"


# ---------------------------------------------------------------------------
# Quotas
# ---------------------------------------------------------------------------

def quota_of(account):
    """
    How much this account may keep, in bytes, or None for no limit.

    Its own, when an admin has set one (`edit quota`), whichever way that
    goes; otherwise `ASSET_QUOTA`.
    """
    own = getattr(account.db, "asset_quota", None) if account is not None \
        else None
    if own is not None:
        return int(own)
    default = getattr(settings, "ASSET_QUOTA", None)
    return None if default is None else int(default)


def used_by(account):
    """Bytes this account is charged for."""
    from django.db.models import Sum

    if account is None:
        return 0
    total = _model().objects.filter(
        charged_to=account, status="present").aggregate(Sum("size"))
    return int(total["size__sum"] or 0)


def room_for(account, size):
    """Why this account cannot take on `size` more bytes, or ""."""
    if account is None:
        return ""
    allowed = quota_of(account)
    if allowed is None:
        return ""
    used = used_by(account)
    if used + int(size) <= allowed:
        return ""
    return (f"that is {size_said(size)}, and {account.key} is using "
            f"{size_said(used)} of {size_said(allowed)}, with "
            f"{size_said(max(allowed - used, 0))} left")


# ---------------------------------------------------------------------------
# Adding one
# ---------------------------------------------------------------------------

def hash_of(path):
    """SHA-256 of a file's contents, read in pieces."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def identify(path, wanted=None):
    """
    `(type, version)` for this file, or `Refused` saying why it is neither.

    Every type whose `sniff` accepts the first bytes is asked to `check` the
    whole file; the first that accepts it, at a version this server can use
    and a size its type allows, is the answer. `wanted` narrows it to one
    type key, for somewhere that can use only that.
    """
    from world import asset_types

    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head = handle.read(asset_types.HEAD)
    candidates = asset_types.recognise(head)
    if wanted:
        candidates = [found for found in candidates if found.key == wanted]
    if not candidates:
        kinds = "; ".join(label for _key, label, _most in
                          asset_types.described()
                          if not wanted or _key == wanted)
        raise Refused([f"that is not a kind of file this server keeps. It "
                       f"keeps: {kinds}"])

    wrong = []
    for found in candidates:
        if size > found.most_bytes:
            wrong.append(f"that is {size_said(size)}, and "
                         f"{size_said(found.most_bytes)} is the most a "
                         f"{found.key} file may be")
            continue
        version, why = found.check(path)
        if why:
            wrong.append(why)
            continue
        refused = found.refuses(version)
        if refused:
            wrong.append(refused)
            continue
        return found, version
    raise Refused(wrong)


_SAME = object()


def add(path, *, name, description, added_by, origin, charged_to=_SAME,
        source="", author="", licence="", made_with=None, wanted=None):
    """
    Keep a file. Returns `(asset, said)`; raises `Refused` with the reasons.

    `charged_to` is whoever paid for it to exist; it is `added_by` unless a
    tool made it, when it is the sponsor's payer (docs/archived/assets.md 7). `said` is
    a sentence for whoever added it, which is different when the file was
    already here: they are given the asset that exists, charged nothing.
    """
    from world import asset_store

    name = " ".join(str(name or "").split())
    description = str(description or "").strip()
    wrong = []
    if not name:
        wrong.append("an asset needs a name")
    if not description:
        wrong.append("an asset needs a description: it is how anybody "
                     "who cannot see or hear it finds it, a model included")
    if wrong:
        raise Refused(wrong)

    found, version = identify(path, wanted=wanted)
    size = os.path.getsize(path)
    hash_ = hash_of(path)
    payer = added_by if charged_to is _SAME else charged_to

    Asset = _model()
    existing = Asset.objects.filter(hash=hash_).first()
    if existing is not None and existing.status == Asset.PRESENT:
        return existing, (f"That file is already here, as |w{existing.name}|n. "
                          f"It costs you nothing.")

    refused = room_for(payer, size)
    if refused:
        raise Refused([refused])

    asset_store.store().put(hash_, found.extension, path)
    if existing is not None:
        # Missing, and somebody has brought it back: whoever did is who paid
        # for it to exist this time. Its name and description stay, since
        # worlds already know it by them.
        existing.status = Asset.PRESENT
        existing.charged_to = payer
        existing.size = size
        existing.save()
        return existing, f"|w{existing.name}|n is back."

    asset = Asset.objects.create(
        hash=hash_, type=found.key, version=str(version or ""), name=name,
        description=description, size=size, added_by=added_by,
        charged_to=payer, origin=origin, source=str(source or ""),
        author=str(author or ""), licence=str(licence or ""),
        made_with=dict(made_with or {}))
    return asset, (f"|w{asset.name}|n is kept, {size_said(size)}, as a "
                   f"{found.key} asset.")


def add_bytes(data, **kwargs):
    """`add`, for contents already in memory: an upload, or a test."""
    handle, path = tempfile.mkstemp(suffix=".asset")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        return add(path, **kwargs)
    finally:
        os.remove(path)


# ---------------------------------------------------------------------------
# Fetching one
# ---------------------------------------------------------------------------
#
# The one place in the game that downloads a file somebody named. Drawbridge
# does the part that is easy to get wrong -- every address a host resolves to
# must be public, the connection goes to the address that was checked rather
# than to a second lookup, and every redirect is checked again -- and this
# adds what a game wants on top: a size cap counted on the bytes that actually
# arrive, a timeout, a file on disk rather than bytes in memory, and refusals
# a player can read. docs/archived/assets.md 6.

#: Seconds before a download is given up.
FETCH_TIMEOUT = 30

#: Networks treated as public anyway. Empty, and only ever patched by tests,
#: which need a server on the loopback address to fetch from. Nothing a
#: player or a setting can reach changes it.
TRUSTED_NETWORKS = ()

#: Ports a download may use besides `ASSET_FETCH_PORTS`. Empty, and for tests
#: only, for the same reason.
TRUSTED_PORTS = ()


def _policy(most_bytes):
    import ipaddress

    import drawbridge

    ports = set(getattr(settings, "ASSET_FETCH_PORTS",
                        (80, 443, 8080, 8443, 4001)))
    ports.update(TRUSTED_PORTS)
    return drawbridge.Policy(
        allow_ports=frozenset(int(port) for port in ports),
        ip_allowlist=frozenset(ipaddress.ip_network(net)
                               for net in TRUSTED_NETWORKS),
        timeout=FETCH_TIMEOUT, max_redirects=5,
        max_response_bytes=int(most_bytes),
        user_agent="aimud asset fetch")


def _refusal(exc, most_bytes):
    """A drawbridge or httpx failure, as a sentence somebody can act on."""
    import drawbridge
    import httpx

    if isinstance(exc, drawbridge.UnsafeSchemeError):
        return "only http and https addresses can be fetched"
    if isinstance(exc, (drawbridge.BlockedAddressError,
                        drawbridge.BlockedDomainError)):
        return ("that address is inside a private network, and this server "
                "does not fetch from one")
    if isinstance(exc, drawbridge.UnsafePortError):
        ports = ", ".join(str(port) for port in sorted(exc.allowed)) \
            if getattr(exc, "allowed", None) else "the usual ones"
        return f"this server fetches only from ports {ports}"
    if isinstance(exc, drawbridge.TooManyRedirectsError):
        return "it sent this server somewhere else too many times"
    if isinstance(exc, drawbridge.DrawbridgeDNSError):
        return "there is no such address"
    if isinstance(exc, drawbridge.ResponseTooLargeError):
        return f"it is bigger than {size_said(most_bytes)}"
    if isinstance(exc, httpx.TimeoutException):
        return f"it took longer than {FETCH_TIMEOUT} seconds"
    if isinstance(exc, httpx.HTTPError):
        return "it could not be reached"
    return "it could not be fetched"


def fetch(url, most_bytes):
    """
    Download `url` to a temporary file and answer its path. Blocking: run it
    in a thread. The caller deletes the file.

    Raises `Refused` with the reason for anything short of a whole file: an
    address that is private or not http, a server that refuses, a file bigger
    than `most_bytes` -- counted as it arrives, whatever the server says its
    size is -- or one that takes too long.
    """
    import drawbridge
    import httpx

    url = str(url or "").strip()
    if not url:
        raise Refused(["there is no address to fetch"])

    handle, path = tempfile.mkstemp(suffix=".fetch")
    kept = False
    try:
        with os.fdopen(handle, "wb") as out, \
                drawbridge.SyncClient(_policy(most_bytes)) as client, \
                client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise Refused([f"the server there answered "
                               f"{response.status_code}, not a file"])
            received = 0
            for piece in response.iter_bytes():
                received += len(piece)
                if received > most_bytes:
                    raise Refused([f"it is bigger than "
                                   f"{size_said(most_bytes)}"])
                out.write(piece)
        kept = True
        return path
    except Refused:
        raise
    except (drawbridge.DrawbridgeError, httpx.HTTPError, OSError) as exc:
        raise Refused([_refusal(exc, most_bytes)])
    finally:
        if not kept and os.path.exists(path):
            os.remove(path)


def largest():
    """The most any registered type allows: the most a fetch need ever take."""
    from world import asset_types

    return max((found.most_bytes for found in asset_types.every().values()),
               default=0)


# ---------------------------------------------------------------------------
# Finding one
# ---------------------------------------------------------------------------

def search(type_=None, words="", status="present"):
    """Assets, newest first: of one type, matching some words, in a state."""
    from django.db.models import Q

    found = _model().objects.all()
    if type_:
        found = found.filter(type=type_)
    if status:
        found = found.filter(status=status)
    for word in str(words or "").split():
        found = found.filter(Q(name__icontains=word)
                             | Q(description__icontains=word))
    return found


def named(said, type_=None, status=None):
    """
    `(asset, "")` for the asset somebody named, or `(None, why not)`.

    By name, exactly and then in part, or by the start of its hash for two
    assets that share a name. Names are not unique, so a name two assets
    share is answered with both, to be told apart.
    """
    said = " ".join(str(said or "").split())
    if not said:
        return None, "Which asset? |wview assets|n lists them."
    every = search(type_, status=status)
    exact = list(every.filter(name__iexact=said)[:10])
    if not exact and len(said) >= 6:
        exact = list(every.filter(hash__startswith=said.lower())[:10])
    found = exact or list(every.filter(name__icontains=said)[:10])
    if len(found) == 1:
        return found[0], ""
    if not found:
        return None, f"There is no asset called {said}. |wview assets|n lists them."
    choices = "; ".join(f"|w{asset.hash[:8]}|n {asset.name}" for asset in found)
    return None, (f"More than one asset is called {said}: {choices}. Name one "
                  f"by the start of its hash instead.")


def is_admin(account):
    """Whether this account may remove and review anybody's assets."""
    if account is None:
        return False
    try:
        return bool(account.is_superuser
                    or account.check_permstring("Admin"))
    except AttributeError:
        return False


def may_change(account, asset):
    """Whoever is charged for it, or an admin; a given-up one, an admin."""
    return is_admin(account) or (asset.charged_to_id is not None
                                 and asset.charged_to_id == getattr(
                                     account, "id", None))


def edit(asset, **fields):
    """Change what an asset is called or credited as. Never its contents."""
    for field in ("name", "description", "author", "licence"):
        if field not in fields:
            continue
        value = " ".join(str(fields[field] or "").split()) if field == "name" \
            else str(fields[field] or "").strip()
        if field in ("name", "description") and not value:
            raise Refused([f"an asset needs a {field}"])
        setattr(asset, field, value)
    asset.save()
    return asset


def uses_of(asset):
    """What is using this asset, as its type says."""
    from world import asset_types

    found = asset_types.get(asset.type)
    return list(found.uses(asset) or []) if found is not None else []


def delete(asset, force=False):
    """
    Delete an asset. Refused while something uses it, unless an admin forces
    it, which leaves whatever used it holding a missing asset rather than a
    broken reference. docs/archived/assets.md 12.
    """
    from world import asset_store

    using = uses_of(asset)
    if using and not force:
        raise Refused([f"{asset.name} is in use: " + "; ".join(
            str(use.get("said", use)) for use in using)])
    asset_store.store().delete(asset.hash, extension_of(asset))
    if using:
        _go_missing(asset, f"|w{asset.name}|n was removed by an admin, and is "
                           f"missing now.")
        return f"|w{asset.name}|n is removed, and missing wherever it was used."
    name = asset.name
    asset.delete()
    return f"|w{name}|n is deleted."


# ---------------------------------------------------------------------------
# The pool: what owners gave up. docs/archived/assets.md 7.1
# ---------------------------------------------------------------------------

#: How full the pool may be before its owners hear what is next in line.
NEARLY_FULL = 0.9


def pool_quota():
    found = getattr(settings, "ASSET_POOL_QUOTA", None)
    return None if found is None else int(found)


def pool_used():
    from django.db.models import Sum

    total = _model().objects.filter(
        charged_to__isnull=True, status="present").aggregate(Sum("size"))
    return int(total["size__sum"] or 0)


def _eviction_order(exclude=None):
    """The pool, least used first: fewest users, then longest unused."""
    pool = _model().objects.filter(charged_to__isnull=True, status="present")
    if exclude is not None:
        pool = pool.exclude(pk=exclude.pk)

    def key(asset):
        last = asset.last_used or asset.added
        return (len(uses_of(asset)), last)

    return sorted(pool, key=key)


def _would_evict(needed, exclude=None):
    """What making room for `needed` more bytes would take, in order."""
    allowed = pool_quota()
    if allowed is None:
        return []
    over = pool_used() + int(needed) - allowed
    taken = []
    for asset in _eviction_order(exclude):
        if over <= 0:
            break
        taken.append(asset)
        over -= asset.size
    return taken


def make_room(exclude=None):
    """Evict until the pool fits its quota. Returns what went."""
    allowed = pool_quota()
    if allowed is None or pool_used() <= allowed:
        return []
    gone = _would_evict(0, exclude=exclude)
    for asset in gone:
        from world import asset_store

        asset_store.store().delete(asset.hash, extension_of(asset))
        _go_missing(asset, f"|w{asset.name}|n, which the server was keeping "
                           f"after it was given up, has been removed to make "
                           f"room, and is missing now."
                           + (f" It can be fetched again from where it came: "
                              f"|wedit asset {asset.hash[:8]} fetch|n."
                              if asset.source else ""))
    return gone


def next_in_line():
    """
    What would go to make room for one more of the largest file, once the
    pool is nearly full; [] otherwise.
    """
    allowed = pool_quota()
    if not allowed or pool_used() < allowed * NEARLY_FULL:
        return []
    return _would_evict(largest())


def give_up(account, asset):
    """
    Hand an asset to the server: it stops counting against whoever gave it
    up, and everything using it keeps it. Returns a sentence.
    """
    if asset.charged_to_id != getattr(account, "id", None):
        raise Refused(["only whoever is charged for an asset can give it up"])
    allowed = pool_quota()
    if allowed is not None and asset.size > allowed:
        raise Refused([f"{asset.name} is {size_said(asset.size)}, more than "
                       f"the server keeps of given-up assets altogether"])
    asset.charged_to = None
    asset.save()
    warn_owners(asset, f"|w{asset.name}|n has been given up to the server, "
                       f"which may remove it when it runs short of room. "
                       f"|wedit asset {asset.hash[:8]} adopt|n keeps it, on "
                       f"your quota ({size_said(asset.size)}).")
    gone = make_room(exclude=asset)
    for asset_in_line in next_in_line():
        warn_owners(asset_in_line,
                    f"|w{asset_in_line.name}|n is next in line to be removed "
                    f"from the server's pool. |wedit asset "
                    f"{asset_in_line.hash[:8]} adopt|n keeps it.",
                    once="next")
    said = f"|w{asset.name}|n is the server's now, and no longer yours."
    if gone:
        said += f" To make room, {len(gone)} older given-up asset(s) went."
    return said


def given_up_in(world_root):
    """The given-up assets this world uses: the pool, asked of each type."""
    if world_root is None:
        return []
    found = []
    for asset in _model().objects.filter(charged_to__isnull=True,
                                         status="present"):
        if any(hasattr(use, "get") and use.get("world") == world_root
               for use in uses_of(asset)):
            found.append(asset)
    return found


def adopt(account, asset):
    """Take a given-up asset onto one's own quota, out of the pool's reach."""
    if asset.charged_to_id is not None:
        raise Refused([f"{asset.name} is already somebody's"])
    if asset.status != _model().PRESENT:
        raise Refused([f"{asset.name} is missing; fetch it again instead"])
    refused = room_for(account, asset.size)
    if refused:
        raise Refused([refused])
    asset.charged_to = account
    asset.save()
    return (f"|w{asset.name}|n is yours now, and counts "
            f"{size_said(asset.size)} against your quota.")


def _go_missing(asset, told):
    asset.status = _model().MISSING
    asset.charged_to = None
    asset.save()
    warn_owners(asset, told)


# ---------------------------------------------------------------------------
# Telling the owners of worlds that use something. docs/archived/assets.md 7.1
# ---------------------------------------------------------------------------

def _owner_of(use):
    from world import sponsor

    world_root = use.get("world") if hasattr(use, "get") else None
    return sponsor.creator_of(world_root) if world_root is not None else None


def warn_owners(asset, text, once=""):
    """
    Tell the creator of every world using this asset, once.

    At once if they are logged in; otherwise kept on the account and said at
    their next login. `once` names a warning that should not be repeated for
    the same asset (`next`, for next in line), however often it comes true.
    """
    from world import sponsor

    told = set()
    for use in uses_of(asset):
        owner = _owner_of(use)
        if owner is None or owner.id in told:
            continue
        told.add(owner.id)
        if once:
            seen = set(owner.db.asset_warned or [])
            mark = f"{once}:{asset.hash}"
            if mark in seen:
                continue
            seen.add(mark)
            owner.db.asset_warned = sorted(seen)
        said = f"|y{text}|n"
        if sponsor.present(owner):
            owner.msg(said)
        else:
            waiting = list(owner.db.asset_notices or [])
            waiting.append(said)
            owner.db.asset_notices = waiting
    return len(told)


def deliver_notices(account):
    """Everything that happened to an account's assets while it was away."""
    waiting = list(account.db.asset_notices or [])
    if not waiting:
        return 0
    account.attributes.remove("asset_notices")
    account.msg("|wWhile you were away|n, assets your worlds use changed:\n"
                + "\n".join(waiting))
    return len(waiting)


def touch(asset, now=None):
    """
    Say an asset was used, for choosing what a full pool lets go. Written at
    most once an hour per asset: a sound playing every turn is not a write
    every turn.
    """
    from datetime import timedelta

    from django.utils import timezone

    now = now or timezone.now()
    if asset.last_used is None or now - asset.last_used > timedelta(hours=1):
        _model().objects.filter(pk=asset.pk).update(last_used=now)
        asset.last_used = now


# ---------------------------------------------------------------------------
# Quotas an admin sets
# ---------------------------------------------------------------------------

def read_size(text):
    """`750MB`, `1 gb`, `500k`, `default`, `none` -> bytes, "default" or None."""
    said = str(text or "").strip().lower().replace(" ", "")
    if said in ("default", ""):
        return "default"
    if said in ("none", "unlimited", "nolimit"):
        return None
    for unit, scale in (("gb", 1024 ** 3), ("g", 1024 ** 3),
                        ("mb", 1024 ** 2), ("m", 1024 ** 2),
                        ("kb", 1024), ("k", 1024), ("b", 1)):
        if said.endswith(unit):
            number = said[:-len(unit)]
            break
    else:
        number, scale = said, 1024 ** 2
    try:
        value = float(number)
    except ValueError:
        raise Refused([f"{text} is not a size: try 750MB or 2GB"])
    if value < 0:
        raise Refused(["a quota cannot be less than nothing"])
    return int(value * scale)


def set_quota(account, size):
    """Give one account its own quota; `"default"` takes it away again."""
    if size == "default":
        account.attributes.remove("asset_quota")
        return f"{account.key} has the default quota again."
    if size is None:
        raise Refused(["one account cannot be given no limit; raise its quota "
                       "instead"])
    account.db.asset_quota = int(size)
    return f"{account.key} may keep {size_said(size)} of assets."


# ---------------------------------------------------------------------------
# Worlds carry their assets. docs/archived/assets.md 9
# ---------------------------------------------------------------------------

def listed(world_root):
    """
    Every asset a world uses, as its export lists them: by name and hash,
    with where to fetch each and what it is, and never a path.
    """
    from world import asset_types

    entries, seen = [], set()
    for found in asset_types.every().values():
        for asset in found.used_in(world_root) or []:
            if asset.hash in seen:
                continue
            seen.add(asset.hash)
            entries.append({
                "name": asset.name, "type": asset.type, "hash": asset.hash,
                "size": int(asset.size), "url": public_url(asset),
                "description": asset.description, "author": asset.author,
                "licence": asset.licence})
    return sorted(entries, key=lambda entry: (entry["type"], entry["name"],
                                              entry["hash"]))


def entry_problems(entries):
    """What is wrong with a document's asset list, as sentences."""
    import re

    from world import asset_types

    if not isinstance(entries, list):
        return ["assets is not a list"]
    wrong = []
    for index, entry in enumerate(entries):
        if not hasattr(entry, "get"):
            wrong.append(f"assets[{index}] is not an object")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("hash") or "")):
            wrong.append(f"assets[{index}] has no hash this can check against")
        if asset_types.get(entry.get("type")) is None:
            wrong.append(f"assets[{index}] is a {entry.get('type')!r}, which "
                         f"this server does not keep")
        if not str(entry.get("name") or "").strip():
            wrong.append(f"assets[{index}] has no name")
    return wrong


def to_bring(doc):
    """The entries of a document this server has not got."""
    found = []
    for entry in doc.get("assets") or []:
        asset = find(entry.get("hash"))
        if asset is None or asset.status != _model().PRESENT:
            found.append(entry)
    return found


def room_to_bring(doc, account):
    """Why `account` has no room for what an import would bring, or ""."""
    needed = sum(int(entry.get("size") or 0) for entry in to_bring(doc))
    if not needed:
        return ""
    refused = room_for(account, needed)
    return (f"its assets need {size_said(needed)} of your quota: {refused}"
            if refused else "")


def _record_missing(entry, account):
    """A record for an asset that could not be brought, to fetch later."""
    from world import asset_types

    Asset = _model()
    existing = find(entry.get("hash"))
    if existing is not None:
        return existing
    found = asset_types.get(entry.get("type"))
    return Asset.objects.create(
        hash=str(entry["hash"]), type=found.key if found else "",
        name=" ".join(str(entry.get("name") or "an asset").split())[:120],
        description=str(entry.get("description") or "").strip()
        or "Came with an imported world, and could not be fetched.",
        size=int(entry.get("size") or 0), added_by=account, charged_to=None,
        origin=Asset.IMPORT, source=str(entry.get("url") or ""),
        author=str(entry.get("author") or ""),
        licence=str(entry.get("licence") or ""), status=Asset.MISSING)


def keep_fetched(path, entry, account):
    """
    Keep a downloaded file as the asset an entry named, if it is that file.

    The hash is checked first: a server handing back something else has not
    handed back the asset, whatever it is. Returns a sentence; a file that
    is not the one named leaves a missing record instead.
    """
    if hash_of(path) != entry.get("hash"):
        _record_missing(entry, account)
        return f"{entry.get('name')} was not the file the world named"
    try:
        add(path, name=entry.get("name"),
            description=entry.get("description") or "Came with a world.",
            added_by=account, origin=_model().IMPORT,
            source=str(entry.get("url") or ""),
            author=entry.get("author") or "",
            licence=entry.get("licence") or "", wanted=entry.get("type"))
    except Refused as refusal:
        _record_missing(entry, account)
        return f"{entry.get('name')}: {refusal}"
    return ""


def bring_in(doc, account, on_done):
    """
    Fetch every asset a document names that this server has not got, then
    call `on_done(problems)`. Known hashes are reused without a download --
    the reset-on-the-same-server case. Fetching runs in a thread, one at a
    time; keeping runs here. Anything that cannot be fetched, or is not the
    file named, is recorded missing and does not stop the import.
    """
    import os

    from twisted.internet import threads

    queue = list(to_bring(doc))
    problems = []

    def next_one(_=None):
        if not queue:
            on_done(problems)
            return
        entry = queue.pop(0)
        if not entry.get("url"):
            _record_missing(entry, account)
            problems.append(f"{entry.get('name')} has nowhere to fetch it from")
            next_one()
            return

        def fetched(path):
            try:
                said = keep_fetched(path, entry, account)
                if said:
                    problems.append(said)
            finally:
                if os.path.exists(path):
                    os.remove(path)
            next_one()

        def failed(failure):
            _record_missing(entry, account)
            problems.append(f"{entry.get('name')}: {failure.value}")
            next_one()

        threads.deferToThread(fetch, entry["url"], largest()) \
            .addCallbacks(fetched, failed)

    next_one()


def fetch_again(account, asset, on_done):
    """Try a missing asset's source again, charged to whoever asks."""
    import os

    from twisted.internet import threads

    if asset.status != _model().MISSING:
        on_done(f"{asset.name} is not missing")
        return
    if not asset.source:
        on_done(f"{asset.name} has nowhere to fetch it from")
        return
    entry = {"hash": asset.hash, "name": asset.name, "type": asset.type,
             "url": asset.source, "description": asset.description}

    def fetched(path):
        try:
            if hash_of(path) != asset.hash:
                on_done(f"what is at {asset.source} now is not {asset.name}")
                return
            add(path, name=asset.name, description=asset.description,
                added_by=account, origin=asset.origin, source=asset.source,
                wanted=asset.type)
            on_done("")
        except Refused as refusal:
            on_done(str(refusal))
        finally:
            if os.path.exists(path):
                os.remove(path)

    threads.deferToThread(fetch, entry["url"], largest()).addCallbacks(
        fetched, lambda failure: on_done(str(failure.value)))


def keep_world(doc, account, origin="export"):
    """
    Keep a world document as a `world` asset: what `export world` writes now
    that the shared folder is the register. Returns `(asset, said)`.
    """
    import json

    setup = doc.get("setup") or {}
    title = str(doc.get("title") or setup.get("title") or "A world")
    about = str(setup.get("description") or "").strip().splitlines()
    description = (about[0] if about else "") or (
        f"The world {title}, {int(doc.get('rooms') or 0)} room(s), as "
        f"exported on {doc.get('exported') or 'an unknown day'}.")
    data = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return add_bytes(data, name=title, description=description,
                     added_by=account, origin=origin, wanted="world")


def world_document(asset):
    """The document a `world` asset holds."""
    import json

    with opened(asset) as handle:
        return json.loads(handle.read().decode("utf-8"))


def take_in_folder():
    """
    Bring every world document in `WORLD_DIRS` into the register, once.

    At server start. A file somebody put on the machine by hand is charged
    to nobody, as anything the server holds for itself is, and is left
    where it is, so a later startup finds anything added since. Returns how
    many were new. docs/archived/assets.md 13.
    """
    import json
    import os

    from evennia.utils import logger

    from world import exchange

    added = 0
    for directory in exchange.directories():
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(directory, entry)
            try:
                if find(hash_of(path)) is not None:
                    continue
                with open(path, encoding="utf-8") as handle:
                    doc = json.load(handle)
                setup = (doc.get("setup") or {}) if hasattr(doc, "get") else {}
                add(path, name=str(doc.get("title") or entry[:-5]),
                    description=str(setup.get("description") or "").strip()
                    or "A world document found in the shared folder.",
                    added_by=None, charged_to=None, origin=_model().FOLDER,
                    wanted="world")
                added += 1
            except (OSError, ValueError, AttributeError, Refused) as exc:
                logger.log_info(f"assets: {entry} in the shared folder was "
                                f"not taken in: {exc}")
    return added


# ---------------------------------------------------------------------------
# Assets that tools make. docs/archived/assets.md 11
# ---------------------------------------------------------------------------

def request_of(service, tool, arguments):
    """What a tool was asked, in a form two identical requests share."""
    return {"service": str(service), "tool": str(tool),
            "arguments": {str(key): str(value) for key, value in
                          sorted(dict(arguments or {}).items())}}


def made_before(service, tool, arguments):
    """
    The asset this tool already made from these arguments, or None.

    Asked before the tool is: the same request is the same file, and paying
    for it twice would be paying for nothing.
    """
    wanted = request_of(service, tool, arguments)
    for asset in _model().objects.filter(origin=_model().TOOL,
                                         status="present"):
        if (asset.made_with or {}).get("request") == wanted:
            return asset
    return None


def from_tool(data, *, sponsor, service, tool, arguments, name, description,
              model="", settings_used=None, wanted=None):
    """
    Keep a file a tool made. Returns `(asset, said)`; raises `Refused`.

    Charged to the sponsor's payer -- whoever's key paid for the call, which
    in a shared world is its creator, whoever caused it -- and checked like
    any other file, by its contents. Its record says which service and tool
    made it, with which model and settings and from what request, so it can
    be credited, explained, and found again instead of made again.
    """
    payer = getattr(sponsor, "payer", None)
    actor = getattr(sponsor, "actor", None)
    added_by = getattr(actor, "account", None) or payer
    made_with = {"service": str(service), "tool": str(tool),
                 "request": request_of(service, tool, arguments)}
    if model:
        made_with["model"] = str(model)
    for key, value in sorted(dict(settings_used or {}).items()):
        made_with[str(key)] = value
    return add_bytes(data, name=name, description=description,
                     added_by=added_by, charged_to=payer,
                     origin=_model().TOOL, made_with=made_with, wanted=wanted)


# ---------------------------------------------------------------------------
# Lookups: what a model or an agent may read. docs/archived/assets.md 10
# ---------------------------------------------------------------------------

def lookup_tools():
    """
    `list_assets` and `show_asset`: the register, for a model to read.

    An asset is named by the start of its hash and described in words, never
    by a path or a URL: a model uses one by its id, and what it knows of one
    is its description, which is why every asset must have one.
    """
    from world import asset_types, toolbox as tb

    def entry(asset):
        return (f"{asset.hash[:12]} {asset.type} {asset.name!r} "
                f"({size_said(asset.size)}) -- {asset.description}")

    def listing(ctx, args):
        kind = str(args.get("type") or "").strip()
        found = search(kind or None, str(args.get("query") or ""))
        return tb.paged([entry(asset) for asset in found[:500]],
                        {**args, "query": ""}, "assets")

    def showing(ctx, args):
        said = str(args.get("id") or "").strip().lower()
        asset = _model().objects.filter(hash__startswith=said).first() \
            if len(said) >= 6 else None
        if asset is None:
            return "No asset has that id. list_assets gives each one's id."
        lines = [entry(asset), f"status {asset.status}"]
        if asset.author or asset.licence:
            lines.append(f"credit {asset.author or 'unknown'}; licence "
                         f"{asset.licence or 'not said'}")
        if asset.made_with:
            lines.append("made with " + ", ".join(
                f"{key} {value}" for key, value in sorted(asset.made_with.items())
                if key != "request"))
        return "\n".join(lines)

    kinds = sorted(asset_types.every())
    return [
        tb.Tool("list_assets",
                "Files this game keeps -- world documents now, sounds and "
                "images later -- each with its id, type and description.",
                tb.params({**tb.PAGE, "type": {
                    "type": "string", "enum": kinds,
                    "description": "Optional. Only assets of this type"}}),
                tb.answering(listing), doing="looking through the assets",
                looks=True),
        tb.Tool("show_asset", "One asset in full: what it is, its credit, "
                              "and how it was made.",
                tb.params({"id": {"type": "string",
                                  "description": "Its id, as list_assets "
                                                 "gives it"}}, ["id"]),
                tb.answering(showing), doing="reading about an asset",
                looks=True),
    ]


# ---------------------------------------------------------------------------
# Reading one
# ---------------------------------------------------------------------------

def find(hash_):
    """The asset with this hash, or None."""
    return _model().objects.filter(hash=str(hash_ or "")).first()


def extension_of(asset):
    from world import asset_types

    found = asset_types.get(asset.type)
    return found.extension if found is not None else ""


def opened(asset):
    """The asset's file, open for reading in binary."""
    from world import asset_store

    return asset_store.store().open(asset.hash, extension_of(asset))


def public_url(asset):
    """
    Where somebody outside this server fetches it, or "" while
    `ASSET_BASE_URL` is unset: a server cannot work out its own address.
    """
    from world import asset_store

    base = str(getattr(settings, "ASSET_BASE_URL", "") or "").rstrip("/")
    if not base:
        return ""
    return base + asset_store.store().url(asset.hash, extension_of(asset))
