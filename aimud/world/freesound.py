"""
Freesound: sounds other people recorded, found by searching for them.

`create sound freesound` searches freesound.org, plays a result, and keeps
one as a sound asset. What is kept is the high-quality Ogg preview, which any
key may fetch; the original file needs every player to sign in to Freesound,
and a game does not need a studio master to play a door creaking.

**A sound is kept only under a licence this server may use.** CC0 asks
nothing, and CC-BY asks for credit, which every kept sound carries in its
`author` and `licence` and so in every world exported with it. CC-BY-NC is
for servers that make no money, and is offered only where the server's owner
says theirs is one (`FREESOUND_NONCOMMERCIAL`). Sampling+ is never offered:
Freesound retired it, and what it permits is not something a game can check.
The licence is checked twice, in the search and again on every result, so a
filter Freesound reads differently one day cannot let one through.

**The key is the server's.** `FREESOUND_CLIENT_SECRET` in secret_settings.py,
sent as Freesound's token, never in an address that a log could keep. A
search costs nobody anything, so it is not a sponsor's.

Searching is blocking, like `assets.fetch`: run it in a thread.
"""

import html
import re

from django.conf import settings

#: Freesound's search.
SEARCH_URL = "https://freesound.org/apiv2/search/text/"

#: What a search asks for of each result.
FIELDS = "id,name,description,username,license,duration,url,tags,previews"

#: How many results one search shows.
PAGE_SIZE = 15

#: Seconds before a search is given up.
TIMEOUT = 20

#: The preview that is kept: Ogg Vorbis, which every client here plays.
PREVIEW = "preview-hq-ogg"

#: The licences, as Freesound's search filter names them, with whether a
#: server that makes money may use them.
LICENCES = [("Creative Commons 0", True), ("Attribution", True),
            ("Attribution NonCommercial", False)]

#: The most a description taken from Freesound may be, in characters.
MOST_DESCRIPTION = 600


class Unavailable(Exception):
    """Why Freesound could not be searched, as a sentence."""


def key():
    return str(getattr(settings, "FREESOUND_CLIENT_SECRET", "") or "").strip()


def available():
    """Whether this server has a Freesound key."""
    return bool(key())


def noncommercial():
    """Whether this server's owner says it makes no money from anybody."""
    return bool(getattr(settings, "FREESOUND_NONCOMMERCIAL", False))


def licence_of(url):
    """
    `(label, commercial)` for a Creative Commons licence address, or None.

    None is a licence this server never keeps: Sampling+, or anything else
    Freesound might say one day.
    """
    said = str(url or "").lower()
    found = re.search(r"creativecommons\.org/publicdomain/zero/([\d.]+)", said)
    if found:
        return f"CC0 {found.group(1)}", True
    found = re.search(r"creativecommons\.org/licenses/(by|by-nc)/([\d.]+)",
                      said)
    if found:
        kind, version = found.groups()
        return (f"CC-BY {version}", True) if kind == "by" \
            else (f"CC-BY-NC {version}", False)
    return None


def allowed(url):
    """Whether a sound under this licence may be kept here."""
    found = licence_of(url)
    if found is None:
        return False
    return found[1] or noncommercial()


def refused(licence_text):
    """
    Why a file under this licence may not be brought to this server, or "".

    For a file another server kept: one in a world being imported, or a
    missing one fetched again. Only a licence this can read is refused --
    a Creative Commons non-commercial one, by its address or its name --
    since what a player typed as a licence ("my own", "public domain") is
    not something to guess at. A non-commercial licence is the sound's,
    and never the world's: the world is built, and only the file is left
    out. Files kept here before the server's owner changed their mind are
    not touched; `view asset` says so of them.
    """
    if noncommercial():
        return ""
    said = str(licence_text or "")
    found = re.search(r"creativecommons\.org/licenses/by-nc[\w-]*/", said,
                      flags=re.IGNORECASE) or re.search(
        r"\bCC[- ]?BY[- ]NC\b", said, flags=re.IGNORECASE)
    if not found:
        return ""
    return ("it is for non-commercial use only, and this server is not "
            "set up as a non-commercial one")


def allowed_said():
    """The licences this server keeps, for a player to read."""
    return "CC0, CC-BY and CC-BY-NC" if noncommercial() else "CC0 and CC-BY"


