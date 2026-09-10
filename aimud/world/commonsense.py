"""
A second lexicon: what people think is true of a word, as opposed to what it can be.

WordNet answers what a word **can be**. ConceptNet answers what people **think is
true of it**. Those are different questions with different reliability, and the
difference decides where this may be used and where it may not. See
docs/rulebooks-from-inform.md 7.1 for the measurement that chose the uses.

The alignment with this codebase is exact, and four of its relations are
definitionally four things this game has had to invent for itself:

    /r/ReceivesAction   "B can be done to A"      -> affordances.py
    /r/MannerOf         "A is a specific way to do B"  -> lexicon.verb_ancestors
    /r/DistinctFrom     "something that is A is not B" -> verbs.NEW_GROUP
    /r/HasPrerequisite  "for A to happen, B needs to"  -> a check rule

**One property disqualifies it from everything load-bearing: its nodes are words,
not senses.** `/c/en/pod` is one node for the seed case and for the thing you climb
into, and the edges that *are* sense-labelled are the ones imported from WordNet,
which this game already has. So nothing here may ever ground a kind, name a scope
or enter a cache key. `lexicon.py` states the test this fails: a lexicon "is never
asked what a word MEANS HERE", and "WordNet is a controlled vocabulary the world
selects from, not an oracle it queries." This is an oracle, and it is used the way
an oracle should be -- as a prior a generator may disagree with.

Two clauses of its own, on top of everything `lexicon.py` promises:

* **Never a floor.** `kinds.remember` applies the taxonomic floor last so that it
  wins: a model may add to what a chest can do and may not talk it out of being a
  container. Crowdsourced, weighted, sense-free data must never hold that
  position.
* **Never against the world's own guidance.** These worlds are allowed not to be
  consensus reality. "This is a world of technology; magic does not exist" is a
  line somebody wrote, and a corpus asserting otherwise into a prompt is working
  against the one field that exists to overrule it.

**Nothing here is load-bearing.** Every function answers neutrally when there is
no corpus -- an empty list, an empty set, None -- and a missing corpus is a normal
state rather than an error to report twice. The game is slightly clumsier without
it and never impossible, which is the same contract `lexicon.py` keeps.

**Getting it.** The corpus is fetched at first run and never vendored, and that
single decision removes the licence question rather than managing it: ConceptNet's
licence varies by source and the share-alike obligation attaches to *distributing*
the data. A repository shipping only the code to fetch it distributes neither, so
no edge is dropped on licence grounds. Attribution is owed regardless and is in
the README and in the download notice.

A gzipped TSV is not queryable and the official loader wants PostgreSQL, which is
far too heavy a dependency here. So the download is streamed into SQLite -- in the
standard library, one file beside `data/nltk_data`, indexed on `(start, relation)`
and `(end, relation)` so every lookup is the same shape as a WordNet lookup.
"""

import gzip
import os
import re
import sqlite3
import threading

from evennia.utils import logger

#: Where the corpus lives once built: beside `data/nltk_data`, for the same
#: reason -- part of the game like any other module, rather than in the player's
#: `server/` directory, which holds their database and their key.
_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
PATH = os.path.join(_DATA, "conceptnet.sqlite3")

#: Where it is fetched from. ConceptNet 5.7's assertions export: one gzipped TSV
#: of every edge, which is the only form that needs no PostgreSQL to read.
SOURCE = ("https://s3.amazonaws.com/conceptnet/downloads/2019/edges/"
          "conceptnet-assertions-5.7.0.csv.gz")

#: What is owed for using it, said wherever the download is mentioned.
ATTRIBUTION = (
    "ConceptNet 5.7, from the Open Mind Common Sense project and contributors. "
    "conceptnet.io. Licence varies by source and is recorded per edge; this "
    "game fetches the corpus rather than redistributing it."
)

