"""
Assets, as a subject of the verbs: files the game keeps. docs/archived/assets.md.

  view assets                      yours and everybody's, with your quota
  view assets <type>               only one type: view assets world
  view assets missing              what is gone, and can be fetched again
  view assets pool                 what owners gave up, and what goes next
  view assets recent [<n>]         what was added lately (admins)
  view asset <name>                one, in full
  create asset [<url>]             fetch one from a web address (a form)
  edit asset <name>                change its name, description or credit
  edit asset <name> <field> <text> one of those in a line
  edit asset <name> giveup [yes]   hand it to the server's pool
  edit asset <name> adopt          take a given-up one onto your quota
  edit asset <name> fetch          fetch a missing one again
  delete asset <name> [force] [yes]
  edit quota <account> <size>      one account's own quota (admins)

**Server-wide, so not a maker.** Everything in `world/making.py` is a fact
about one world, owned by its creator. An asset belongs to no world: any
world may use one, and only whoever is charged for it, or an admin, may
change it. That is the shape `services_subject.py` already has.

**Giving up and adopting are `edit`, not verbs of their own.** The verbs are
fixed (`commands/subjects.py`), and both change who an asset belongs to,
which is editing it.

Nobody is shown a path. A player picks assets by name, and a file is never
anything but its type, its size and, once `ASSET_BASE_URL` is set, the
address a client fetches it from.
"""

from commands.subjects import Subject, Use, account_of, answered, asking
from world import assets, menus


def _caller(ctx):
    return ctx.character or ctx.caller


def _account(ctx):
    return account_of(_caller(ctx))


def _admin(ctx):
    return assets.is_admin(_account(ctx))


def _has_account(ctx):
    return _account(ctx) is not None


# ---------------------------------------------------------------------------
# Saying one
# ---------------------------------------------------------------------------

def _belongs(asset, account):
    if asset.status == asset.MISSING:
        return "missing"
    if asset.charged_to_id is None:
        return "the server's"
    if account is not None and asset.charged_to_id == account.id:
        return "yours"
    return f"{asset.charged_to.key}'s"


def line(asset, account=None):
    """One asset in a list: name, type, size, whose."""
    return (f"|w{asset.name}|n ({asset.type}, {assets.size_said(asset.size)}, "
            f"{_belongs(asset, account)}) -- {asset.description}")


def detail(asset, account=None):
    """One asset in full."""
    lines = [f"|w{asset.name}|n -- {asset.type} "
             f"{('version ' + asset.version) if asset.version else ''}".rstrip(),
             asset.description,
             f"Size: {assets.size_said(asset.size)}. Belongs: "
             f"{_belongs(asset, account)}. Known by: {asset.hash[:12]}."]
    origin = dict(asset.ORIGINS).get(asset.origin, asset.origin)
    who = asset.added_by.key if asset.added_by_id else "nobody now"
    lines.append(f"It was {origin}, by {who}, on {asset.added:%Y-%m-%d}.")
    if asset.source:
        lines.append(f"From: {asset.source}")
    if asset.author or asset.licence:
        lines.append(f"Credit: {asset.author or 'unknown'}; licence: "
                     f"{asset.licence or 'not said'}.")
    if asset.made_with:
        made = ", ".join(f"{key} {value}" for key, value in
                         sorted(asset.made_with.items()) if key != "request")
        lines.append(f"Made with: {made}.")
    address = assets.public_url(asset)
    if address:
        lines.append(f"Fetched by clients from: {address}")
    using = assets.uses_of(asset)
    if using:
        lines.append("Used by: " + "; ".join(str(use.get("said", use))
                                             for use in using))
    return "\n".join(lines)


def _quota_line(account):
    if account is None:
        return ""
    allowed = assets.quota_of(account)
    used = assets.size_said(assets.used_by(account))
    if allowed is None:
        return f"You are using {used}, with no limit."
    return f"You are using {used} of {assets.size_said(allowed)}."


# ---------------------------------------------------------------------------
# view assets
# ---------------------------------------------------------------------------

def _listing(found, account, empty):
    found = list(found[:200])
    if not found:
        return empty
    return "\n".join(line(asset, account) for asset in found)


