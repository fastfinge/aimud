"""
The manual an agent reads, written for something that is about to use it.

The surviving half of the `future-plans.md` ACP item, and phase 8 of
docs/archived/mcp.md. The README tells a person how to switch the endpoint on; this
tells whatever connects to it what there is to do here. Two different readers
wanting two different documents, which is why this is not a copy of the README.

**Half of it is generated, and that half is the half that would rot.** The
tools, the commands, the things a world can be made of, the effects a rule may
use: every one of those is a register this game already keeps, and a page
listing them by hand would be wrong within a month -- the way
`preferences.help_entries` builds a topic per setting rather than somebody
writing fourteen of them. The prose is what a register cannot say: what a
world *is*, why building goes through menus, what an agent is expected to do
with a document.

**One tool, `manual`.** A page at a time rather than everything at once,
because the whole thing is longer than any one answer may be and most of it is
not what was wanted. Defined here as a lookup, so `world/lookups.py` gathers
it and an agent is offered it with nothing wired up -- the same road every
other lookup takes.
"""


#: The page an agent is pointed at first, named in `agents.greeting`.
FIRST = "start"


def contents():
    """`[(key, title)]` for every page, in the order they are worth reading."""
    return [(key, page[0]) for key, page in PAGES.items()]


def page(key):
    """
    One page as text, or a complaint naming the pages there are.

    Asked for nothing, it answers the front page: somebody who calls this with
    no argument wants to start reading, and a complaint there would be a
    riddle with the answer in it.
    """
    wanted = str(key or "").strip().lower() or FIRST
    entry = PAGES.get(wanted)
    if entry is None:
        listed = ", ".join(name for name, _title in contents())
        return f"There is no page called that. The pages are: {listed}."
    title, body = entry
    text = body() if callable(body) else body
    return f"{title}\n\n{text.strip()}"


# ---------------------------------------------------------------------------
# The pages that are written
# ---------------------------------------------------------------------------

START = """
You are connected to aimud, a text mud, as an ordinary player. There is no
separate API for agents: you type at the game and read what it says, the same
as a person at a terminal.

Two tools do that. `send` types one line and gives you back everything the
game said in reply. `poll` gives you whatever it has said since you last
looked, so you can hear an NPC answer or an errand run out while you were not
typing. Everything else you are offered only reads: they are shortcuts for
questions you could also ask by typing, and they answer as data rather than
prose.

**Everything this game can do is reachable by typing.** Not most of it --
every point in every menu has a command that gets there, and there is a test
that keeps it true. So you never need a tool for an action; you need `send`.

Start with these:

    look                  where you are
    help                  what you can type
    view worlds           the worlds this account has
    enter world 1         go into one
    enter world public    worlds other people here have shared
    view world            what the world you are in is like

A **world** is the unit of everything here. It holds its own rooms, things,
people, words, rules and errands, and one account may have several. You are
either standing in one or standing in the start room outside them all.
A world's creator may share it; whoever made a world pays for what happens
in it, and only while they are logged in.

Menus are how anything gets made or changed. When one opens it tells you what
to type: a number, a word, `b` to go back, `q` to quit, `?` for help on a
choice, `l` to list the choices again. A menu is a conversation -- send one
line, read what it says, send the next.

What to read next:
  `building`   making a world, and everything it can be made of
  `documents`  a world as one JSON file: the fast way to build and to test
  `rules`      how anything in a world comes to behave
  `testing`    driving this game as a test, which is what you are best at
  `extending`  what may be added to the game itself, and what may not
  `tools`      every tool you have, and what each is for
  `commands`   the commands that make, change and read things
  `effects`    the closed list of everything a rule may do
  `services`   what this server lets the game reach outside itself for
"""

