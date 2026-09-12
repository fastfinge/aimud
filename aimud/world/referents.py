"""
What "her" last meant.

A pronoun is a promise that both people already know who is being talked
about. Keeping that promise needs one small thing the game has never had: a
memory of what was last referred to, per person, per surface form.

Inform keeps exactly this and keeps it small -- one object each for `it`,
`him`, `her` and `them`, rewritten after every successful action. This is that
table. It is deliberately **not persistent**: it lives in `ndb`, so a reload
makes "get it" mean nothing rather than something from last week, which is the
right answer to a question nobody is still in the middle of asking.

**Keyed by the word, not by the set.** A player types "her", and two pronoun
sets in one world may legitimately share that form -- "she/her" and a declared
"ze/her" both answer to it. The table is about what was said, so it stores
what was said.

**Two directions, one table, and that is why this is one module.** The parser
asks it to resolve a pronoun somebody typed. The narrator will ask it whether
it may *use* one -- what this viewer was last told about, which is the same
question read backwards. The second half arrives in P4; what is here is the
first, plus the slot the second will write to.

Nothing here decides *which* candidate wins when several answer to a word.
That is `verbs.bind`'s business, because it depends on the verb being
attempted and on what is in reach, and neither is known here.
"""

#: Where the table hangs. In-memory by design; see the module docstring.
ATTR = "referents"

#: The slot the narrator writes and the parser never reads: the ranked
#: participants of the last message this viewer was shown. What
#: `events.centre` chooses the next sentence's pronoun from.
TOLD = "_told"

#: The last thing referred to at all, whatever word was used for it, and what
#: sort of thing it was.
#:
#: "all of them" is the case these exist for, and it is not answered by the
#: forms above: somebody who has just looked at one wrench and types "get all
#: of them" has never said "them" about anything. The plural is of the last
#: thing mentioned rather than of a plural referent, so the last thing is what
#: has to be kept.
LAST = "_last"
KIND = "_kind"


def _table(caller):
    if caller is None:
        return {}
    found = getattr(caller.ndb, ATTR, None)
    if not isinstance(found, dict):
        found = {}
        setattr(caller.ndb, ATTR, found)
    return found


def forms_of(obj, world_root=None):
    """
    The words a phrase could use to mean this object.

    A person answers to the object form of the set they go by -- "hug her",
    "greet him", "thank them" -- because that is the slot a typed command puts
    them in. A thing answers to "it", or to "them" when its name is plural,
    which is the whole of what number means for something that is not a
    person.
    """
    if obj is None:
        return set()

    from world.quests import is_person

    if is_person(obj):
        from world import pronouns

        entry = pronouns.of(obj, world_root)
        return {entry.get("object", ""), entry.get("subject", "")} - {""}

    return {"them"} if is_plural(obj) else {"it"}


def recall_by_set(caller, word, field, world_root=None):
    """
    The last person referred to by a set that uses `word` in `field`.

    "her sword" says whose by its ADJECTIVE, and the table is keyed by what a
    phrase calls somebody -- their object form. For she/her those are the same
    string and the question never arises; for he/him they are "his" and "him"
    and it does. So the word is read back to whichever sets use it that way,
    and their object forms are what the table is asked about.
    """
    from world import pronouns

    for entry in pronouns.by_form(world_root, word, field):
        found = recall(caller, entry.get("object", ""))
        if found is not None:
            return found
    return None


def is_plural(obj):
    """
    Whether a thing's name is plural: a pile of coins is "them".

    Asked of the dictionary rather than of a suffix rule, and answered "no"
    when there is no dictionary -- which is the neutral answer and the
    behaviour the game had before any of this. See `world.lexicon`.
    """
    from world import lexicon

    head = str(getattr(obj, "key", "")).split()[-1:] or [""]
    word = head[0].lower()
    if not word:
        return False
    return lexicon.lemma(word, "n") != word


def note(caller, obj, world_root=None, last=True):
    """
    Record that `obj` was just referred to, under every word that could mean it.

    Called after a successful bind rather than at each place a bind happens,
    so that there is one point at which the table can be wrong instead of
    several -- and by the narrator, for what a viewer was shown rather than
    what they typed, which is the same table because "hug her" after
    watching Jessica act means Jessica.

    `last=False` records the words and not the thing: the narrator passes it
    for the actor of a sentence, because somebody who watched Jessica pick
    up a wrench and types "get all of them" means wrenches, not Jessicas.
    """
    if caller is None or obj is None:
        return
    table = _table(caller)
    for form in forms_of(obj, world_root):
        table[form] = obj
    if not last:
        return

    from world import kinds

    table[LAST] = obj
    settled = kinds.of(obj)
    table[KIND] = settled[0] if settled else ""


def note_all(caller, bound, world_root=None):
    """
    Record a whole attempt's worth of bindings.

    The direct object last, so that it wins where two roles share a word: "put
    the lamp on the shelf" leaves "it" meaning the lamp, which is what somebody
    typing "now light it" means.
    """
    for role, obj in sorted((bound or {}).items(),
                            key=lambda pair: pair[0] == "direct"):
        note(caller, obj, world_root)


def recall(caller, form):
    """The last thing referred to by this word, or None."""
    return _table(caller).get(str(form or "").lower().strip())


def last(caller):
    """The last thing referred to, whatever it was called."""
    return _table(caller).get(LAST)


def last_kind(caller):
    """What the last bound object was a sort of, for "all of them"."""
    return _table(caller).get(KIND) or ""


def clear(caller):
    """Forget everything. For a character leaving a world, and for tests."""
    if caller is not None:
        setattr(caller.ndb, ATTR, {})


# ---------------------------------------------------------------------------
# The other direction: what the narrator has shown this viewer
# ---------------------------------------------------------------------------

def told(caller):
    """The ranked participants of the last message this viewer was shown."""
    return list(_table(caller).get(TOLD) or [])


def was_told(caller, participants):
    """
    Record what this viewer was just told, ranked.

    Written by `events.render` once per sentence per reader, and read by
    `events.centre` for the next one. Never written for the actor's own
    line, which is second person throughout and establishes no centre.
    """
    if caller is None:
        return
    _table(caller)[TOLD] = list(participants or [])