#: The relations worth keeping. Everything else in the corpus is either imported
#: from WordNet -- which this game already has, with senses attached, which these
#: edges do not -- or about language rather than about the world: etymologies,
#: translations, word forms. Keeping the whole file would quadruple the index for
#: nothing any part of this game asks about.
#:
#: Ordered by what 7.1's table says they land on.
KEPT = (
    "DistinctFrom",      # exclusive state groups, free
    "Antonym",           # the same, from the other direction
    "PartOf",            # body parts beyond the hand-written 120, free
    "HasA",              # the same, inverted
    "MannerOf",          # verb kindred wider than troponymy, free
    "IsA",               # anchor proposals, and a third contradiction signal
    "ReceivesAction",    # affordance priors, and the contradiction signal
    "UsedFor",
    "CapableOf",
    "AtLocation",        # what is plausibly lying about in a galley
    "HasPrerequisite",   # a missing condition
    "Causes",            # a missing consequence
    "HasSubevent",
    "ObstructedBy",
)

#: Only English. The corpus is multilingual and nothing here reads anything else;
#: dropping the rest at import time is most of why the index is manageable.
_EN = re.compile(r"^/c/en/([^/]+)")

#: The minimum weight an edge must carry. ConceptNet records how much agreement
#: is behind an assertion, and the long tail at weight 1.0 is where a single
#: contributor's typo lives. One is the corpus's own floor for a single source;
#: this keeps that and no more, because raising it throws away most of the
#: genre-adjacent vocabulary along with the noise.
MIN_WEIGHT = 1.0

#: Resolved once. `None` means "not looked yet"; `False` means "looked, and there
#: is no corpus", which is a normal state and not an error to report twice.
_DB = None
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Whether there is anything to consult
# ---------------------------------------------------------------------------

def _connect():
    """The corpus, or None when there is none."""
    global _DB
    if _DB is not None:
        return _DB or None

    with _LOCK:
        if _DB is not None:
            return _DB or None
        if not os.path.exists(PATH):
            _DB = False
            return None
        try:
            found = sqlite3.connect(PATH, check_same_thread=False)
            found.execute("SELECT 1 FROM edges LIMIT 1").fetchone()
            _DB = found
        except Exception as err:
            logger.log_info(
                f"ConceptNet index unreadable ({err}); running without it. "
                f"State groups, body parts and anchor suggestions will be "
                f"guessed rather than looked up.")
            _DB = False
    return _DB or None


def available():
    """Whether there is a corpus to consult at all."""
    return _connect() is not None


def forget():
    """Drop the cached connection. For tests, and after a rebuild."""
    global _DB
    with _LOCK:
        if _DB:
            try:
                _DB.close()
            except Exception:
                pass
        _DB = None


def size():
    """(edges, megabytes) of the index, or (0, 0) when there is none."""
    db = _connect()
    if db is None:
        return 0, 0
    try:
        edges = db.execute("SELECT count(*) FROM edges").fetchone()[0]
    except Exception:
        return 0, 0
    return int(edges), round(os.path.getsize(PATH) / (1024 * 1024), 1)


# ---------------------------------------------------------------------------
# Asking it things
# ---------------------------------------------------------------------------

def _word(text):
    """A phrase as the corpus spells it: lower case, underscores for spaces."""
    found = re.sub(r"[^a-z0-9_ ]", "", str(text or "").lower().strip())
    return re.sub(r"[ _]+", "_", found).strip("_")


def _said(word):
    """A corpus word as English: underscores back to spaces."""
    return str(word or "").replace("_", " ")


def forward(word, relation, limit=12):
    """
    The ends of edges that start at `word`. `[]` without a corpus.

    "A PartOf B" read forward from A gives the wholes a thing is part of; read
    `backward` it gives the parts of a thing. Both directions are wanted by
    something, so both are indexed.
    """
    return _query("start", "end", word, relation, limit)


def backward(word, relation, limit=12):
    """The starts of edges that end at `word`. `[]` without a corpus."""
    return _query("end", "start", word, relation, limit)


