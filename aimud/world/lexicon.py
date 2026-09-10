"""
What English already knows about a word.

Almost everything this game knows, it paid a model to tell it. That is the
right trade for anything about *this* world -- what is in the room, what the
innkeeper wants, whether the chest here is a box or a ribcage. It is a poor
trade for facts that were settled long before the world existed: that "held"
is the past tense of "hold", that "quickly" can only ever be an adverb, that
a satchel is a kind of container. English has already been written down. This
module reads it.

The distinction that keeps this useful rather than dangerous:

* **A lexicon is asked what a word CAN be.** How it inflects, which parts of
  speech it may take, which senses exist, what each sense is a kind of. These
  are closed questions with published answers, and they cost microseconds.

* **A lexicon is never asked what a word MEANS HERE.** Which sense was
  intended is a fact about the room, and WordNet orders its senses by how
  often they turned up in a 1990s newspaper corpus. Asked cold, it will tell
  you that a board is a committee, a chest is a ribcage, a bolt is lightning
  and a crane is an American novelist. The generators can see the room and
  are already being called; they choose the sense, and `senses()` exists to
  hand them the list to choose *from*.

So WordNet is a controlled vocabulary the world selects from, not an oracle
it queries. What that buys is a closed set of names for kinds: a thing filed
under `chest.n.02` in one zone and another filed the same way an hour later
agree, where two free-written strings would drift through "chest", "wooden
chest", "storage chest" and "coffer". Kinds feed cache keys, and a cache key
that drifts does not degrade -- it silently stops matching and re-spends
every call the cache was built to save.

**Nothing here is load-bearing.** WordNet is an 11MB download and worlds have
to keep working without it: a server behind a firewall, a fresh checkout, a
corpus that failed to unzip. Every function below answers neutrally when the
corpus is missing -- no lemma, no senses, nothing is an adverb, nothing is
ambiguous -- and every caller is written so that the neutral answer is the
behaviour the game had before this module existed. A missing dictionary makes
the world slightly clumsier. It must never make the world impossible.
"""

import os
import threading

from evennia.utils import logger

#: The vendored corpus, alongside the source rather than in the player's
#: `server/` directory -- that holds their database and their API key, which
#: are theirs, while this is a fixed part of the game like any other module.
_VENDORED = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "nltk_data",
)

#: Resolved once. `None` means "not looked yet"; `False` means "looked, and
#: there is no corpus" -- which is a normal state to be in and not an error to
#: report twice.
_WORDNET = None

#: NLTK's corpus reader builds its indices on first access and is not written
#: to survive two threads arriving at once. Evennia runs commands on a
#: threadpool, so the first two players to type anything would race. `warm()`
#: at startup is the real fix; this makes the race harmless if anything slips
#: in before it.
_LOCK = threading.Lock()


def _wordnet():
    """The corpus reader, or None if this installation has no WordNet."""
    global _WORDNET
    if _WORDNET is not None:
        return _WORDNET or None

    with _LOCK:
        if _WORDNET is not None:
            return _WORDNET or None
        try:
            import nltk
            from nltk.corpus import wordnet

            if _VENDORED not in nltk.data.path:
                nltk.data.path.insert(0, _VENDORED)
            # Force the lazy loader to resolve now, inside the lock, so that
            # the failure (if any) happens here rather than in whichever
            # command happened to be first.
            wordnet.synsets("cup")
            _WORDNET = wordnet
        except Exception as err:
            logger.log_info(
                f"WordNet unavailable ({err}); running without it. Word "
                f"endings, kinds and senses will be guessed rather than "
                f"looked up."
            )
            _WORDNET = False
    return _WORDNET or None


def warm():
    """
    Load the corpus before anybody needs it.

    Called from server startup. The first query costs about a second and a
    half while the indices are built, and that second and a half should be
    spent while the server is starting rather than inside the first command
    somebody types.

    The causation index is built here too, for the same reason and out of the
    same pass: it walks every verb synset once, and doing that inside whichever
    command first wanted a planner hint would be a visible pause for nothing.
    """
    ready = _wordnet() is not None
    if ready:
        _caused_by()
    return ready


