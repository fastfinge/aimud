"""
What to call somebody who is not you.

A world keeps its own pronoun sets, the way it keeps its own states, traits
and kinds. Four are seeded and a world may add more, because a world that
generates a hive-mind, a ship's computer or a creature nobody has met before
has to be able to say how to refer to it -- and constraining that to whatever
four were written here would mean the register could only ever grow by a
player typing into it, which defeats the emergent half of the game.

**Five forms, because English has five**, and because Evennia already models
them that way -- `evennia.utils.funcparser`'s `$pron()` uses exactly this
decomposition, and its conjugator reads the sixth field. What is not borrowed
is Evennia's *model*: a fixed four-way male/female/neutral/plural keyed off an
object's `.gender`, which is precisely the thing a world here should be able
to stop being fixed.

**The sixth field is number, and it is not optional.** Without it every
sentence about a they/them character reads "they picks up the sword". It is
the one field a model reliably gets wrong, so `they` is seeded rather than
left to be invented and a declared set whose subject form is "they" has its
number corrected rather than believed -- the same way `DEFAULT_STATE_GROUP`
overrules a group a model declared.

**Growth goes through a declaration, never a side effect.** That is the rule
the state vocabulary already follows: a word merely *used* does nothing, a
word *declared* arrives with its meaning, and near-duplicates fold onto what
is already there. `register` is the one door, and the `pronouns` command and
`npc_gen`'s `new_pronoun_set` both go through it.
"""

from evennia.utils import logger

#: The five forms, in the order English teaches them, and what each is for.
#: Named rather than positional because a set written by a model arrives as a
#: mapping and a field missed is a sentence broken for ever.
FORMS = ("subject", "object", "adjective", "possessive", "reflexive")

#: What a complete declaration has to carry. The forms, plus the number that
#: decides the verb and the sentence that says who the set is for.
REQUIRED = FORMS + ("plural", "means")

#: Sets every world starts with.
#:
#: Four, and `they` is here for a reason the other three are not: it is the
#: one whose `plural` is True, nothing works that out reliably, and a world
#: that gets it wrong produces ungrammatical narration about that character
#: for as long as the character exists.
SEEDED = {
    "he": {
        "subject": "he", "object": "him", "adjective": "his",
        "possessive": "his", "reflexive": "himself", "plural": False,
        "means": "for somebody who goes by he and him",
    },
    "she": {
        "subject": "she", "object": "her", "adjective": "her",
        "possessive": "hers", "reflexive": "herself", "plural": False,
        "means": "for somebody who goes by she and her",
    },
    "they": {
        "subject": "they", "object": "them", "adjective": "their",
        "possessive": "theirs", "reflexive": "themselves", "plural": True,
        "means": "for somebody who goes by they and them, and for more than "
                 "one of anything",
    },
    "it": {
        "subject": "it", "object": "it", "adjective": "its",
        "possessive": "its", "reflexive": "itself", "plural": False,
        "means": "for a thing, and for somebody who goes by it",
    },
}

#: What somebody is called when nobody has said. The only defensible answer
#: for a character nobody has asked, and the reason `they` is seeded.
DEFAULT = "they"

#: Subject forms whose number is known and not up for declaration.
SETTLED_NUMBER = {"they": True, "he": False, "she": False, "it": False}


def _slug(word):
    """A subject form reduced to how it is stored: one lowercase word."""
    return "".join(ch for ch in str(word or "").lower().strip()
                   if ch.isalpha())


def vocabulary(world_root):
    """{slug: set} for this world, seeded sets included."""
    if world_root is None:
        return dict(SEEDED)
    stored = dict(world_root.db.pronoun_sets or {})
    if not stored:
        return dict(SEEDED)
    found = dict(SEEDED)
    found.update({slug: dict(entry) for slug, entry in stored.items()})
    return found


def get(world_root, slug):
    """One set by slug, or the default when the slug names none."""
    vocab = vocabulary(world_root)
    return dict(vocab.get(_slug(slug)) or vocab.get(DEFAULT) or SEEDED[DEFAULT])


def known(world_root, slug):
    """Whether this world keeps a set by that name."""
    return _slug(slug) in vocabulary(world_root)


def seed(world_root):
    """
    Write the seeded sets onto a world that has none.

    Not required -- `vocabulary` answers with them either way -- and worth
    doing so that `help` and the export see a world's register rather than an
    empty attribute that behaves as though it were full.
    """
    if world_root is None or world_root.db.pronoun_sets:
        return
    world_root.db.pronoun_sets = {slug: dict(entry)
                                  for slug, entry in SEEDED.items()}


# ---------------------------------------------------------------------------
# Adding one
# ---------------------------------------------------------------------------