BUILDING = """
There are two ways a world comes to exist. A model can generate one, which
costs money and needs an API key; or it can be built by hand, which costs
nothing and is the same world when it is finished. Nothing in building calls a
model, and that is deliberate.

    create world                the wizard: a new world, start to finish
    view worlds                 what this account has
    enter world <n>             go into one
    enter world public <n>      go into one somebody else shared
    view world                  what this one is like
    export world                keep it as a world asset
    view assets                 files the game keeps: worlds, and later sounds
    reset world                 put it back to its restore point
    delete world <n>            permanently

Inside a world, seven verbs do everything: `create`, `edit`, `delete`, `view`,
`reset`, `import`, `export`. Each takes a subject -- `create rule`, `view
kinds`, `edit trait` -- and opens a menu if you do not say enough for it to
act. Typing the verb alone lists what it can act on, which is the quickest way
to find out what a world is made of.

The full list of subjects and of the things you can make is under `commands`.

Two things worth knowing before you build much:

**A world is one document** (`documents`). If you are building something to
test against, write the document instead of answering menus. It is faster by
an order of magnitude and the result is reviewable.

**Nothing in a world is hardcoded.** A thing behaves because a rule says so, a
word means something because the world's vocabulary says so, and a sort of
thing affords what its kind affords. There is no Python to write and none to
be written from in here; see `rules` and `extending`.
"""

DOCUMENTS = """
A whole world reads out as one JSON document and builds again from one. This is
the most useful thing you can do here.

    export_world                    the world you are standing in, as JSON
    export_world world="3"          by its number in `view worlds`
    export_world world="The School" or by its title
    import_world document="{...}"   build a world from one

The document holds everything: rooms and the ways between them, things and
where they sit and whose they are, people and what they want, the world's own
words, its rules, its errands, and what it has learned. Nothing in it is a
database id, a filesystem path, an account or anything executable, so it can
be read, edited by hand and built again anywhere.

It is **the world as it stands**, not as it was authored: a door left open
exports open, a thing moved exports where it was moved to.

`import_world` validates the whole document before it builds anything, and
refuses the lot with every reason if something is wrong -- there is no such
thing as a half-built world. A refusal is a list of complaints; fix them and
send it again.

Neither tool writes a file and neither moves the restore point. A person's
`export world` command does both; these do not, so reading a world out changes
nothing about it.

Two things the document does not carry, because they are not the world's:
memories, and whatever a player was holding (what somebody carried at export
comes back on the floor where they stood).
"""

RULES = """
Everything a world does that is not built into the game is a **rule**, and
rules are data rather than code. One says: at some point in an attempt, when
these conditions hold, do these things.

    view rules            every rule this world has, and its firing order
    show_rule             one rule in full, as data
    view faults           what is wrong with them: rules that can never fire,
                          conditions nothing tests, rules that defeat
                          themselves
    create rule           write one, through a menu
    edit rules            change or suspend one

The pieces a rule is made of, each with a vocabulary a world keeps and you can
read with the tools under `tools`:

  **actions**     what somebody is trying to do. A verb the world knows.
  **kinds**       what sort of thing something is, and what that sort affords
  **traits**      figures a person or thing carries
  **conditions**  states a thing can be in, in named groups
  **effects**     the only ways a rule may change anything

A rule's **phase** decides when it fires: before the attempt (`instead`), as a
condition of it (`check`), as the thing that happens (`carry out`), or
afterwards (`after`). A check rule is a tax on every attempt, so it is worth
knowing that most behaviour belongs in `carry out`.

`world_faults` is the tool worth calling after you write rules. It reports
rules that can never fire, conditions nothing can satisfy, and rules whose
effect undoes their own requirement -- each with which rule to go and edit.
"""

EXTENDING = """
There are hard limits on what can be added from in here, and they are not
incidental.

**No player, character, model or rule can write Python from inside the game.**
Not a sandbox, not a restricted subset: none. Code is added by somebody with
access to the machine putting a file in a directory, and nothing reachable
over this connection can do that. If you find a way to get code to run from
inside a world, that is a bug worth reporting rather than a feature to use.

**Nothing in the game makes an uncontrolled network request.** The ways out
are named and few: a model API on somebody's own key, a service the server's
owner added (`services` says which), a download somebody confirmed. This
connection is one of the ways *in*, not a way out. A service is reached only
through a rule, with the server's own credentials, never yours.

What can be added without code, and where:

  **rulesets**  a bundle of rules, kinds, states and figures a world can
                choose, as a JSON document in a directory the server declares.
                Never code. A world takes one with `edit rulesets`.
  **worlds**    a world document, kept as an asset, as under `documents`.
  **assets**    files the game keeps: `create asset` fetches one from a web
                address, checked by what is in it. Never code.

So the way to make a world do something new is a rule, a kind, a trait or a
word -- and if what you want cannot be expressed that way, that is worth
saying plainly rather than working around. The limit is the design.
"""