def available():
    """Whether there is a dictionary to consult at all."""
    return _wordnet() is not None


# ---------------------------------------------------------------------------
# What a word can be
# ---------------------------------------------------------------------------

def parts_of_speech(word):
    """
    Every part of speech a word can take: a subset of {n, v, a, s, r}.

    "a" and "s" are both adjectives -- WordNet separates head adjectives from
    satellites, and nothing here cares which is which.
    """
    wordnet = _wordnet()
    if wordnet is None or not word:
        return frozenset()
    try:
        return frozenset(s.pos() for s in wordnet.synsets(word.lower()))
    except Exception:
        return frozenset()


def is_only_adverb(word):
    """
    Whether a word is an adverb and can be nothing else.

    The test is deliberately "only", never "can be". Plenty of ordinary nouns
    double as adverbs -- you can travel *light* -- and a check that merely
    asked whether an adverb reading existed would swallow the lamp along with
    the manner. Being wrong in that direction costs a player their noun; being
    wrong the other way leaves a stray word in a phrase, which the matcher
    already survives.

    This is what lets manner be stripped from a command without anybody
    writing down what the adverbs of English are. Around 3,200 words qualify
    and nine in ten of them end in -ly, but the list is WordNet's to keep.
    """
    return parts_of_speech(word) == frozenset("r")


def known(word):
    """
    Whether English has heard of this word at all.

    A useful third signal for `naming.py`, which currently has to tell a typo
    from an invention on spelling alone. A word nobody has ever written down,
    sitting one edit away from one that everybody has, is a slip. A word that
    is in the dictionary is more likely to be meant.

    Note what this cannot do: a world of its own invention is full of real
    words WordNet has never seen -- mithril, datapad, greatsword. So absence
    is evidence of a typo and never proof of one, and this is read alongside
    the edit distance rather than instead of it.
    """
    wordnet = _wordnet()
    if wordnet is None or not word:
        return False
    try:
        return bool(wordnet.synsets(word.lower()))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# What a word reduces to
# ---------------------------------------------------------------------------

def lemma(word, pos=None):
    """
    A word reduced to its dictionary form, or the word itself if unknown.

    "knives" is a knife, "mice" are mice, "held" is hold, "lit" is light, and
    none of that follows from a suffix table -- which is what `anatomy.py` had
    to write by hand and what every hand-written singulariser gets wrong at
    about the same place.

    Returns the word unchanged rather than None when there is no answer, so a
    caller can always use the result. That also makes a missing corpus
    invisible: without WordNet everything is already in its dictionary form,
    which is exactly what the game assumed before this module existed.

    `pos` is "n" or "v" where the caller knows which it wants. Given neither,
    nouns are tried first: this is mostly called on things.

    NLTK's `morphy` is deliberately not used, and the reason is worth writing
    down because the failure is quiet. It hands back the first candidate, and
    a plural that is *itself* a dictionary headword is its own first
    candidate: "hands", "eyes", "teeth", "boards" and "glasses" all come back
    untouched, while "knives" and "cups" reduce properly. A singulariser that
    works on the hard words and fails on the easy ones is worse than none,
    because nothing about it looks broken.

    The full candidate list has what is wanted -- "hands" offers ['hands',
    'hand'] -- so the shortest is taken, and where two are the same length the
    later one wins: "teeth" offers ['teeth', 'tooth'] and only the tie-break
    separates them. Shortest also settles "leaves", which offers a leaf and a
    leaving and means the leaf.
    """
    wordnet = _wordnet()
    word = (word or "").lower().strip()
    if wordnet is None or not word:
        return word
    try:
        for tag in ([pos] if pos else ["n", "v"]):
            found = wordnet._morphy(word, tag)
            if found:
                return min(
                    ((len(w), -i, w) for i, w in enumerate(found))
                )[2]
    except Exception:
        pass
    return word


# ---------------------------------------------------------------------------
# What a thing is a kind of
# ---------------------------------------------------------------------------

