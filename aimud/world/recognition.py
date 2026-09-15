"""
Who somebody meant, read back out of what they said.

The reverse of rendering. `world.tokens` turns what is known into words;
this turns words back into what is known, for the one place the game hears
names it never bound: speech and poses. "Hello, Raldor." is about Raldor, and
said to him, and a memory of it that knows so can be found by asking about
Raldor. See docs/tokens-and-phrases.md, phase 5.

**Conservative, because recall trusts what it is handed.** A mention written
here becomes an annotation, and an annotation is what a later cue matches
against. A false one is worse than a missed one, so:

* **Only who could be meant.** The room's contents and the people the speaker
  was last told about -- never the whole world, where every common word is
  somebody's name.
* **Exact words, never fuzzy.** `naming.resemblance` is right for a command,
  where the player is reaching for a thing in front of them. Speech is not
  reaching for anything.
* **A name that is also a word needs a capital.** An NPC called Hope is not
  mentioned by "I hope so", and at the start of a sentence -- where everything
  has a capital -- only when the name is set off as somebody being spoken to.
* **Two people answering to one word are neither.** "Tam, over here" in a room
  with two Tams names nobody.

**Addressed is not the same as mentioned.** "Hello, Raldor." is said to him;
"I think Raldor took it." is said about him, to somebody else. The difference
is punctuation -- a name that opens or closes an utterance and is set off by a
comma, "!" or "?" -- and it is what an NPC deciding whether to answer wants.

**Confidence is what the annotation carries.** 1.0 is a role the parser
bound, and nothing found in speech is that sure.
"""

import re
from collections import namedtuple

#: One person or thing a piece of speech named. `start` and `end` are where,
#: or -1 for somebody the command itself named -- a whisper's listener.
Mention = namedtuple("Mention", "ref name start end addressed confidence")

#: Named by the command rather than found in the words.
BOUND = 1.0

#: A name or an alias, whole.
FULL_NAME = 0.8

#: One word of a person's name: "Barnaby" for Barnaby Royston.
PART_NAME = 0.6

#: A name that is also an ordinary word, used as one: "Hope, come here."
COMMON_WORD = 0.5

#: What may surround a name, and still leave it the end of an utterance.
_TRAILING = " \t\"'”’.!?)"


def recognise(text, speaker=None, room=None, targets=()):
    """
    Everybody and everything `text` names, best confidence each, as Mentions.

    `targets` are whoever the command named -- a whisper's listeners -- and are
    addressed whatever the words say. The speaker is never a mention: somebody
    posing "Aria bows" has not named anybody else.
    """
    found = {}
    for obj in targets or ():
        if obj is None or obj is speaker:
            continue
        _keep(found, Mention(obj, _key(obj), -1, -1, _is_person(obj), BOUND))

    text = str(text or "")
    if not text.strip() or room is None:
        return list(found.values())

    world_root = getattr(getattr(room, "db", None), "world_root", None)
    entries = sorted(
        ((name, obj, confidence)
         for obj in candidates(speaker, room)
         for name, confidence in names_of(obj, world_root)),
        key=lambda entry: -len(entry[0]))

    claims = {}
    for name, obj, confidence in entries:
        pattern = re.compile(r"(?<![\w'])" + re.escape(name) + r"(?![\w'])",
                             re.IGNORECASE)
        for match in pattern.finditer(text):
            span = match.span()
            if span not in claims and any(start < span[1] and span[0] < end
                                          for start, end in claims):
                continue          # inside a longer name already found
            sure = confidence
            if _is_person(obj) and _common(name):
                if not match.group(0)[:1].isupper():
                    continue
                if _sentence_start(text, span[0]) and not addressed_at(text, *span):
                    continue
                sure = min(sure, COMMON_WORD)
            claim = claims.setdefault(span, {"refs": [], "confidence": sure})
            if sure > claim["confidence"]:
                claim["refs"], claim["confidence"] = [obj], sure
            elif sure == claim["confidence"] and obj not in claim["refs"]:
                claim["refs"].append(obj)

    for (start, end), claim in sorted(claims.items()):
        if len(claim["refs"]) != 1:
            continue              # two people answer to it; it names neither
        obj = claim["refs"][0]
        _keep(found, Mention(obj, _key(obj), start, end,
                             _is_person(obj) and addressed_at(text, start, end),
                             claim["confidence"]))
    return list(found.values())