def _query(mine, theirs, word, relation, limit):
    db = _connect()
    wanted = _word(word)
    if db is None or not wanted or relation not in KEPT:
        return []
    try:
        rows = db.execute(
            f"SELECT {theirs} FROM edges WHERE {mine} = ? AND relation = ? "
            f"ORDER BY weight DESC LIMIT ?",
            (wanted, relation, int(limit))).fetchall()
    except Exception as err:
        logger.log_info(f"ConceptNet query failed ({err})")
        return []
    return [_said(row[0]) for row in rows]


def both_ways(word, relation, limit=12):
    """
    Everything joined to `word` by a relation, whichever end it was written at.

    For the symmetric relations -- `DistinctFrom` and `Antonym` are true in both
    directions and the corpus records whichever way round the contributor typed
    it. Asking one way finds half the answers.
    """
    found = []
    for side in (forward(word, relation, limit), backward(word, relation, limit)):
        for other in side:
            if other not in found and _word(other) != _word(word):
                found.append(other)
    return found[:limit]


# ---------------------------------------------------------------------------
# The free uses
# ---------------------------------------------------------------------------

def opposites(word, limit=8):
    """
    The words that cannot be true at the same time as this one.

    `DistinctFrom` -- "something that is A is not B" -- is definitionally what a
    state group is, and `Antonym` catches the pairs a contributor wrote as
    opposites instead. Together they are open/closed, wet/dry, lit/unlit, already
    written down, for every ordinary pair in English.

    Advisory. A world that wants `lit` and `burning` to be separate conditions is
    entitled to that, and this only ever proposes.
    """
    found = []
    for relation in ("DistinctFrom", "Antonym"):
        for other in both_ways(word, relation, limit):
            if other not in found:
                found.append(other)
    return found[:limit]


def parts_of(word, limit=24):
    """
    The parts a thing has, for a world with beetles and birds in it.

    `anatomy.PARTS` is about 120 hand-written nouns whose own comment admits the
    problem, and every creature a generator invents is tested against it. Read
    from both relations because the corpus records the same fact either way round:
    a wing is `PartOf` a bird, and a bird `HasA` wing.
    """
    found = []
    for other in forward(word, "HasA", limit):
        if other not in found:
            found.append(other)
    for other in backward(word, "PartOf", limit):
        if other not in found:
            found.append(other)
    return found[:limit]


def is_part_of_anything(word):
    """
    Whether the corpus thinks this word names a part of something.

    Both relations, for the same reason `parts_of` reads both: the corpus records
    the same fact either way round, and a contributor who typed "an insect has a
    proboscis" left no `PartOf` edge at all. Checking one direction finds half the
    parts, which on a test of "is this a body part" is a wrong answer rather than
    a thin one.
    """
    return bool(forward(word, "PartOf", 1)) or bool(backward(word, "HasA", 1))


def kinds_of(word, limit=8):
    """
    What the corpus thinks a word is a sort of: `IsA`, read forward.

    Two uses, both free and both advisory. It pre-fills section 7's anchor menu
    for an invented noun, so a model picking where `datapad` hangs is choosing
    rather than inventing. And it is a third signal that a sense choice was wrong,
    beside the two `kinds.sense_contradicts` already has.

    Never a floor, and never a ground. A kind is a WordNet synset; this answers in
    words, and words are what 7.1 says it may not be trusted for.
    """
    return forward(word, "IsA", limit)


def ways_to(verb, limit=8):
    """
    The verbs this one is a specific way of doing: `MannerOf`.

    Wider than WordNet's troponymy and, unlike it, including multiword verbs --
    "take off" is a manner of "leave" and WordNet has no pointer saying so.
    Beside `lexicon.verb_ancestors` rather than instead of it.
    """
    return forward(verb, "MannerOf", limit)