#: Ancestors worth noticing, and what each implies about a thing filed under
#: it. Deliberately short: these are the buckets that decide whether the game
#: has to ask which sense was meant, not a replacement for the affordances a
#: generator writes. A chest that is a box and a chest that is a ribcage fall
#: in different buckets, which is the whole point; the eleven senses of "book"
#: that between them name one readable thing and ten abstractions do not, and
#: cost nothing to leave alone.
KIND_BUCKETS = {
    "container.n.01": "container",
    "publication.n.01": "readable",
    "furniture.n.01": "surface",
    "clothing.n.01": "wearable",
    "weapon.n.01": "wieldable",
    "food.n.01": "edible",
    "body_part.n.01": "bodypart",
    "person.n.01": "person",
    "structure.n.01": "structure",
    "device.n.01": "device",
    "implement.n.01": "implement",
}


def _synset(name):
    wordnet = _wordnet()
    if wordnet is None or not name:
        return None
    try:
        return wordnet.synset(name)
    except Exception:
        return None


def ancestors(sense):
    """
    Every synset a sense descends from, by name.

    `sense` is a WordNet id like "chest.n.02". The closure rather than the
    single parent, because what is worth knowing sits at different depths:
    a bottle is a container four steps up, a sword is a weapon in two.
    """
    synset = _synset(sense)
    if synset is None:
        return frozenset()
    try:
        return frozenset(
            node.name() for path in synset.hypernym_paths() for node in path
        )
    except Exception:
        return frozenset()


def buckets(sense):
    """Which of the KIND_BUCKETS a sense falls into."""
    names = ancestors(sense)
    return frozenset(
        bucket for name, bucket in KIND_BUCKETS.items() if name in names
    )


def word_of(sense):
    """
    The plain word a sense is about: "chest.n.02" -> "chest".

    A synset id is written for a machine but it carries its own lemma, which
    is the one part of it meant for a person -- and a person is who asks, since
    this exists for `help chest` rather than for anything the game decides. No
    corpus needed, and a bare noun (which is what a kind is when WordNet has
    never heard of it) comes back as itself.
    """
    name = str(sense or "").strip().lower()
    if not name:
        return ""
    return name.split(".")[0].replace("_", " ")


def definition(sense):
    """
    What WordNet says a sense is, or "" when there is no corpus.

    The gloss, which is the sentence that tells a box from a ribcage. Only ever
    shown to a player: nothing in the game decides anything by it, which is the
    rule this module keeps -- a lexicon is asked what a word can be, never what
    it means here.
    """
    synset = _synset(sense)
    if synset is None:
        return ""
    try:
        return synset.definition() or ""
    except Exception:
        return ""


def senses(word, pos="n", limit=12):
    """
    The senses a word has, as [(id, definition)], for a model to choose from.

    This is the only function here written to be put in a prompt, and the
    only one whose answer the game does not act on by itself. A generator that
    can see the room picks one; that choice is a fact about the object and is
    stored on it, never against the word -- a world can hold a chest you open
    and a chest you bruise at the same time, and both are right.
    """
    wordnet = _wordnet()
    word = lemma(word, pos)
    if wordnet is None or not word:
        return []
    try:
        found = wordnet.synsets(word, pos=pos)[:limit]
        return [(s.name(), s.definition()) for s in found]
    except Exception:
        return []


def settled_noun_sense(word):
    """
    The sense a noun can be ground in without asking anybody, or "".

    The counterpart of `needs_sense_choice`, and it follows from it. That
    function's whole argument is that most ambiguity does not matter for
    deciding what *sort of thing* something is: "book" has eleven senses and
    ten of them are abstractions that "say nothing about what sort of object is
    being made, so any of them would answer the same". If any of them would
    answer the same, the first will do, and nobody needs to be asked.

    So this is deliberately the frequency-ordered first sense -- the thing
    `lexicon.py` warns against everywhere else -- and it is safe here for
    exactly one reason: it is only reached for words whose senses do not
    disagree about the answer being asked for. A word whose senses do disagree
    goes to `sense_prompt` and a generator that can see the room.

    Empty for a word with no senses at all, which is the case an anchor is for.
    """
    if not word or needs_sense_choice(word):
        return ""
    listed = senses(word, pos="n", limit=1)
    return listed[0][0] if listed else ""