def about(mentions):
    """Mentions as `memory.remember` takes them: (name, dbref, confidence)."""
    return [(mention.name, f"#{mention.ref.id}", mention.confidence)
            for mention in mentions or () if getattr(mention.ref, "id", None)]


def addressed(mentions):
    """The same, for only those spoken to."""
    return about([mention for mention in mentions or () if mention.addressed])


# ---------------------------------------------------------------------------
# Who could be meant, and what they answer to
# ---------------------------------------------------------------------------

def candidates(speaker, room):
    """
    Everybody and everything that could be meant: the room's contents, then
    the people the speaker was last told about. Never the speaker, never an
    exit, never something already gone.
    """
    found = []

    def add(obj):
        try:
            if (obj is None or obj is speaker or obj in found
                    or not getattr(obj, "id", None)
                    or getattr(obj, "destination", None) is not None):
                return
        except Exception:
            return
        found.append(obj)

    for obj in list(getattr(room, "contents", []) or []):
        add(obj)
    if speaker is not None:
        from world import referents

        table = referents._table(speaker)
        for obj in list(table.values()) + referents.told(speaker):
            if hasattr(obj, "key") and _is_person(obj):
                add(obj)
    return found


def names_of(obj, world_root=None):
    """
    [(name, confidence)] for everything `obj` answers to.

    Its key and its own aliases, whole; what it is called in this world; and
    for a person, each word of their name that is not a title -- the same rule
    an NPC already uses to notice it has been named, so "Sergeant Bram Ketch"
    answers to Bram and to Ketch and not to Sergeant.
    """
    from evennia.utils.ansi import strip_ansi

    found = {}

    def add(name, confidence):
        name = strip_ansi(str(name or "")).strip()
        if len(name) < 2:
            return
        kept = found.get(name.lower())
        if kept is None or confidence > kept[1]:
            found[name.lower()] = (name, confidence)

    add(getattr(obj, "key", ""), FULL_NAME)
    try:
        for alias, category in obj.aliases.all(return_key_and_category=True):
            if category is None:
                add(alias, FULL_NAME)
    except Exception:
        pass
    naming = getattr(obj, "world_name", None)
    if callable(naming) and world_root is not None:
        try:
            add(naming(world_root), FULL_NAME)
        except Exception:
            pass

    if _is_person(obj):
        from world.npc_gen import TITLES

        for word in re.findall(r"[\w']+", str(getattr(obj, "key", ""))):
            if len(word) > 2 and word.lower() not in TITLES:
                add(word, PART_NAME)
    return list(found.values())


# ---------------------------------------------------------------------------
# Reading punctuation
# ---------------------------------------------------------------------------

def addressed_at(text, start, end):
    """
    Whether the name at `text[start:end]` is somebody being spoken to.

    It is when it opens the utterance -- first, or after a greeting of a word
    or two and a comma -- and is followed by a comma, "!", "?" or nothing; or
    when it closes the utterance and is set off by a comma before it or "!" or
    "?" after. "Hello, Raldor." "Raldor, come here." "Is that you, Raldor?"
    "Thanks Raldor!" all are; "I think Raldor took it." is not.
    """
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    lead = before.lstrip(" \t\"'“‘")
    opens = not lead or (lead.endswith(",") and len(lead.split()) <= 2)
    # The end of its sentence is the end of an utterance: "Hello, Raldor. Is
    # the lamp lit?" is said to Raldor as much as "Hello, Raldor." is.
    closes = (not after.strip(_TRAILING)
              or after.lstrip(" \t\"'”’)")[:1] in (".", "!", "?"))
    if opens and (not after or after[0] in ",!?" or closes):
        return True
    return closes and (before.endswith(",") or after[:1] in ("!", "?"))


def _sentence_start(text, start):
    before = text[:start].rstrip(" \t\"'“‘")
    return not before or before[-1] in ".!?"


def _common(name):
    """A one-word name that is also a word English already has."""
    from world import lexicon

    name = str(name or "").strip()
    return " " not in name and lexicon.known(name.lower())


def _is_person(obj):
    from world.quests import is_person

    try:
        return bool(is_person(obj))
    except Exception:
        return False


def _key(obj):
    return str(getattr(obj, "key", "") or "")


def _keep(found, mention):
    """One Mention per thing: the surest, addressed if it ever was."""
    marker = id(mention.ref)
    kept = found.get(marker)
    if kept is None:
        found[marker] = mention
        return
    found[marker] = kept._replace(
        addressed=kept.addressed or mention.addressed,
        confidence=max(kept.confidence, mention.confidence))