TESTING = """
What you are unusually good at here, and the reason this connection exists.

**Build the fixture as a document.** `import_world` with a document you wrote
is one call and gives you a world in a known state. Answering menus to build
the same world is hundreds of turns and is not reviewable afterwards.

**Play it with `send`.** Every command a person can type, in order, reading
what comes back. This is the only way some things can be exercised at all:
the parser, disambiguation, menus, what a rule does when it actually fires.

**Assert with `export_world`.** Read the world out after you have played it
and compare the document with what you expected. The document is the state, so
a diff of two documents is a diff of two worlds.

**Hear what happens on its own with `poll`.** NPCs act between your turns,
errands run out, the clock moves.

Worth knowing:

  * A world in `settings mode none` calls no model at all, so a hand-built
    world imported and played costs nothing and behaves the same way every
    time. Check with `view world`.
  * `world_faults` tells you what is wrong with a world's rules without
    playing it.
  * You are an ordinary session. `who` lists you. An idle connection is
    dropped. One character per account, so connecting takes the character from
    whoever was using it -- if a person is meant to be playing alongside you,
    they need their own account.
  * Nothing you can type is more powerful than what the account could type
    itself. If something is refused, it is refused for a reason worth reading
    rather than a permission worth routing around.
"""


# ---------------------------------------------------------------------------
# The pages that are built
# ---------------------------------------------------------------------------

def _tools_page():
    """Every tool an agent has, off the register, so the page cannot drift."""
    from world import agents, toolbox as tb, toolkit

    lines = [
        "Two tools do things and the rest only read. Every one of these is a "
        "question you could also ask by typing; they answer as data, which is "
        "easier to be sure about.",
        "",
        "  send   type one line, as a player would, and read the reply",
        "  poll   what the game has said since you last looked",
        "",
    ]
    ctx = tb.ToolContext()
    offered = agents.offered_tools(ctx)
    documents = {tool.name for tool in agents.document_tools()}

    lines.append("The world as a document:")
    for name in sorted(documents):
        tool = offered.get(name) or toolkit.every_tool().get(name)
        if tool is not None:
            lines.append(f"  {name}")
            lines.append(f"      {_said(tool, ctx)}")
    lines.append("")

    lines.append("Reading the world and what it knows:")
    for name, tool in sorted(offered.items()):
        if name in documents:
            continue
        lines.append(f"  {name}")
        lines.append(f"      {_said(tool, ctx)}")

    left = {name: why for name, why in agents.NOT_OFFERED.items()}
    if left:
        lines.append("")
        lines.append("Not offered, and why:")
        for name, why in sorted(left.items()):
            lines.append(f"  {name}: {why}.")

    lines.append("")
    lines.append(
        "Some tools appear only where they can answer -- a world's own rules "
        "and words need a world to be standing in. Ask for the list again "
        "after entering one.")
    return "\n".join(lines)


def _said(tool, ctx):
    """What one tool says about itself, in one paragraph."""
    description = tool.description
    if callable(description):
        try:
            description = description(ctx)
        except Exception:
            description = ""
    return " ".join(str(description or "").split())


def _commands_page():
    """The verbs and their subjects, and the makers, off both registers."""
    from commands import subjects
    from world import making

    lines = [
        "Seven verbs act on subjects. Typing a verb with no subject "
        "lists what it can act on; typing one with too little to go on "
        "opens a menu.",
        "",
    ]
    verbs = {}
    for subject in subjects.registered():
        for verb in subject.uses:
            verbs.setdefault(verb, set()).update(subject.words()[:1])
    for verb in sorted(verbs):
        words = ", ".join(sorted(verbs[verb]))
        lines.append(f"  {verb} <subject>")
        lines.append(f"      {words}")

    lines.append("")
    lines.append(
        "What a world can be made of. Each is created, changed, listed and "
        "sometimes deleted through the same four verbs above:")
    lines.append("")
    for maker in making.registered():
        label = maker.label if isinstance(maker.label, str) else maker.key
        lines.append(f"  {maker.key:16} {label}")

    lines.append("")
    lines.append(
        "Settings are per account and per world: `settings` opens them all, "
        "`view settings` reads them, `help <name>` explains any one.")
    return "\n".join(lines)