def needs_sense_choice(word):
    """
    Whether a word's senses disagree about what kind of thing it is.

    Most ambiguity is not worth a question. "Book" has eleven senses, and ten
    of them are abstractions that say nothing about what sort of object is
    being made, so any of them would answer the same. "Chest" has four and
    they straddle `container` and `bodypart`, which decides whether the thing
    has a lid or a ribcage.

    Only about one multi-sense noun in sixteen crosses a bucket this way, so
    this is what keeps sense selection from being a tax on every object made:
    a sword, a door, a bottle, a book and a lantern are never asked about, and
    a chest, a board, a bar, a trunk, a lamp and a crane always are. "Cup" is
    asked about too, on the strength of a sense meaning punch served from a
    pitcher -- which is the cost of drawing the line mechanically, and cheaper
    than the ribcage with a lid that comes of not drawing it at all.
    """
    wordnet = _wordnet()
    word = lemma(word, "n")
    if wordnet is None or not word:
        return False
    try:
        found = wordnet.synsets(word, pos="n")
    except Exception:
        return False
    if len(found) < 2:
        return False
    seen = {buckets(s.name()) for s in found}
    return len({b for b in seen if b}) > 1


#: What a bucket is worth in the vocabulary the generators already use. Only
#: the buckets that answer to an affordance appear: `bodypart`, `person` and
#: `structure` say something true and say it about what a thing IS, which is
#: what `kind` records. This is for what can be DONE with it.
_BUCKET_AFFORDANCES = {
    "container": "container",
    "readable": "readable",
    "surface": "surface",
    "wearable": "wearable",
    "wieldable": "wieldable",
    "edible": "edible",
}


def implied_affordances(sense):
    """
    What being this kind of thing already implies, before anybody is asked.

    A thing filed under `chest.n.02` is a box, and a box is a container, and
    a container is something things go in -- and none of that needed a model,
    because it is true of every chest that ever was. Handed to the generator's
    own list as a floor rather than a ceiling: a model that says a chest is
    also lockable and flammable is telling us something this cannot.

    The value is steadiness rather than savings. `verbs.signature()` keys the
    rule cache on affordances, so a chest that came back "container" one day
    and "storage" the next quietly splits every rule ever learned about it
    into two. Anything the taxonomy can pin down is one less thing that can
    drift.
    """
    return implied_by(ancestors(sense))


def implied_by(senses):
    """
    The same, for a chain of senses somebody else worked out.

    `world.kinds` follows an invented noun's anchor to get its ancestry, so it
    arrives holding the senses rather than a name to look them up from. This
    keeps the bucket tables in here, where they are defined, rather than having
    another module reach in for them.
    """
    names = frozenset(senses or ())
    return frozenset(
        _BUCKET_AFFORDANCES[bucket]
        for name, bucket in KIND_BUCKETS.items()
        if name in names and bucket in _BUCKET_AFFORDANCES
    )


def sense_prompt(phrase):
    """
    A block asking a model which sense of a word it means, or "" for most.

    Returned empty unless the head noun's senses actually disagree about what
    kind of thing it is, which is about one multi-sense noun in sixteen. A
    sword, a door and a bottle are never asked about and cost nothing; a
    chest, a board, a bar and a crane are asked about every time, because
    getting those wrong is how a ribcage ends up with a lid.

    Asked of the model rather than answered here on purpose. WordNet orders
    its senses by how often they appeared in a newspaper corpus, so left to
    itself it reports that a board is a committee and a crane is an American
    novelist. Which one is meant is a fact about the room, and the room is
    what the generator can see.
    """
    word = head_noun(phrase)
    if not word or not needs_sense_choice(word):
        return ""
    listed = "\n".join(f"  {name} -- {definition}"
                       for name, definition in senses(word))
    if not listed:
        return ""
    return (
        f'"{word}" means several different kinds of thing. Set "sense" to '
        f"whichever of these this one actually is, given the room:\n"
        f"{listed}\n"
        f"Copy the identifier exactly. If none of them fits what you are "
        f'making, set "sense" to "".\n'
    )