#: Words a search leaves out. Freesound finds only sounds every word of a
#: search is found in, and nobody tags a recording "on" or "a", so "rain on
#: a tent" finds nothing where "rain tent" finds a page of them.
LITTLE_WORDS = frozenset(
    "a an the on in of at to into onto with and or for from by under over "
    "near some".split())


def keywords(words):
    """`words` without the little ones, unless that leaves nothing."""
    said = str(words or "").split()
    kept = [word for word in said if word.lower() not in LITTLE_WORDS]
    return " ".join(kept or said)


def _filter(longest):
    names = " OR ".join(f'"{name}"' for name, commercial in LICENCES
                        if commercial or noncommercial())
    said = f"license:({names})"
    if longest:
        said += f" duration:[0 TO {float(longest):g}]"
    return said


def _plain(text):
    """A Freesound description, which is HTML, as plain words."""
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return " ".join(html.unescape(text).split())


def _name(text):
    """A file name as somebody would call the sound: no extension."""
    said = re.sub(r"\.(wav|flac|aiff?|mp3|ogg|m4a)$", "", str(text or ""),
                  flags=re.IGNORECASE)
    return " ".join(said.replace("_", " ").split())[:120]


def result_of(raw):
    """
    One search result, as this game keeps it in a draft, or None for one
    under a licence this server does not keep or with no preview.
    """
    if not allowed(raw.get("license")):
        return None
    preview = (raw.get("previews") or {}).get(PREVIEW)
    if not preview:
        return None
    label, _commercial = licence_of(raw.get("license"))
    title = str(raw.get("name") or "")
    description = _plain(raw.get("description"))
    if len(description) > MOST_DESCRIPTION:
        description = description[:MOST_DESCRIPTION].rsplit(" ", 1)[0] + "..."
    tags = [str(tag) for tag in raw.get("tags") or []][:12]
    if not description:
        description = _name(title) + (
            f", tagged {', '.join(tags)}" if tags else "") + "."
    return {"id": int(raw.get("id") or 0), "title": title,
            "name": _name(title) or f"freesound {raw.get('id')}",
            "description": description,
            "username": str(raw.get("username") or ""),
            "licence": label, "licence_url": str(raw.get("license") or ""),
            "seconds": round(float(raw.get("duration") or 0), 1),
            "page": str(raw.get("url") or ""), "preview": preview,
            "tags": tags}


def search(words, longest=None, page=1):
    """
    `(results, how many match)` for `words`. Blocking.

    Raises `Unavailable` when there is no key or Freesound will not answer.
    Results are already only those this server may keep.
    """
    import httpx

    if not available():
        raise Unavailable("this server has no Freesound key")
    words = keywords(words)
    if not words:
        raise Unavailable("there is nothing to search for")
    try:
        response = httpx.get(
            SEARCH_URL, timeout=TIMEOUT,
            headers={"Authorization": f"Token {key()}",
                     "User-Agent": "aimud"},
            params={"query": words, "filter": _filter(longest),
                    "fields": FIELDS, "page_size": PAGE_SIZE,
                    "page": max(1, int(page))})
    except httpx.TimeoutException:
        raise Unavailable(f"Freesound took longer than {TIMEOUT} seconds")
    except httpx.HTTPError:
        raise Unavailable("Freesound could not be reached")
    if response.status_code in (401, 403):
        raise Unavailable("Freesound refused this server's key")
    if response.status_code == 429:
        raise Unavailable("Freesound says this server has searched too "
                          "often; try again later")
    if response.status_code >= 400:
        raise Unavailable(f"Freesound answered {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise Unavailable("Freesound's answer could not be read")
    found = [result for result in map(result_of, body.get("results") or [])
             if result is not None]
    return found, int(body.get("count") or 0)


def credit(result):
    """
    Who to credit, the way CC-BY asks: the title, the author and where it is.

    It goes in the asset's `author`, which travels with every world the sound
    is used in, so the credit cannot be left behind by an export.
    """
    said = f"\"{result['title']}\" by {result['username']}"
    if result.get("page"):
        said += f", {result['page']}"
    return said[:200]


def licence(result):
    """The licence, as an asset records it: its name and its address."""
    return f"{result['licence']}, {result['licence_url']}"[:200]


def line(result):
    """A result, in one line: what it is, how long, whose, and its licence."""
    return (f"{result['name']} -- {result['seconds']:g} seconds, by "
            f"{result['username']}, {result['licence']}")
