"""
Recognising a thing somebody meant to name.

This world conjures what it is asked for: name something that is not here and,
if it is plausible, it becomes real. That is the best thing about it and also
its sharpest edge, because a typo is indistinguishable from an invention. Ask
to look at the "blackbaord" and you get a second blackboard, slightly
different from the first, standing next to it forever -- and it cost two model
calls to make the mess.

So before anything is conjured, what is already in reach gets a proper chance
to be what was meant. Two kinds of mistake need catching and they are not the
same kind of thing:

* **Slips of the finger.** "candel", "blackbaord", "lamnp". These are edit
  distance, and specifically Damerau-Levenshtein -- ordinary Levenshtein
  charges two edits for a transposition, which is the single commonest typo
  there is, and would rank "candel" no closer to "candle" than "candid".

* **Slips of the ear.** "kandle", "sissors", "flaer", "nite". No amount of
  edit distance helps: these are spelled the way they sound. They need the
  word reduced to how it is pronounced, which is what `phonetic` does.

Soundex, the obvious candidate, is not used. It keeps the first letter of the
word, so "kandle" and "candle" get different codes -- it fails the very case
that motivates having a phonetic pass at all. It was built to file surnames
and it collides wildly on everything else. What is here is Metaphone-shaped
instead: consonants folded onto the sound they make, vowels dropped except at
the front.

Neither measure is trusted far. A confident match is acted on; a merely
plausible one is offered back to the player rather than guessed at, because
looking at the wrong thing is a small annoyance and silently littering a world
with near-duplicates is not.
"""

import re

#: Good enough to act on without asking. Reached by an exact word, a
#: contained name, one plain typo, or a word that sounds the same.
CONFIDENT = 0.86

#: Worth mentioning rather than conjuring over. Below this, the player really
#: does seem to be naming something new.
PLAUSIBLE = 0.62

#: Words too short to judge. Among three-letter words a coincidence is likelier
#: than a typo -- "cup" and "cap" are different things, and so are "pot", "pit"
#: and "pat" -- so these must match exactly or not at all.
MIN_LENGTH = 4


# ---------------------------------------------------------------------------
# How a word sounds
# ---------------------------------------------------------------------------

_VOWELS = "aeiou"

#: Letter groups folded onto one sound, longest first so "sch" is seen before
#: "ch". Ordinary English spelling confusions, and nothing more clever: this
#: is not a pronunciation dictionary, it is a way for "kandle" and "candle" to
#: arrive at the same string.
_DIGRAPHS = (
    ("sch", "sk"), ("tch", "X"), ("tion", "Xn"), ("sion", "Xn"),
    ("ough", "f"), ("augh", "f"), ("ph", "f"), ("gh", ""), ("ck", "k"),
    ("sh", "X"), ("ch", "X"), ("th", "0"), ("wh", "w"), ("qu", "kw"),
    ("ce", "se"), ("ci", "si"), ("cy", "sy"), ("ge", "je"), ("gi", "ji"),
    ("gy", "jy"),
)

#: Silent starts. "knife" and "nife" are the same word said aloud.
_SILENT_STARTS = (("kn", "n"), ("gn", "n"), ("pn", "n"), ("wr", "r"),
                  ("ps", "s"), ("mb", "m"))

#: Single letters folded onto the sound they usually make.
_LETTERS = {"c": "k", "q": "k", "x": "ks", "z": "s", "v": "f", "y": "",
            "h": "", "w": ""}


def phonetic(word):
    """
    A word reduced to roughly how it is pronounced.

    Metaphone-shaped: letter groups folded onto their sound, then vowels
    dropped except a leading one, then runs of the same letter collapsed. Two
    words with the same code are spelled differently and said the same, which
    is what makes "kandle" findable as a candle.
    """
    word = re.sub(r"[^a-z]", "", (word or "").lower())
    if not word:
        return ""

    for start, replacement in _SILENT_STARTS:
        if word.startswith(start):
            word = replacement + word[len(start):]
            break

    for group, replacement in _DIGRAPHS:
        word = word.replace(group, replacement)

    first, rest = word[:1], word[1:]
    out = []
    for letter in rest:
        if letter in _VOWELS:
            continue          # vowels carry almost no information about a typo
        out.append(_LETTERS.get(letter, letter))

    # A leading vowel is kept: "apple" and "pple" are not the same word, and
    # the front of a word is where people make fewest mistakes.
    code = (first if first in _VOWELS else _LETTERS.get(first, first)) + "".join(out)
    return re.sub(r"(.)\1+", r"\1", code)


# ---------------------------------------------------------------------------
# How far apart two spellings are
# ---------------------------------------------------------------------------

def edit_distance(a, b):
    """
    Damerau-Levenshtein distance: edits, counting a swap of neighbours as one.

    The transposition case is the reason for using this rather than plain
    Levenshtein. "candel" for "candle" is one slip of two fingers, and
    charging it two edits puts it level with words that are genuinely
    different.
    """
    a, b = a or "", b or ""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)

    previous = list(range(len(b) + 1))
    before_previous = None
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(
                previous[j] + 1,                       # deletion
                current[j - 1] + 1,                    # insertion
                previous[j - 1] + (ca != cb),          # substitution
            )
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                current[j] = min(current[j], before_previous[j - 2] + 1)
        before_previous, previous = previous, current
    return previous[-1]