def head_noun(name):
    """
    The word a name is *of*, singularised.

    Last word, because English noun phrases are head-final and the generators
    write in exactly that register: a Slate Chalkboard is a board, a Cardboard
    Nametag is a nametag. Worth saying plainly that a dictionary cannot
    improve on this -- in "Blue Ceramic Cup" every single word is a noun as
    far as WordNet is concerned, blue and ceramic included, because English
    makes modifiers out of nouns all day. Position knows; vocabulary does not.
    """
    import re

    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    if not words:
        return ""

    # "Of" turns a phrase around, and which way depends on the first word.
    # A bottle of soju is a bottle -- it is the bottle you pick up, and the
    # soju is what happens to be in it. But a pair of boots is boots and a
    # piece of chalk is chalk, because those first words are measures rather
    # than things: nobody owns a pair.
    #
    # Left unhandled, "bottle of soju" came out as a kind called "soju",
    # which matched no object in a world full of bottles -- so a character
    # who wanted one could never be given one, and never stop looking.
    if "of" in words[1:-1]:
        at = words.index("of", 1)
        before, after = words[:at], words[at + 1:]
        chosen = after if before[-1] in _MEASURES else before
        words = chosen or words

    return lemma(words[-1], "n")


#: Words that count a thing rather than being one. "A pair of boots" is boots;
#: "a bottle of soju" is a bottle, because a bottle is something in its own
#: right and a pair is not. Deliberately short and uncontroversial: anything
#: arguable -- a glass of water, a cup of tea -- is left as the container,
#: which is the thing you can actually pick up.
_MEASURES = frozenset("""
    piece bit lump chunk slice sliver shred scrap pair set pile heap
    handful bunch stack sheet length strand speck grain
""".split())


# ---------------------------------------------------------------------------
# What a verb is a way of doing
# ---------------------------------------------------------------------------

def _verb_synsets(word, spread=2):
    """
    The senses a verb reference names: exact for an id, guessed for a word.

    Everything below reads verb relations, and every one of them is only as
    right as the sense it starts from. Given `launch.v.03` there is nothing to
    guess. Given `launch` there is, and the guess is wrong often enough to
    matter -- WordNet orders senses by how often they turned up in a 1990s
    newspaper corpus, so the first sense of `launch` is `establish.v.01`, "set
    up or found", and everything read from it is about founding institutions.

    So the guess is narrow by default and every caller is written to prefer a
    recorded id. `world.actions` records one per verb for exactly this reason.

    How wide the guess may safely be depends on how common the relation is,
    which is why `spread` is a parameter rather than a constant:

        95.9% of verb synsets have a hypernym    -- dense
         2.8% have an entailment                 -- sparse
         1.6% have a cause                       -- very sparse

    A dense relation is reachable from any sense, so a wide guess mostly finds
    answers about the wrong sense: that is the `launch` -> `establish` ->
    `open` road. A sparse one is different -- when 1.6% of senses have a cause
    at all, a sense that has one is telling us something, and looking past the
    first two costs almost no risk of finding the wrong thing. Measured: a
    spread of four recovers `ring` -> `sound` and `break` -> `break`, and
    anything beyond four adds nothing at all.
    """
    wordnet = _wordnet()
    if wordnet is None or not word:
        return []
    word = str(word).strip()
    exact = _synset(word)
    if exact is not None:
        return [exact]
    try:
        return wordnet.synsets(lemma(word, "v"), pos="v")[:spread]
    except Exception:
        return []


def _related_verbs(word, relation, limit, keep_self=False, spread=2):
    """
    Words reached from `word` by a verb-to-verb relation, nearest first.

    `keep_self` decides what happens when the relation leads back to the same
    word, and the two answers are both right for different relations. Nothing
    is served by reporting that opening is a way of opening, so an ancestor
    that spells the same is dropped. But `open` *causing* `open` is the
    causative pair -- the transitive verb beside the intransitive change it
    produces -- and that is the single most useful thing this file can say
    about a verb, so `causes` keeps it.
    """
    out = []
    for synset in _verb_synsets(word, spread):
        try:
            found = getattr(synset, relation)()
        except Exception:
            continue
        for other in found:
            said = word_of(other.name())
            if said in out:
                continue
            if not keep_self and said == word_of(word):
                continue
            out.append(said)
    return out[:limit]


