"""
Who pays for a model call, and who caused it.

Every generator in this game takes an `account` and asks it two questions:
what is your API key, and which model do you want for this job. That is
exactly right for one person playing in a world they made themselves, and it
is wrong in three ways the moment anything else is true.

* **A world will be shared.** Somebody visiting a world they did not build
  should not be spending their own key on its innkeeper, and may not have a
  key at all. The world's creator is paying; the acting player is only acting.
  Asked of the caller, that question has the wrong answer.

* **A world may answer nothing.** Worldmode `none` is a world with nobody
  paying, still worth walking around in. Asked of the caller, "is there a
  model" has fifty-seven separate places to be answered, and a `ValueError`
  arriving at a player who did nothing wrong.

* **A player may not use OpenRouter.** The service URL is a constant in
  `world.llm`, which is a third question to the same object and has nowhere
  to live.

So the thing a generator is handed is not the person typing. It is a
**sponsor**: the world, whoever is paying for it, and whoever caused this
particular call. All three are known at the moment a sponsor is made and none
of them is known inside `world.llm`, which is why the sponsor goes all the way
down rather than being unpacked into an api key at the top.

That last part is what makes the ledger possible at all. "How much has this
cost" is answerable today by nobody; "whose action spent whose money" is the
question that actually matters once worlds are shared, and it can only be
answered if the actor and the payer were both still in scope when the request
was built.

**One place to ask who made a world.** `world_creator` has been written on a
first room for as long as `worldgen` has had a creator to write, and read raw
in three other modules -- each of which then had its own idea of what to do
when it was empty. `npcs.py` in particular preferred *any player in the room
with a key*, which is the exact behaviour shared worlds cannot have: an NPC
would spend a visitor's money because the visitor happened to be standing
there.

So the attribute stays and the reading of it moves here. `creator_of` is the
one answer, `claim` the one write, and a world made before either -- or made
without a creator being passed through -- falls back to the scan of
`created_worlds` that this replaced, claiming itself on the way past so the
scan is paid once per world at most.
"""

from evennia.utils import logger

#: What a world says when asked who made it.
#:
#: Already the name for this before a sponsor existed: `worldgen` has always
#: written it on the first room, and three places read it. What changes is
#: that it is now written for every world rather than only the ones that
#: happened to pass a creator through, and that everything asking goes
#: through `creator_of` rather than reading the attribute raw.
CREATOR_ATTR = "world_creator"


class Sponsor:
    """
    The world a call is for, whoever pays for it, and whoever caused it.

    Answers the two questions a generator used to ask an account, plus the two
    it had nowhere to ask: where the service lives, and whether there is going
    to be an answer at all.

    A sponsor with no account behind it is a real and ordinary thing -- a world
    whose creator has no key set, or a world nobody has claimed -- and it
    answers `False` to `answers` rather than raising. The raise is saved for
    `key`, where a caller has decided to go ahead and needs to be told why it
    cannot.
    """

    __slots__ = ("world_root", "account", "actor")

    def __init__(self, world_root=None, account=None, actor=None):
        self.world_root = world_root
        self.account = account
        self.actor = actor

    # -- who is involved -------------------------------------------------

    @property
    def payer(self):
        """The account whose key this spends, or None."""
        return self.account

    @property
    def answers(self):
        """
        Whether a model is going to answer for this world at all.

        False for a world with nobody paying. This is the one question every
        generator should ask before building a prompt, and the place worldmode
        `none` will be added when it exists -- one line here rather than a
        branch in each of the callers.
        """
        return bool(self.account and self.account.db.openrouter_api_key)

    # -- what a generator needs ------------------------------------------

    def key(self):
        """
        The API key to spend, or `ValueError` saying whose it should have been.

        The wording distinguishes the two cases on purpose. A player with no
        key of their own is told to set one; a player standing in somebody
        else's unfunded world is told that, because "use the apikey command"
        is advice they cannot act on.
        """
        if self.account is None:
            return _no_account()
        stored = self.account.db.openrouter_api_key
        if not stored:
            return _no_key(self.account, self.actor)
        return stored

    @property
    def base_url(self):
        """
        Where to send it: this account's choice, or wherever the game talks to
        by default.

        The default is deliberately not named here. Which service the game
        speaks to is `world.llm`'s business and there is a test asserting that
        no other module knows -- one seam, so it cannot quietly be reopened.
        What belongs to a sponsor is only whether whoever pays has chosen
        somewhere else.
        """
        from world import llm

        chosen = self.account.db.api_base_url if self.account else ""
        return str(chosen or llm.BASE_URL).rstrip("/")

    def model_for(self, *jobs):
        """
        The model for a job, with that job's sampling settings attached.

        Delegates, because which model answers for "dialogue" is a setting
        belonging to whoever pays, and that is what an account has always
        held. What changes is only which account is asked.
        """
        if self.account is None:
            from world.model_params import ModelChoice

            return ModelChoice("", {}, job=jobs[0] if jobs else "")
        return self.account.model_for(*jobs)