def edit_ratio(a, b):
    """Edit distance as a score from 0 to 1, against the longer word."""
    longest = max(len(a or ""), len(b or ""))
    if not longest:
        return 0.0
    return max(0.0, 1.0 - edit_distance(a, b) / longest)


# ---------------------------------------------------------------------------
# How well one phrase names another
# ---------------------------------------------------------------------------

_NOISE = frozenset(["the", "a", "an", "my", "your", "some", "that", "this",
                    "of"])


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w and w not in _NOISE]


def _word_score(word, other):
    """How well one word stands for another, typos and homophones included."""
    if word == other:
        return 1.0
    # Too short to forgive: "cup" and "cap" are both real things.
    if len(word) < MIN_LENGTH or len(other) < MIN_LENGTH:
        return 0.0
    # Naming a thing by part of one of its words: "board" for a chalkboard,
    # "lamp" for an oil-lamp. Not a mistake at all, and what Evennia's own
    # search already does, so this only keeps the two in agreement.
    if word in other or other in word:
        return 0.9
    if phonetic(word) == phonetic(other):
        return 0.95
    ratio = edit_ratio(word, other)
    shortest = min(len(word), len(other))
    if edit_distance(word, other) == 1:
        # One edit is usually a typo, but not always, and which kind of edit
        # it was says a good deal about which. A SUBSTITUTION is how one real
        # word becomes another -- lamp/lamb, boot/book, table/cable,
        # plate/plane -- so it has to be a long word before that is likelier
        # to be a slip than a different thing being named. An insertion or a
        # deletion is a dropped or doubled keystroke, and "ledgr" is not a
        # word anybody meant; those can be forgiven a letter sooner.
        dropped_or_doubled = len(word) != len(other)
        if shortest >= 6 or (dropped_or_doubled and shortest >= 5):
            return max(ratio, 0.9)
    return ratio


def resemblance(phrase, key):
    """
    How well `phrase` names something called `key`, from 0 to 1.

    Built for object names, which here are several words long and title-cased
    ("Dried-Out Marker", "Slate Chalkboard"), so it works word by word and
    weighs the head noun highest: a Slate Chalkboard is a board, while a
    Cardboard Nametag is a nametag, however alike the strings look.
    """
    phrase_words, key_words = _words(phrase), _words(key)
    if not phrase_words or not key_words:
        return 0.0
    if phrase_words == key_words:
        return 1.0
    if set(phrase_words) <= set(key_words):
        return 0.9      # naming a thing by part of its name is not a mistake

    # Every word of the phrase has to find something to be, and the weakest
    # one decides -- otherwise one strong word carries a wrong answer, and
    # "wall clock" matches a "Stained Wall Chalkboard" on "wall" alone.
    def best(word):
        return max(((_word_score(word, other), other) for other in key_words),
                   default=(0.0, ""))

    score = min(best(word)[0] for word in phrase_words)
    if score and best(phrase_words[-1])[1] != key_words[-1]:
        score *= 0.85   # matched a modifier rather than what the thing is
    return score


# ---------------------------------------------------------------------------
# Finding what was meant
# ---------------------------------------------------------------------------

def best_match(caller, phrase, candidates=None):
    """
    (object, score) for the thing in reach that `phrase` most likely names.

    Returns (None, 0.0) when nothing is close. Candidates default to
    everything the caller could reach, so a mug on the table and a key in an
    open drawer are both eligible -- conjuring a second one because the first
    was put down somewhere would be the worst of both worlds.
    """
    if not phrase or caller is None:
        return None, 0.0
    if candidates is None:
        from world import relations

        candidates = relations.reachable(caller)

    best, best_score = None, 0.0
    for obj in candidates:
        # Aliases count as much as the key. An item conjured as a "Brass
        # Orrery" for somebody who asked for an astrolabe carries "astrolabe"
        # as an alias, and that is the name they will type again.
        names = [obj.key] + [str(alias) for alias in obj.aliases.all()]
        score = max(resemblance(phrase, name) for name in names)
        # Ties go to the oldest, so repeated attempts settle on one thing
        # rather than wandering between near-identical ones.
        if score > best_score or (score == best_score and best is not None
                                  and obj.id < best.id):
            best, best_score = obj, score
    return (best, best_score) if best_score else (None, 0.0)


def instead_of_creating(caller, phrase, fuzzy=False):
    """
    What to do about a name nothing here answers to.

    Returns (obj, suggestion):
      (obj, None)   -- confident this is what was meant; act on it
      (None, text)  -- close enough to be worth asking about; say `text` and
                       create nothing
      (None, None)  -- genuinely something new; go ahead and conjure it

    The asymmetry is deliberate. Acting on the wrong object wastes a moment;
    conjuring a near-duplicate costs money, permanently clutters the world,
    and is the one mistake the player cannot undo.

    `fuzzy` takes the middle band as good enough, and is for NPCs. There is
    nobody to read a question put to a character, so the choice for them is
    between the thing that is probably meant and another near-duplicate on
    the floor -- and they are naming things from memory in their own words,
    which is what the middle band is full of.
    """
    obj, score = best_match(caller, phrase)
    if obj is None:
        return None, None
    if score >= CONFIDENT or (fuzzy and score >= PLAUSIBLE):
        return obj, None
    if score >= PLAUSIBLE:
        name = obj.get_numbered_name(1, caller, return_string=True)
        return None, (f"You see no '{phrase}' here. Did you mean "
                      f"|w{name}|n?")
    return None, None
