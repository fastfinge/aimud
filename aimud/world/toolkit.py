"""
Every tool this game defines, gathered, and what kind each one is.

Phase 6 of docs/archived/mcp.md. `world/lookups.py` gathers the lookups and has since
the tool loops were built; this gathers everything -- the lookups, the tools a
character acts with, and the finish tools a generator answers through -- so
that one question can be asked of the whole game at once: *what tools are
there, and who may call each?*

Asked by two things, and it exists because of the first:

* **The guard** (`tests/test_agents.py`). An agent is offered tools, and the
  way that surface rots is somebody adding a tool beside the register it reads
  and nobody being asked whether an agent should have it. The guard walks this
  register, so a new tool is a decision rather than a silence.
* **The documentation an agent reads** (`world/manual.py`). A page listing what
  can be done here is written from the tools that exist, not from a copy of
  their names that drifts.

**Two accessors, and a module may have either or both.** `lookup_tools()` has
answered for the lookups since before this module existed and keeps that job;
`tools()` is for everything else a module defines. Nothing forwards: a module
whose only tools are lookups needs no `tools()` at all, for the reason the
makers never grew a `record()` -- fourteen functions each forwarding to the
reader beside it is not a register, it is a second place to forget something.

**A tool with no handler is a declaration.** Most finish tools cannot exist
without a live generator around them: `item_gen.item_tool` needs to know which
item, `rule_gen.rules_tool` which action, `verb_gen.narration_tool` which
attempt. Their *identity* -- the name, the kind, what they are for -- is fixed
all the same, and that is what a register wants. So a module declares those:
a `Tool` with a description and no handler, which `Tool.runnable` reports as
not callable and nothing will ever try to run. What varies per call is the
wording and the enums, and those were never the register's business.

The AST test in `tests/test_agents.py` is what stops a declaration drifting
from the tool it declares: it reads every `tb.Tool("...")` in `world/` and
fails when a name is built but not declared, or declared but never built.
"""


#: Modules that define a tool which is not a lookup. `lookups.MODULES` already
#: names every module with a lookup in it, and `modules()` adds these to it
#: rather than listing them again -- a second copy of that list is a thing to
#: forget, and forgetting it would take a module's lookups off this register
#: and so out of an agent's hands, silently.
ALSO = (
    "agents", "fact_gen", "item_gen", "quest_gen", "suggest", "suggesting",
    "verb_gen", "worldgen",
)


def modules():
    """Every module that defines a tool, in one list and without repeats."""
    from world import lookups

    found = list(lookups.MODULES)
    found.extend(name for name in ALSO if name not in found)
    return tuple(found)


def every_tool():
    """
    `{name: Tool}` for every tool in the game, lookups and all.

    A name is claimed once. Two modules defining a tool of one name would mean
    whichever was imported later silently won, so `tests/test_agents.py`
    refuses it rather than letting the register pick.
    """
    import importlib

    found = {}
    for name in modules():
        module = importlib.import_module(f"world.{name}")
        for accessor in ("lookup_tools", "tools"):
            among = getattr(module, accessor, None)
            if among is None:
                continue
            for tool in among():
                found[tool.name] = tool
    return found


def by_kind():
    """`{kind: [Tool]}`, each list by name, for anything that lists tools."""
    found = {}
    for _name, tool in sorted(every_tool().items()):
        found.setdefault(tool.kind, []).append(tool)
    return found


def where_defined():
    """
    `{name: [module]}` for every tool, read off the modules themselves.

    Used by the guard to say which file to go and look at, and to catch a name
    claimed twice.
    """
    import importlib

    found = {}
    for name in modules():
        module = importlib.import_module(f"world.{name}")
        for accessor in ("lookup_tools", "tools"):
            among = getattr(module, accessor, None)
            if among is None:
                continue
            for tool in among():
                found.setdefault(tool.name, []).append(f"world/{name}.py")
    return found