def view_run(cmd, ctx, words):
    from world import asset_types

    caller = cmd.caller
    account = account_of(caller)
    said = " ".join(words).strip().lower()
    if not said:
        caller.msg(f"{_quota_line(account)}\n" + _listing(
            assets.search(), account,
            "Nobody has added an asset yet. |wcreate asset|n fetches one."))
        return
    if said == "missing":
        caller.msg(_listing(assets.search(status="missing"), account,
                            "Nothing is missing."))
        return
    if said == "pool":
        quota = assets.pool_quota()
        head = (f"The server keeps {assets.size_said(assets.pool_used())} of "
                f"given-up assets"
                + (f", of {assets.size_said(quota)}." if quota else "."))
        going = assets.next_in_line()
        if going:
            head += " Next to go: " + ", ".join(a.name for a in going) + "."
        caller.msg(head + "\n" + _listing(
            assets.search().filter(charged_to__isnull=True), account,
            "Nobody has given an asset up."))
        return
    if said.split()[0] == "recent":
        if not assets.is_admin(account):
            caller.msg("Reviewing what was added is for admins.")
            return
        count = int(said.split()[1]) if len(said.split()) > 1 \
            and said.split()[1].isdigit() else 20
        found = assets.search(status=None)[:count]
        caller.msg("\n".join(
            f"{asset.added:%Y-%m-%d %H:%M} "
            f"{asset.added_by.key if asset.added_by_id else 'nobody'}: "
            + line(asset, account)
            + (f" [from {asset.source}]" if asset.source else "")
            for asset in found) or "Nothing has been added.")
        return
    if asset_types.get(said) is not None:
        caller.msg(_listing(assets.search(said), account,
                            f"There are no {said} assets."))
        return
    asset, why = assets.named(said)
    caller.msg(detail(asset, account) if asset is not None else why)


def _view_form():
    return menus.Form(
        key="assets", title="Assets", kind=menus.VIEW,
        intro=lambda ctx: _quota_line(_account(ctx)) + "\n" + _listing(
            assets.search(), _account(ctx), "Nobody has added an asset yet."),
        items=[])


def view_items(ctx):
    return [menus.Submenu("assets", "Files this game keeps", _view_form(),
                          help="Worlds, and the sounds, images and the rest "
                               "the game keeps, with how much of your quota "
                               "you are using.")]


# ---------------------------------------------------------------------------
# create asset: fetch one
# ---------------------------------------------------------------------------

def fetch_and_add(caller, url, name, description, author="", licence=""):
    """
    Fetch in a thread, then keep it on the main thread, telling `caller`.

    The fetch is the slow and dangerous part and touches no database, so it
    runs off the main thread; keeping it does, so it does not.
    """
    import os

    from twisted.internet import threads

    account = account_of(caller)

    def kept(path):
        try:
            _asset, said = assets.add(
                path, name=name, description=description, added_by=account,
                origin="url", source=url, author=author, licence=licence)
            caller.msg(said)
        except assets.Refused as refusal:
            caller.msg(f"|rNot kept:|n {refusal}.")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def failed(failure):
        refusal = failure.value
        if isinstance(refusal, assets.Refused):
            caller.msg(f"|rNot fetched:|n {refusal}.")
        else:
            caller.msg("|rNot fetched:|n it could not be fetched.")

    caller.msg(f"Fetching {url} ...")
    threads.deferToThread(assets.fetch, url, assets.largest()) \
        .addCallbacks(kept, failed)


def _keep(ctx):
    draft = dict(ctx.draft)
    url = str(draft.get("url") or "").strip()
    name = str(draft.get("name") or "").strip()
    description = str(draft.get("description") or "").strip()
    if not url:
        raise menus.Refuse("Say where to fetch it from.")
    if not name or not description:
        raise menus.Refuse("It needs a name and a description: the description "
                           "is how anybody who cannot see or hear it finds it.")
    if not _has_account(ctx):
        raise menus.Refuse("Only an account can keep an asset.")
    ctx.dirty = False
    fetch_and_add(_caller(ctx), url, name, description,
                  draft.get("author") or "", draft.get("licence") or "")
    return ""


def _fields(creating):
    fields = []
    if creating:
        fields.append(menus.Field(
            "url", "Where to fetch it from", required=True,
            help="A web address, http:// or https://. What kind of file it is "
                 "is read off the file, never the address."))
    fields += [
        menus.Field("name", "Its name", required=True,
                    help="What players and models will call it."),
        menus.Field("description", "What it is", kind=menus.LONG_TEXT,
                    required=True,
                    help="Say what it is as if to somebody who cannot see or "
                         "hear it, because a screen reader user and a model "
                         "will only ever know it by this."),
        menus.Field("author", "Who made it",
                    help="For credit: many sounds and images need it."),
        menus.Field("licence", "Its licence",
                    help="CC-BY 4.0, public domain, your own: whatever it was "
                         "shared under."),
    ]
    return fields


