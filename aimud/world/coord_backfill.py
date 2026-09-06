"""
Assign coordinates to worlds that were generated before the coordinate index.

Walks each world outward from its root, following exits and stepping one cell
per direction.  Rooms reached by a labelled or portal exit get no coordinate --
they have no compass sense, so they stay unplaced and simply generate as before.

Collisions are expected and informative: two rooms landing on one cell is
exactly the duplication the index exists to prevent, and the second room keeps
its place in the world but stays off the map. Run `report()` to see them
without writing anything.
"""

from collections import deque

from world import coords
from world.worldgen import canonical_direction


def _walk(root):
    """
    Breadth-first walk from `root`, yielding (room, coord, collided_with).

    collided_with is the room already claiming that cell, or None when the
    placement is clean.
    """
    placed = {coords.ORIGIN: root}
    yield root, coords.ORIGIN, None

    queue = deque([(root, coords.ORIGIN)])
    seen = {root.id}

    while queue:
        room, coord = queue.popleft()
        for ex in room.contents:
            target = getattr(ex, "destination", None)
            if target is None or target is room or target.id in seen:
                continue
            if ex.db.pending_generation:
                continue
            direction = canonical_direction(ex.key)
            if direction is None:
                continue
            step = coords.step(coord, direction)
            if step is None:
                continue

            clash = placed.get(step)
            yield target, step, clash
            seen.add(target.id)
            if clash is None:
                placed[step] = target
                queue.append((target, step))


def _worlds():
    """Every AI world root in the database."""
    from evennia.objects.models import ObjectDB

    return [
        o for o in ObjectDB.objects.all()
        if o.db_destination is None and o.db.is_world_root
    ]


def report():
    """Print what a backfill would do, changing nothing."""
    for root in _worlds():
        rows = list(_walk(root))
        clashes = [(r, c, k) for r, c, k in rows if k is not None]
        print(f"\n[{root.key}] (#{root.id}) -- {len(rows)} rooms reachable, "
              f"{len(clashes)} collision(s)")
        for room, coord, clash in clashes:
            print(f"    {coord} wanted by {room.key!r} (#{room.id}), "
                  f"already held by {clash.key!r} (#{clash.id})")


def run():
    """Assign coordinates. Idempotent: re-running places the same rooms."""
    total, collided = 0, 0
    for root in _worlds():
        for room, coord, clash in _walk(root):
            if clash is not None:
                collided += 1
                continue
            coords.place(root, room, coord)
            total += 1
    print(f"placed {total} room(s); {collided} left unplaced due to collisions")
    return total, collided
