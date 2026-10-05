"""
Inputfuncs

Input functions are always called from the client (they handle server
input, hence the name).

This module is loaded by being included in the
`settings.INPUT_FUNC_MODULES` tuple.

All *global functions* included in this module are considered
input-handler functions and can be called by the client to handle
input.

An input function must have the following call signature:

    funcname(session, *args, **kwargs)

Where session will be the active session and *args, **kwargs are extra
incoming arguments and keyword properties.

A special command is the "default" command, which is will be called
when no other match is found.

Its call signature is

    default(session, cmdname, *args, **kwargs)

Available functions are found in `evennia.server.inputfuncs`.

---

**The Server end of MCP.** `server/conf/mcp_protocol.py` runs in the Portal,
has no database and is not allowed one; everything it needs to know about who
somebody is, or what the game holds, is asked for here. The two functions
below are the whole of that seam, and they are inputfuncs rather than
something new because that is how structured messages already travel from a
protocol into the game -- the same road GMCP and MSDP take. See docs/archived/mcp.md
§3.4.
"""


def mcp_auth(session, token="", **kwargs):
    """
    Log an MCP session in by its token, and tell the Portal what happened.

    The verdict always goes back, refusal included, because the Portal is
    holding an HTTP request open waiting for it and a silence would become a
    timeout with nothing said. §4.

    Logging in is `sessionhandler.login`, the same call the webclient and
    telnet make, which is what makes an agent's session an ordinary one. With
    one character per account that call also disconnects whatever else was
    logged in as this account -- displacement, which this game did not invent
    and does not override; the only thing added here is saying why (§4.3).
    """
    from world import agents

    if session.logged_in:
        session.msg(mcp_auth=((False, "That session is already connected."),
                              {}))
        return

    account = agents.account_for(token)
    if account is None:
        session.msg(mcp_auth=((False, "That token is not known. Type "
                                      "`settings agenttoken` in the game to "
                                      "mint one."), {}))
        return

    agents.warn_displaced(session, account)
    session.sessionhandler.login(session, account)
    # The tool list goes first and the verdict second, because the Portal is
    # holding a request open until the verdict arrives and reads the tools in
    # the same breath. Sent the other way round, the tools are still in flight
    # when the reply goes out and an agent is offered `send` and `poll` alone.
    session.msg(mcp_tools=((agents.tool_schemas(session),), {}))
    session.msg(mcp_auth=((True, agents.greeting(account)), {}))


def mcp_tool(session, ticket="", name="", args=None, **kwargs):
    """
    Run one tool the Server owns and send its answer back by ticket.

    The ticket is how a reply is matched to the call that asked for it: an
    agent may have one call in flight, but a slow lookup and a fast one
    answering out of order would otherwise be told apart by nothing.
    """
    from world import agents

    try:
        said, failed = agents.run_tool(session, name, args or {})
    except Exception:
        from evennia.utils import logger

        logger.log_trace()
        said, failed = "Something went wrong running that tool.", True
    session.msg(mcp_tool=((ticket, said, failed), {}))