ASSET = menus.Form(
    key="asset", title="A new asset", guided=True,
    intro=lambda ctx: (
        "A file for the game to keep. "
        + _quota_line(_account(ctx))
        + " Only files of a kind this server keeps are accepted, checked by "
          "what is in them."),
    items=lambda ctx: _fields(True) + [
        menus.Action("keep", "Fetch it, and keep it", _keep,
                     after=menus.CLOSE)],
)


def create_run(cmd, ctx, words):
    menus.open_menu(cmd.caller, ASSET, session=cmd.session,
                    draft={"url": " ".join(words)} if words else {})


def create_items(ctx):
    if not _has_account(ctx):
        return []
    return [menus.Submenu("asset", "A file for the game to keep", ASSET,
                          fresh_draft=True, command="create asset",
                          help="Fetched from a web address. The website's "
                               "upload page takes a file directly.")]


# ---------------------------------------------------------------------------
# edit asset
# ---------------------------------------------------------------------------

def _asset_of(ctx):
    found = assets.find(ctx.data.get("hash") or ctx.draft.get("hash"))
    if found is None:
        raise menus.Refuse("That asset is gone.")
    return found


def _save_edit(ctx):
    asset = _asset_of(ctx)
    if not assets.may_change(_account(ctx), asset):
        raise menus.Refuse("Only whoever it belongs to, or an admin, can "
                           "change it.")
    try:
        assets.edit(asset, **{field: ctx.draft.get(field)
                              for field in ("name", "description", "author",
                                            "licence")})
    except assets.Refused as refusal:
        raise menus.Refuse(str(refusal).capitalize() + ".")
    ctx.dirty = False
    return f"Saved {asset.name}."


def _edit_form():
    return menus.Form(
        key="edit-asset", title=lambda ctx: f"The asset {ctx.draft.get('name')}",
        intro=lambda ctx: detail(_asset_of(ctx), _account(ctx)),
        items=lambda ctx: _fields(False) + [
            menus.Action("keep", "Save", _save_edit, after=menus.CLOSE)],
    )


EDIT = _edit_form()


def _draft_of(asset):
    return {"hash": asset.hash, "name": asset.name,
            "description": asset.description, "author": asset.author,
            "licence": asset.licence}


TYPED = ("name", "description", "author", "licence")


def edit_run(cmd, ctx, words):
    caller = cmd.caller
    account = account_of(caller)
    words, already = answered(words)
    if not words:
        caller.msg("Which asset? |wview assets|n lists them.")
        return None

    # The asset's name may be several words, so the action is looked for at
    # the end: `edit asset sea at night adopt`.
    action = words[-1].lower() \
        if words[-1].lower() in ("giveup", "adopt", "fetch") else ""
    field_at = next((index for index, word in enumerate(words)
                     if index and word.lower() in TYPED), None)
    if action:
        said = " ".join(words[:-1])
    elif field_at is not None:
        said = " ".join(words[:field_at])
    else:
        said = " ".join(words)
    asset, why = assets.named(said, status=None)
    if asset is None:
        caller.msg(why)
        return None

    if action == "fetch":
        # A missing asset, from where it came: charged to whoever asks, who
        # is bringing it back. docs/archived/assets.md 9.
        caller.msg(f"Fetching {asset.name} again...")
        assets.fetch_again(account, asset, lambda why: caller.msg(
            f"|rNot fetched:|n {why}." if why else f"|w{asset.name}|n is back."))
        return None
    if action == "adopt":
        try:
            caller.msg(assets.adopt(account, asset))
        except assets.Refused as refusal:
            caller.msg(f"{str(refusal).capitalize()}.")
        return None
    if not assets.may_change(account, asset):
        caller.msg("Only whoever it belongs to, or an admin, can change it.")
        return None
    if action == "giveup":
        def do():
            try:
                caller.msg(assets.give_up(account, asset))
            except assets.Refused as refusal:
                caller.msg(f"{str(refusal).capitalize()}.")

        return asking(cmd, f"Give {asset.name} up to the server? It stops "
                           f"counting against your quota, and only an admin "
                           f"can delete it afterwards. If the server runs "
                           f"short of room it may go.",
                      "giveup_asset", f"edit asset {asset.hash[:8]} giveup",
                      do, already)
    if field_at is not None:
        field = words[field_at].lower()
        try:
            assets.edit(asset, **{field: " ".join(words[field_at + 1:])})
        except assets.Refused as refusal:
            caller.msg(f"{str(refusal).capitalize()}.")
            return None
        caller.msg(f"Saved {asset.name}'s {field}.")
        return None
    menus.open_menu(caller, EDIT, session=cmd.session, draft=_draft_of(asset))
    return None