def _effects_page():
    """The closed list of ways a rule may change anything."""
    from world import effects

    lines = [
        "A rule changes the world only through these. The list is closed on "
        "purpose: it is the whole vocabulary of consequence in this game, and "
        "anything a world does is some arrangement of them.",
        "",
    ]
    vocabulary = getattr(effects, "VOCABULARY", {}) or {}
    for name in sorted(vocabulary):
        entry = vocabulary[name]
        said = entry.get("means") if isinstance(entry, dict) else None
        takes = entry.get("takes") if isinstance(entry, dict) else None
        lines.append(f"  {name}")
        if said:
            lines.append(f"      {' '.join(str(said).split())}")
        if takes:
            lines.append(f"      takes: {' '.join(str(takes).split())}")
    lines.append("")
    lines.append(
        "`create rule` offers these as a menu, with the fields each one "
        "takes. `show_rule` reads one back as data.")
    return "\n".join(lines)


#: The most tools the services page lists before saying where the rest are.
#: A page has to arrive whole, and a server can have a great many.
MOST_SERVICE_TOOLS = 30


def _services_page():
    """What this server may reach outside the game for, off the register."""
    from world import services

    lines = [
        "A service is something the owner of this server let the game reach "
        "outside itself for: an MCP server or an OpenAPI service, added in "
        "the game by an admin, with the server's own credentials and never a "
        "player's.",
        "",
        "Nothing calls a service except a rule. A rule's call_tool effect "
        "names a tool, says where each thing it takes comes from, and where "
        "each part of the answer goes: a condition, a figure, what something "
        "looks like, or told privately to whoever used the verb. It is never "
        "narrated. So you use a tool by typing the verb whose rule calls it, "
        "as anybody does. If it needs to know something, answer in brackets "
        "on the end: forecast [city=Lisbon].",
        "",
        "Each tool is classed by what it does out there. Contained: nothing "
        "leaves the machine. Looks outward: a question goes out. Acts "
        "outward: something out there changes. A character may use any of "
        "them only where somebody pays for a model; a player may use the "
        "first two anywhere and the third where somebody pays.",
        "",
    ]
    usable = services.usable()
    if not usable:
        lines.append("This server has none switched on, so nothing here "
                     "reaches outside the game.")
        return "\n".join(lines)
    lines.append(f"This server offers {len(usable)}:")
    for found, _record, info in usable[:MOST_SERVICE_TOOLS]:
        does = services.does(info)[:100] or "it says nothing about itself"
        lines.append(f"  {found}, {services.said_level(info.get('level'))}: "
                     f"{does}")
    if len(usable) > MOST_SERVICE_TOOLS:
        lines.append(f"  and {len(usable) - MOST_SERVICE_TOOLS} more.")
    lines.append("")
    lines.append("view services lists them; view service <name> says what "
                 "each takes and gives back, in full.")
    return "\n".join(lines)


#: Every page, in the order they are worth reading. Key, then (title, body);
#: a body is either the text or something that builds it off a register.
PAGES = {
    "start": ("aimud: what this is and how to use it", START),
    "building": ("Building a world", BUILDING),
    "documents": ("A world as one document", DOCUMENTS),
    "rules": ("Rules: how a world comes to behave", RULES),
    "testing": ("Driving this game as a test", TESTING),
    "extending": ("What may be added, and what may not", EXTENDING),
    "tools": ("Every tool you have", _tools_page),
    "commands": ("Commands, subjects and what can be made", _commands_page),
    "effects": ("Everything a rule may do", _effects_page),
    "services": ("What this server may reach outside the game for",
                 _services_page),
}


# ---------------------------------------------------------------------------
# The tool (docs/archived/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`manual`: the documentation, a page at a time."""
    from world import toolbox as tb

    listed = ", ".join(f"{key} ({title})" for key, title in contents())

    def reading(ctx, args, answer):
        answer(page(args.get("page") or FIRST))

    return [tb.Tool(
        "manual",
        f"How this game works, written for an agent using it, a page at a "
        f"time. Start with '{FIRST}'. The pages are: {listed}.",
        tb.params({"page": {"type": "string", "enum": sorted(PAGES),
                            "description": f"Which page; '{FIRST}' if left "
                                           f"out"}}),
        reading, doing="reading the manual", looks=True)]
