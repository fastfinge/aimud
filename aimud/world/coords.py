"""
Sparse coordinate index for AI-generated worlds.

Every room in a world sits at an integer ``(x, y, z)``.  The world root holds a
dict mapping ``"x,y,z"`` to a room id, so "is there already a room north of
here?" is a lookup rather than a graph walk.

The index is deliberately sparse and unbounded.  A world's size is not known
when it is created -- a generated room may introduce exits nobody declared --
so there is no grid, no extent and no limit.  Keys exist only where rooms
exist, and coordinates run negative in every direction.

Two rooms never share a cell.  That is the whole point: when a player walks
toward an occupied cell we link to the room already there instead of
generating a second one, which is what lets a world close back on itself.
"""

# Unit vector per direction.  "in" and "out" are portals: they connect rooms
# without displacing them, so they have no vector and are excluded here.
DIRECTION_VECTORS = {
    "north":     (0,  1,  0),
    "south":     (0, -1,  0),
    "east":      (1,  0,  0),
    "west":      (-1, 0,  0),
    "northeast": (1,  1,  0),
    "northwest": (-1, 1,  0),
    "southeast": (1, -1,  0),
    "southwest": (-1, -1, 0),
    "up":        (0,  0,  1),
    "down":      (0,  0, -1),
}

ORIGIN = (0, 0, 0)


def coord_key(coord):
    """Serialise a coordinate tuple to the string form used as a dict key."""
    x, y, z = coord
    return f"{int(x)},{int(y)},{int(z)}"


def parse_key(key):
    """Inverse of coord_key."""
    x, y, z = key.split(",")
    return (int(x), int(y), int(z))


def step(coord, direction):
    """
    The coordinate reached by leaving `coord` in `direction`, or None when the
    direction does not displace the player (a portal such as "in"/"out", or a
    labelled exit with no compass sense).
    """
    from world.worldgen import canonical_direction

    vector = DIRECTION_VECTORS.get(canonical_direction(direction) or "")
    if vector is None:
        return None
    return (coord[0] + vector[0], coord[1] + vector[1], coord[2] + vector[2])


# ---------------------------------------------------------------------------
# Index access -- the world root owns the map
# ---------------------------------------------------------------------------

def get_index(world_root):
    """Return the world's {coord_key: room_id} dict (never None)."""
    return (world_root.db.room_coords or {}) if world_root else {}


def get_coord(room):
    """Return a room's coordinate tuple, or None if it has not been placed."""
    stored = room.db.coord
    return tuple(stored) if stored else None


def place(world_root, room, coord):
    """
    Record `room` at `coord`, on the room and in the world index.

    Returns the coordinate placed.  A cell already holding a different room is
    left alone -- callers should test with room_at() first; this only guards
    against corrupting an index through a double-placement.
    """
    if world_root is None:
        return None
    index = dict(get_index(world_root))
    key = coord_key(coord)
    existing = index.get(key)
    if existing is not None and existing != room.id:
        return get_coord(room)
    index[key] = room.id
    world_root.db.room_coords = index
    room.db.coord = tuple(coord)
    return tuple(coord)


def room_at(world_root, coord):
    """Return the room occupying `coord`, or None if the cell is free."""
    if world_root is None or coord is None:
        return None
    room_id = get_index(world_root).get(coord_key(coord))
    if room_id is None:
        return None
    from evennia.objects.models import ObjectDB

    room = ObjectDB.objects.filter(id=room_id).first()
    if room is None:
        # The room was deleted; drop the stale cell so the space frees up.
        index = dict(get_index(world_root))
        index.pop(coord_key(coord), None)
        world_root.db.room_coords = index
    return room


def forget(world_root, room):
    """Remove a room from the index, freeing its cell."""
    if world_root is None:
        return
    coord = get_coord(room)
    if coord is None:
        return
    index = dict(get_index(world_root))
    if index.get(coord_key(coord)) == room.id:
        index.pop(coord_key(coord), None)
        world_root.db.room_coords = index


def neighbours(world_root, coord, radius=1, same_floor=True):
    """
    Rooms within `radius` cells of `coord`, as {(dx, dy, dz): room}.

    Offsets are relative to `coord`, so (0, 1, 0) is the room one step north.
    The centre cell itself is excluded.  With same_floor set, the search stays
    on the current z level, which is what room context wants -- a room above is
    not a neighbour you can see into.
    """
    if world_root is None or coord is None:
        return {}
    found = {}
    zs = [0] if same_floor else range(-radius, radius + 1)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in zs:
                if (dx, dy, dz) == (0, 0, 0):
                    continue
                room = room_at(world_root, (coord[0] + dx, coord[1] + dy, coord[2] + dz))
                if room is not None:
                    found[(dx, dy, dz)] = room
    return found


def free_directions(world_root, coord):
    """Directions out of `coord` whose target cell holds no room yet."""
    return [
        direction
        for direction, vector in DIRECTION_VECTORS.items()
        if room_at(world_root, (coord[0] + vector[0],
                                coord[1] + vector[1],
                                coord[2] + vector[2])) is None
    ]