def _no_account():
    raise ValueError(
        "This world has no owner on this server, so nothing here can "
        "be generated."
    )


def _no_key(account, actor):
    owner = getattr(account, "key", "") or "whoever made it"
    mine = actor is not None and getattr(actor, "account", None) is account
    if mine:
        raise ValueError(
            f"Account '{owner}' has no OpenRouter API key set. "
            "Use the |wapikey set <key>|n command to add one."
        )
    raise ValueError(
        f"This world belongs to {owner}, who has no API key set, so "
        "nothing new can happen here."
    )


# ---------------------------------------------------------------------------
# Finding one
# ---------------------------------------------------------------------------

def of(caller):
    """
    The sponsor for something a character is doing.

    The ordinary entry point, and the one that replaces `_get_account(caller)`
    at every command. The world comes from where they are standing, the payer
    from who made that world, and the actor is them.
    """
    room = getattr(caller, "location", None)
    world_root = getattr(room.db, "world_root", None) if room else None
    return of_world(world_root, actor=caller)


def of_world(world_root, actor=None):
    """The sponsor for a world, with an optional actor to blame the call on."""
    return Sponsor(world_root=world_root, account=creator_of(world_root),
                   actor=actor)


def of_account(account, actor=None, world_root=None):
    """
    A sponsor for work that is not inside a world yet.

    World generation is the case: the first room does not exist, so there is
    nothing to read a creator off, and the person asking for a world is by
    definition the person who will own it.
    """
    return Sponsor(world_root=world_root, account=account, actor=actor)


def creator_of(world_root):
    """
    The account that made this world, or None.

    Reads the back-link `claim` writes. Falls back to the scan the back-link
    replaced, so a world made before this existed still answers -- and claims
    itself on the way past, which is what makes the backfill a formality
    rather than a requirement.
    """
    if world_root is None:
        return None

    # An attribute holding a deleted object reads back as None, which is the
    # right answer here without any checking: a world whose owner is gone is
    # unfunded rather than broken.
    stored = world_root.db.world_creator
    if stored is not None:
        return stored

    found = _scan_for_creator(world_root)
    if found is not None:
        claim(world_root, found)
    return found


def claim(world_root, account):
    """
    Record who made a world, so nothing has to go looking again.

    Refuses anything that is not an account, and says so. This goes into a
    persistent attribute, so a wrong value is not a wrong value: it is a
    `TypeError` from inside Evennia's pickler, several frames from whoever
    passed it, with nothing in the message naming this function. Handed a
    Sponsor rather than the account inside it -- which is one rename away and
    happened -- the failure read `'NoneType' object is not callable`.
    """
    if world_root is None or account is None:
        return
    if not hasattr(account, "db") or isinstance(account, Sponsor):
        logger.log_err(
            f"sponsor: refusing to record {type(account).__name__} as the "
            f"maker of {getattr(world_root, 'key', world_root)!r}; that wants "
            f"the account, not whatever is carrying it"
        )
        return
    world_root.db.world_creator = account


def _scan_for_creator(world_root):
    """
    Whoever lists this world among the ones they made.

    The expensive way, kept only because worlds made before the back-link
    existed have no other answer. Every call that reaches here writes the
    back-link, so it is paid once per world at most.
    """
    from evennia.accounts.models import AccountDB

    wanted = world_root.id
    for account in AccountDB.objects.all():
        try:
            if wanted in (account.db.created_worlds or []):
                return account
        except Exception:
            continue
    return None


def backfill():
    """
    Write the creator back-link onto every world that has none.

    Driven from the account side, which is the only place the answer is
    written down, and cheap: one pass over accounts rather than one scan per
    world. Returns how many worlds were claimed, for the startup log.
    """
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    claimed = 0
    for account in AccountDB.objects.all():
        try:
            ids = list(account.db.created_worlds or [])
        except Exception:
            continue
        for world_id in ids:
            try:
                root = ObjectDB.objects.get(id=int(world_id))
            except Exception:
                continue
            if root.db.world_creator:
                continue
            claim(root, account)
            claimed += 1
    return claimed
