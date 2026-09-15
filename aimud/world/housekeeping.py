"""
Clearing up the rows that deleting something leaves behind.

Deleting an object takes its own row with it, and the join rows tying it to
its attributes and tags -- but not the attribute and tag rows themselves.
Both are shared by design: one "wieldable" tag row is pointed at by every
wieldable thing in every world, which is what makes tagging cheap to search
and impossible to tidy on the way past, because the thing being deleted
cannot know whether it was the last one holding on. So when the last holder
goes, the row stays, referenced by nothing and found by nothing. Better than
half the tag rows in a world that has generated and deleted a few worlds are
that kind of leftover.

Nothing here reclaims dbrefs, and nothing should. A dbref is identity in this
game, written down in places the database knows nothing about: a character's
memories live in a directory named for one, rooms are tagged into a world by
their root's, the coordinate index maps cells to them, quests name their
giver by one and zones keep rosters of them. None of those are versioned, so
handing a dead number to a new object would quietly give it a dead
character's memories or fold it into a world that no longer exists. There is
nothing to gain by trying: dbrefs come from an AUTOINCREMENT column with room
for nine and a bit billion billion of them, and this game has issued four
thousand.
"""


def _unreferenced(model):
    """
    Every row of `model` that nothing points at.

    Which relations count is read off the model rather than written down
    here. Listing them is the dangerous way round: miss one -- messages and
    help entries carry tags as well as objects do, and a later Evennia may
    tag something new again -- and this deletes rows that are still in use.
    Asking the model means a relation we have never heard of still protects
    its rows.
    """
    joins = {
        f"{rel.field.related_query_name()}__isnull": True
        for rel in model._meta.related_objects
        if rel.many_to_many
    }
    if not joins:
        # Nothing in the schema refers to this at all, which is not a table
        # full of garbage -- it is a table we have misunderstood.
        return model.objects.none()
    return model.objects.filter(**joins)


def collect_orphans():
    """
    Delete the tag and attribute rows nothing refers to. Returns (tags, attrs).

    Called at server start rather than from the sleep script, and the
    difference is the whole safety of it. Attaching a tag is two steps -- the
    row is created, then joined to the thing that wanted it -- and in the
    moment between them the row is indistinguishable from garbage. A sweep
    running in a live game would eventually land in that gap and delete a tag
    out from under the object asking for it. At startup there is nothing else
    running to race with.

    What is deleted is recreated on demand: a tag is looked up by key and
    category and made if it is missing, so removing one nothing holds costs
    at most the insert that brings it back.
    """
    from evennia.typeclasses.attributes import Attribute
    from evennia.typeclasses.tags import Tag

    stale_tags = _unreferenced(Tag)
    tags = stale_tags.count()
    if tags:
        stale_tags.delete()

    # Attributes go one at a time, because they are idmapper-cached and only
    # the instance's own delete() takes it out of that cache -- a queryset
    # delete would leave the row gone and a ghost of it in memory. They are
    # nearly always a handful: an attribute belongs to one thing, so it is
    # deleted along with it, and these are the few that slipped past.
    attributes = 0
    for attribute in _unreferenced(Attribute):
        attribute.delete()
        attributes += 1

    return tags, attributes


def prune_letter_states():
    """
    Take the one-letter conditions out of every world. Returns (worlds, things).

    A `set_state` effect written `"add": "sharpened"` rather than
    `["sharpened"]` was read a letter at a time, and each letter registered as
    a condition of its own -- so a world in the first soak of the tool loops
    had `d`, `e`, `h`, `s`, `t` and `x` in its vocabulary, none of which means
    anything, none of which any verb sets, and none of which can ever be
    unset. `worldcheck` reported them faithfully and `help x` had nothing to
    say about any of them, because there was nothing to say.

    The reading is repaired at every door now (`model_json.listed`, and the
    length `register_state` refuses), and this clears up after the worlds that
    met it: the register, what the kinds remember, and the things standing in
    them. Startup, beside the orphan sweep, for the same reason -- nothing
    else is running to race with.
    """
    from evennia.objects.models import ObjectDB

    def kept(values):
        return [value for value in (values or []) if len(str(value)) > 1]

    worlds = things = 0
    roots = ObjectDB.objects.filter(
        db_attributes__db_key="state_vocabulary").distinct()
    for root in roots:
        vocabulary = dict(root.db.state_vocabulary or {})
        letters = [slug for slug in vocabulary if len(str(slug)) < 2]
        if letters:
            for slug in letters:
                vocabulary.pop(slug, None)
            root.db.state_vocabulary = vocabulary
            worlds += 1
        # The kinds remember what things of their sort have been in, which is
        # where the letters would otherwise be handed to the next generator.
        specs = dict(root.db.kind_specs or {})
        changed = False
        for kind, spec in specs.items():
            states = (spec or {}).get("states")
            if states is not None and kept(states) != list(states):
                specs[kind] = {**spec, "states": kept(states)}
                changed = True
        if changed:
            root.db.kind_specs = specs

    for obj in ObjectDB.objects.filter(
            db_attributes__db_key="states").distinct():
        standing = list(obj.db.states or [])
        if kept(standing) != standing:
            obj.db.states = sorted(kept(standing))
            things += 1
    return worlds, things