def verb_ancestors(verb, limit=3):
    """
    The verbs a verb is a way of performing, nearest first.

    Prying is a way of opening; dousing is a way of snuffing out. A world that
    has already learned what `open` does knows something real about `pry`
    before anybody defines it, and that is worth handing to the rule writer as
    a starting point.

    A starting point and not an answer. Troponymy says pry is a kind of
    opening; it does not say that prying wants a crowbar, and a rule that
    inherited `open` wholesale would quietly lose the instrument. The caller
    puts this in a prompt beside the learned rule, never in place of it.

    `verb` may be a recorded sense id, and should be wherever one is known.
    Handed the bare word `launch` this answers `['open', 'propel']` -- `open`
    because the commonest sense of launching is founding something, whose
    hypernym is `open.v.02`. That is the world's `open` rule offered as the
    starting point for writing `launch`, for a spacecraft. Handed
    `launch.v.03` it answers about launching.
    """
    return _related_verbs(verb, "hypernyms", limit)


def entailments(verb, limit=3):
    """
    The verbs doing this one necessarily involves.

    Snoring entails sleeping; soaping entails washing. Which makes it the one
    verb relation that transfers a *precondition* soundly: if A cannot happen
    without B, then whatever B requires, A requires. 408 pairs in all of
    WordNet, and sense-disambiguated, so it is small and precise rather than
    broad -- 17% of the verbs the exported worlds learned have one.
    """
    return _related_verbs(verb, "entailments", limit, spread=4)


def causes(verb, limit=3):
    """
    The verbs this one brings about.

    Only 220 pairs exist, and among the verbs these worlds actually learn they
    are almost all one thing -- the causative pair, a transitive verb beside
    the intransitive change it produces:

        open  causes open.v.03      kill causes die.v.01
        fill  causes fill.v.02      dry  causes dry.v.02

    Which is the link this game has needed and never had: the verb a player
    types, joined to the condition it leaves behind. `world.affordances`
    already observes that "burn and burning are one idea correctly split
    across two registers"; nothing anywhere computed it. This does, for a
    tenth of every verb a world learns, for nothing.

    Read the other way it answers a different and equally useful question --
    which verbs would bring a condition about -- and there it is deliberately
    many-to-one. See docs/rulebooks-from-inform.md 5.1 for why that makes it a
    planner's index and emphatically not a test of whether two verbs are the
    same word.
    """
    return _related_verbs(verb, "causes", limit, keep_self=True,
                          spread=4)


#: The whole causation relation, inverted, built once and kept.
#:
#: None until somebody asks. WordNet holds about 220 `causes` pairs in total, so
#: inverted it is a dict of a couple of hundred entries -- small enough to hold
#: and far too small to be worth storing on disk. What it costs is one pass over
#: the verb synsets, which `warm()` already pays for at startup.
_CAUSED_BY = None


def causing(word, limit=3):
    """
    The verbs that would bring `word` about, nearest first.

    `causes` read backwards, and the direction that is actually useful to a
    planner: to make something descend, drop it or lower it or fell it. The spec
    is emphatic that this is **not** a test of whether two verbs are the same
    word -- dropping and felling are not synonyms and nothing here claims they
    are. It is a list of candidates for a world that has no rule about descending
    and might be taught one.

    Deliberately many-to-one. A condition has several ways to be brought about,
    and that is the point: a caller takes the first that suits and the rest are
    there when it does not.
    """
    wanted = word_of(str(word or "")) if word else ""
    if not wanted:
        return []
    return list(_caused_by().get(wanted) or [])[:limit]