def register(world_root, declared):
    """
    Put a pronoun set in the world's register, or fold it onto one there.

    Returns the slug actually in use, which may not be the one asked for --
    that return value is the point, and every caller must use it rather than
    what it passed in, or the fold achieves nothing. Returns "" for a
    declaration too incomplete to be worth keeping.

    **The slug is the subject form.** A set is identified in English by how it
    starts, so a declaration whose subject form this world already keeps is
    that set, and is answered with it. That is `register_state`'s fold doing
    the same job with a sharper test: pronoun forms are a small closed set of
    strings rather than open vocabulary, so an exact match is both right and
    cheaper than a similarity.

    **Two sets may share a form that is not the subject.** "she/her" and a
    declared "ze/her" both answer to "her", which is how neopronoun sets
    genuinely work. Allowed rather than refused; which was meant is a question
    for whoever is resolving a pronoun, not for whoever is storing one.
    """
    entry, complaint = clean(declared)
    if complaint:
        logger.log_info(f"pronouns: refused a set -- {complaint}")
        return ""

    slug = entry["subject"]
    if world_root is None:
        return slug

    vocab = vocabulary(world_root)
    if slug in vocab:
        return slug          # already had it; the declaration adds nothing

    # A word already meaning something else in this world is allowed here and
    # is worth saying out loud. Unlike a state and a trait, a pronoun and a
    # kind are not two answers to one question -- a world with a character who
    # goes by `it` and a kind called `it` is unlikely rather than incoherent.
    from world import vocabulary as vocabulary_mod

    vocabulary_mod.permit(world_root, slug, "pronoun")

    stored = dict(world_root.db.pronoun_sets or {})
    if not stored:
        stored = {name: dict(seeded) for name, seeded in SEEDED.items()}
    stored[slug] = entry
    world_root.db.pronoun_sets = stored
    logger.log_info(
        f"pronouns: {world_root.key} learned {slug}/{entry['object']}")
    return slug


def clean(declared):
    """
    (entry, complaint) for a set somebody wrote down.

    A declaration must be **complete**: five forms, a number and a sentence.
    An incomplete one is dropped rather than patched, because there is no
    later moment at which a missing reflexive gets filled in -- the sentence
    that needed it is written wrong once and then cached.
    """
    try:
        given = dict(declared or {})
    except (TypeError, ValueError):
        return None, "not a set of forms at all"

    entry = {}
    for field in FORMS:
        word = _slug(given.get(field))
        if not word:
            return None, f"no {field} form"
        entry[field] = word

    means = str(given.get("means") or "").strip()
    if not means:
        return None, f"no sentence saying who {entry['subject']} is for"
    entry["means"] = means

    # Believed only where nothing already knows better. A model asked whether
    # "they" is plural answers wrongly often enough that the question is not
    # worth asking; the same is true of the three other seeded subject forms.
    settled = SETTLED_NUMBER.get(entry["subject"])
    entry["plural"] = bool(given.get("plural")) if settled is None else settled
    return entry, ""


# ---------------------------------------------------------------------------
# Who has one
# ---------------------------------------------------------------------------

def of(character, world_root=None):
    """
    The set this character goes by. Never None.

    A character nobody has asked goes by `they`, which is the only defensible
    answer and the reason that set is seeded rather than invented.
    """
    slug = ""
    try:
        slug = _slug(character.db.pronouns)
    except AttributeError:
        pass
    if world_root is None:
        world_root = _world_of(character)
    return get(world_root, slug or DEFAULT)


def give(character, slug, world_root=None):
    """
    Tell a character what they go by. Returns the slug that stuck, or "".

    Refuses a set this world does not keep, which is the same discipline
    `npc_gen` already applies to traits: a character carrying a word nobody
    else has is the beginning of a second vocabulary. The way to *add* a set
    is `register`, and saying so is the point of refusing here.
    """
    if world_root is None:
        world_root = _world_of(character)
    slug = _slug(slug)
    if not slug or not known(world_root, slug):
        return ""
    character.db.pronouns = slug
    return slug


def _world_of(character):
    room = getattr(character, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Saying what a world keeps
# ---------------------------------------------------------------------------

def spelled(entry):
    """"she/her/hers" -- a set as somebody would say it aloud."""
    return "/".join([entry.get("subject", ""), entry.get("object", ""),
                     entry.get("possessive", "")])


def vocabulary_block(world_root,
                     header="Pronoun sets this world already uses"):
    """
    The register as a prompt block.

    Every prompt that could invent a set gets this, which is the half of
    keeping one vocabulary that does the work: a model shown that she/her
    exists does not declare it again under another name.
    """
    vocab = vocabulary(world_root)
    lines = [f"  {slug}: {spelled(entry)} — {entry.get('means', '')}"
             for slug, entry in sorted(vocab.items())]
    return (f"{header} — use one of these by name wherever it fits, and "
            f"declare a new set only for somebody none of them suits:\n"
            + "\n".join(lines) + "\n\n")