def can_be_done_to(word, limit=12):
    """
    What people think can be done to a thing: `ReceivesAction`.

    The relation whose definition is this codebase's own sentence about
    affordances. Its values are participles -- "eaten", "burned" -- which
    `affordances.known_verb` already folds, so a caller gets them as verbs.

    This is the first row of 7.1's *paid* column, and it is here because the
    lookup is free even though putting its answers in a prompt is not. Nothing
    calls it from a prompt yet; see the plan's phase 12, which holds the priors
    back until a replay measurement says they earn their tokens.
    """
    from world import affordances

    found = []
    for word_said in forward(word, "ReceivesAction", limit):
        verb = affordances.known_verb(word_said.split(" ")[0])
        if verb and verb not in found:
            found.append(verb)
    return found[:limit]


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------

def _schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS edges (
            start     TEXT NOT NULL,
            relation  TEXT NOT NULL,
            end       TEXT NOT NULL,
            weight    REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS built (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)


def _index(db):
    """The two indexes every lookup uses. Added after loading, not before."""
    db.executescript("""
        CREATE INDEX IF NOT EXISTS edges_start ON edges (start, relation);
        CREATE INDEX IF NOT EXISTS edges_end   ON edges (end, relation);
    """)


def read_edges(lines):
    """
    The edges worth keeping, out of the corpus's own TSV.

    One row is `uri, relation, start, end, metadata` where the metadata is JSON
    carrying the weight. Yields `(start, relation, end, weight)` with the `/c/en/`
    prefixes stripped, English only, kept relations only.

    Separated from the download so that the parsing can be tested against a
    committed sample of real edges without fetching a gigabyte.
    """
    import json

    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        relation = parts[1].rsplit("/", 1)[-1]
        if relation not in KEPT:
            continue
        start, end = _EN.match(parts[2]), _EN.match(parts[3])
        if not start or not end:
            continue
        weight = 1.0
        if len(parts) > 4:
            try:
                weight = float(json.loads(parts[4]).get("weight", 1.0))
            except Exception:
                weight = 1.0
        if weight < MIN_WEIGHT:
            continue
        yield start.group(1), relation, end.group(1), weight


def build_from(lines, path=None, on_progress=None):
    """
    Build the index out of an iterable of TSV lines. Answers with the edge count.

    The half of the builder that needs no network, which is what makes the whole
    thing testable: a committed sample of real edges goes in, a queryable index
    comes out, and the download is only where the lines come from.
    """
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    partial = f"{path}.building"
    if os.path.exists(partial):
        os.remove(partial)

    db = sqlite3.connect(partial)
    try:
        _schema(db)
        kept = 0
        batch = []
        for edge in read_edges(lines):
            batch.append(edge)
            kept += 1
            if len(batch) >= 20000:
                db.executemany("INSERT INTO edges VALUES (?, ?, ?, ?)", batch)
                batch = []
                if on_progress:
                    on_progress(kept)
        if batch:
            db.executemany("INSERT INTO edges VALUES (?, ?, ?, ?)", batch)
        # Indexed after loading rather than before: building an index while
        # inserting a few million rows costs several times as much as building it
        # once at the end, and nothing queries a half-loaded corpus.
        _index(db)
        db.execute("INSERT OR REPLACE INTO built VALUES ('edges', ?)",
                   (str(kept),))
        db.commit()
    finally:
        db.close()

    # Moved into place only once it is complete, so an interrupted build leaves
    # no half-corpus for `available()` to find and believe.
    forget()
    if os.path.exists(path):
        os.remove(path)
    os.replace(partial, path)
    forget()
    return kept


def download(on_progress=None, source=None, path=None):
    """
    Fetch the corpus and build the index. Blocking; call it off the main thread.

    Streamed and decompressed as it arrives rather than saved first, because the
    gzip is large and the only thing wanted out of it is the few million edges
    that survive `read_edges`. `on_progress` is given the running edge count.
    """
    import urllib.request

    source = source or SOURCE
    logger.log_info(f"ConceptNet: fetching {source}")
    with urllib.request.urlopen(source) as stream:
        with gzip.open(stream, "rt", encoding="utf-8", errors="replace") as tsv:
            kept = build_from(tsv, path=path, on_progress=on_progress)
    logger.log_info(f"ConceptNet: {kept} edges indexed at {path or PATH}")
    return kept