def _caused_by():
    """The inverted index, built on first use."""
    global _CAUSED_BY
    if _CAUSED_BY is not None:
        return _CAUSED_BY

    wordnet = _wordnet()
    with _LOCK:
        if _CAUSED_BY is not None:
            return _CAUSED_BY
        index = {}
        if wordnet is not None:
            try:
                for synset in wordnet.all_synsets("v"):
                    causer = word_of(synset.name())
                    for caused in synset.causes():
                        said = word_of(caused.name())
                        # A verb that causes itself is the causative pair, and
                        # it is no use as a candidate: a world with no way to
                        # make something open does not need to be told to open
                        # it, it needs the rule it has not got.
                        if not said or said == causer:
                            continue
                        entry = index.setdefault(said, [])
                        if causer not in entry:
                            entry.append(causer)
            except Exception as err:
                logger.log_info(f"causation index unavailable ({err})")
        _CAUSED_BY = index
    return _CAUSED_BY


def verb_senses(verb, limit=5):
    """
    The senses a verb has, as [(id, definition)], for a model to choose from.

    Capped, because verbs are far more polysemous than nouns: the verbs these
    worlds learned have a median of six senses and a third have ten or more --
    `break` has 59. The noun trick of asking only when senses straddle a kind
    bucket does not transfer, since nearly every verb would qualify. WordNet
    orders by corpus frequency, so the answer is almost always among the first
    few, and five short glosses once per verb per world is a rounding error.
    """
    return senses(verb, pos="v", limit=limit)


def verb_sense_prompt(verb):
    """
    A block asking a model which sense of a verb it means, or "" without one.

    Unlike the noun version this is offered for nearly every verb rather than
    for the ambiguous few, because 98 of the 100 verbs the exported worlds
    learned have a WordNet sense and most of those have several. The two that do
    not are an adverb the old parser mistook for a verb and a misspelling, which
    is its own small argument for asking.

    Empty for a verb with one sense or none, because a menu of one is not a
    question -- and one is not rare: `power`, `airlock` and `blaster` all have
    exactly one. `settled_sense` is what a caller uses in that case.
    """
    listed = verb_senses(verb)
    if len(listed) < 2:
        return ""          # nothing to choose; see `settled_sense`
    lines = "\n".join(f"  {name} -- {definition}"
                      for name, definition in listed)
    return (
        f'"{verb}" has more than one meaning. Set "sense" to whichever of '
        f"these this world means by it, given what is going on:\n{lines}\n"
        f"Copy the identifier exactly. If none of them fits, leave "
        f'"sense" empty and say what it means in your own words instead.\n'
    )


def settled_sense(verb):
    """
    The verb's sense when there is only one, so nobody need be asked.

    Paired with `verb_sense_prompt`, which is empty in exactly this case. A
    verb with one sense has already been disambiguated by English.
    """
    listed = verb_senses(verb, limit=2)
    return listed[0][0] if len(listed) == 1 else ""

def anchor_prompt(phrase):
    """
    A block asking what sort of thing an invented noun is, or "" for a real one.

    The awkward case, and the reason it needs its own function: a noun WordNet
    has never heard of has no senses to choose between, so there is no menu of
    *its* meanings to offer. What can be offered is the small closed set of
    senses the taxonomy actually reads -- `KIND_BUCKETS`, which is what a floor
    is computed from -- plus leave to name something more precise, since an
    answer is checked against the dictionary before it is believed either way.

    Coarse on purpose. A datapad and a holodeck both landing under
    `device.n.01` is not a loss: each is still its own kind, with its own
    affordances and its own rules, and the anchor exists only so that they have
    a taxonomy above them at all -- a floor to inherit, a hypernym a rule can
    be filed against, and something for `prune` to recognise.
    """
    word = head_noun(phrase)
    if not word or ancestors(word) or settled_noun_sense(word):
        return ""
    if needs_sense_choice(word):
        return ""              # it has senses; `sense_prompt` is asking
    listed = "\n".join(
        f"  {name} -- {definition(name)}" for name in sorted(KIND_BUCKETS))
    return (
        f'"{word}" is not a word the dictionary knows, so nothing is known '
        f"about what sort of thing it is. Set \"under\" to whichever of these "
        f"it most nearly is:\n{listed}\n"
        f"A more precise sense is welcome if you know one -- any WordNet "
        f"identifier will do, and one that does not exist is ignored. Copy it "
        f"exactly.\n"
    )