def _edit_quota(caller, account, words):
    from evennia.accounts.models import AccountDB

    if not assets.is_admin(account):
        caller.msg("Setting somebody's quota is for admins.")
        return None
    if len(words) < 2:
        caller.msg("|wedit quota <account> <size>|n -- 750MB, 2GB, or default.")
        return None
    found = AccountDB.objects.filter(username__iexact=words[0]).first()
    if found is None:
        caller.msg(f"There is no account called {words[0]}.")
        return None
    try:
        caller.msg(assets.set_quota(found, assets.read_size(" ".join(words[1:]))))
    except assets.Refused as refusal:
        caller.msg(f"{str(refusal).capitalize()}.")
    return None


def _mine(ctx):
    account = _account(ctx)
    if account is None:
        return []
    if assets.is_admin(account):
        return list(assets.search(status=None)[:100])
    return list(assets.search(status=None).filter(charged_to=account)[:100])


def edit_items(ctx):
    return [menus.Submenu(f"asset-{asset.hash[:8]}", line(asset, _account(ctx)),
                          EDIT, fresh_draft=True,
                          draft=lambda ctx, a=asset: _draft_of(a),
                          command=f"edit asset {asset.hash[:8]}")
            for asset in _mine(ctx)]


# ---------------------------------------------------------------------------
# delete asset
# ---------------------------------------------------------------------------

def delete_run(cmd, ctx, words):
    caller = cmd.caller
    account = account_of(caller)
    words, already = answered(words)
    force = bool(words) and words[-1].lower() == "force"
    if force:
        words = words[:-1]
    asset, why = assets.named(" ".join(words), status=None)
    if asset is None:
        caller.msg(why)
        return None
    if not assets.may_change(account, asset):
        caller.msg("Only whoever it belongs to, or an admin, can delete it.")
        return None
    if force and not assets.is_admin(account):
        caller.msg("Only an admin can remove an asset something is using.")
        return None
    using = assets.uses_of(asset)
    if using and not force:
        caller.msg(f"{asset.name} is in use: " + "; ".join(
            str(use.get("said", use)) for use in using)
            + ". |wedit asset " + asset.hash[:8] + " giveup|n hands it to the "
              "server instead, which frees your quota and keeps it for them.")
        return None

    def do():
        try:
            caller.msg(assets.delete(asset, force=force))
        except assets.Refused as refusal:
            caller.msg(f"{str(refusal).capitalize()}.")

    key = "force_delete_asset" if force else "delete_asset"
    question = (f"Remove {asset.name}, which is in use? Everything using it "
                f"will find it missing." if force and using
                else f"Delete {asset.name}? It cannot be brought back unless "
                     f"somebody fetches it again.")
    return asking(cmd, question, key,
                  f"delete asset {asset.hash[:8]}{' force' if force else ''}",
                  do, already)


def delete_items(ctx):
    return [menus.Action(
        f"asset-{asset.hash[:8]}", line(asset, _account(ctx)),
        run=lambda c, a=asset: assets.delete(a),
        confirm="delete_asset", question=f"Delete {asset.name}?",
        command=f"delete asset {asset.hash[:8]}")
        for asset in _mine(ctx) if not assets.uses_of(asset)]


SUBJECTS = [
    Subject(
        "assets", ("assets", "asset"),
        uses={"view": Use(view_run, view_items, offered=_has_account),
              "create": Use(create_run, create_items, offered=_has_account),
              "edit": Use(edit_run, edit_items, offered=_has_account),
              "delete": Use(delete_run, delete_items, offered=_has_account)},
        help="Files the game keeps -- world documents now, sounds and images "
             "later -- with who added each, and your quota.",
    ),
    Subject(
        "quota", ("quota",),
        uses={"edit": Use(lambda cmd, ctx, words: _edit_quota(
            cmd.caller, account_of(cmd.caller), words),
            lambda ctx: [], offered=_admin)},
        help="How much of the server's disk one account may use for assets.",
    ),
]
