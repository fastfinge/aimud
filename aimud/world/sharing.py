"""
Whether somebody else may stand in a world, and what that changes.

A world is its creator's. Sharing one opens it to every account on this
server: they can enter it, play in it and talk to its people, and everything
a model does for them there is paid for by the creator -- while the creator
is logged in, and not at all otherwise. That last part is `sponsor.present`,
and it is what makes sharing safe to switch on: logging out stops all
spending, whoever is visiting.

This module is the one place that says what shared means, the way
`world.activity` holds how a world runs and `world.permits` what it may make.
docs/archived/shared-worlds.md.
"""

#: Where a world keeps whether it is shared. Absent means not, so every world
#: made before this existed is unshared with nothing written.
ATTR = "shared"


def is_shared(world_root):
    """Whether accounts other than its creator may enter this world."""
    if world_root is None:
        return False
    return bool(getattr(world_root.db, ATTR, False))


def share(account, world_root, on):
    """
    Share a world, or stop. Returns what to tell whoever asked.

    Checked here as well as by the menu that offers it, so a typed line
    cannot get round the menu: only the creator may, never the superuser.
    Stopping sends every visitor out, since a world that stops being shared
    and keeps strangers inside it is only half closed. docs/archived/shared-worlds.md 3.
    """
    from world import lore, sponsor

    if not sponsor.is_creator(account, world_root):
        return "Only whoever made this world can share it."
    name = lore.title(world_root)
    if on:
        world_root.db.shared = True
        return (f"|w{name}|n is shared. Anybody here can find it under "
                f"|wenter world public|n, and what happens to them in it is "
                f"paid for with your key while you are logged in.")
    world_root.attributes.remove(ATTR)
    sent = send_visitors_out(
        world_root, f"{account.key} has closed {name} to visitors.")
    if sent:
        return (f"|w{name}|n is no longer shared, and the {len(sent)} "
                f"visitor(s) in it have been sent back to the start.")
    return f"|w{name}|n is no longer shared."


def may_enter(account, world_root):
    """
    Whether this account may go into this world.

    Its creator, anybody while it is shared, and the superuser, who may
    already change what any world is made of and has to be able to stand in
    one to do it.
    """
    from world import sponsor

    if account is None or world_root is None:
        return False
    return bool(sponsor.is_creator(account, world_root)
                or is_shared(world_root)
                or getattr(account, "is_superuser", False))


def public_worlds(account):
    """
    Every shared world somebody else made, in a stable order.

    By the creator's name and then by when the world was made, so a number in
    the list means the same world until somebody shares or unshares one --
    which is why the title, not the number, is the dependable way to name one.
    """
    from evennia.objects.models import ObjectDB

    from world import sponsor

    found = []
    for root in ObjectDB.objects.get_by_attribute(key=ATTR, value=True):
        creator = sponsor.creator_of(root)
        if creator is None or creator == account:
            continue
        found.append(root)
    found.sort(key=lambda root: (str(sponsor.creator_of(root).key).lower(),
                                 root.id))
    return found


def rooms_of(world_root):
    """Every room of this world."""
    from evennia import search_tag

    return list(search_tag(str(world_root.id), category="ai_world"))


def visitors_in(world_root):
    """
    Player characters in this world whose account did not make it.

    Characters rather than accounts, because it is a body that is standing
    somewhere. A character nobody puppets is still a visitor: it is a
    stranger's body left in somebody else's world.
    """
    from evennia.objects.objects import DefaultCharacter

    from world import sponsor

    creator = sponsor.creator_of(world_root)
    found = []
    for room in rooms_of(world_root):
        for obj in room.contents:
            if not isinstance(obj, DefaultCharacter) or obj.db.is_npc:
                continue
            if getattr(obj, "account", None) == creator and creator is not None:
                continue
            found.append(obj)
    return found


def send_visitors_out(world_root, why):
    """Move every visitor to the start room, telling them why. Returns them."""
    from commands.world_subject import start_room

    destination = start_room()
    sent = []
    for character in visitors_in(world_root):
        character.msg(f"|y{why}|n")
        if destination is not None:
            character.move_to(destination, quiet=True)
        sent.append(character)
    return sent


def tell_visitors(account, text):
    """
    Tell everybody visiting this account's shared worlds something, once.

    For the creator logging out and coming back: the moment spending stops
    and starts again, which a visitor otherwise finds out by trying a door.
    Returns how many were told.
    """
    from evennia.objects.models import ObjectDB

    told = 0
    for world_id in list(getattr(account.db, "created_worlds", None) or []):
        root = ObjectDB.objects.filter(id=world_id).first()
        if root is None or not is_shared(root):
            continue
        for character in visitors_in(root):
            character.msg(f"|y{text}|n")
            told += 1
    return told


def carry(old_root, new_root):
    """
    Keep a world shared across a reset, which builds it a new root.

    `shared` is never in a world's document, so a rebuilt world would arrive
    unshared -- with its visitors already moved into it. Called before the
    old root is cleared, while it can still be asked.
    """
    if new_root is not None and is_shared(old_root):
        new_root.db.shared = True
