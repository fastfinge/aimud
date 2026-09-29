"""
Who an agent is, and what it is allowed to be.

Phase 2 of docs/mcp.md. An agent reaches the game over MCP and has to say who
it is before anything else happens. What it says is a token, minted here and
kept on the account it belongs to.

**A token is the account.** It is not a scoped credential and this module does
not pretend otherwise: an agent holding one can do everything the account can,
including spending its API key. §4.2 of the plan says so, the help text on
`settings agenttoken` says so, and the reason the plan recommends giving an
agent an account of its own is that an account can be given fewer permissions
and a token cannot.

The token is generated rather than typed, because a token somebody chooses is
a password again. It is compared in constant time, because a token compared
with `==` leaks its own prefix to anybody willing to ask often enough.

Nothing here opens a socket or knows what MCP is. `server/conf/mcp_protocol.py`
is the transport and runs in the Portal; this runs in the Server, where the
database is.
"""

import hmac
import secrets

from evennia.utils import logger

#: Where a token is kept on the account. Named in `exchange.LEFT`: it is a
#: secret and an account's own, and a world document holds neither.
TOKEN_ATTR = "agent_token"

#: How many bytes of randomness a token carries before encoding. 32 bytes is
#: 256 bits, which is the same bar the rest of the world uses for a bearer
#: credential that never expires.
TOKEN_BYTES = 32

#: What a token is prefixed with, so one found in a config file, a log or a
#: pasted traceback is recognisable as this game's and can be revoked rather
#: than puzzled over.
TOKEN_PREFIX = "aimud_agent_"


def mint(account):
    """
    A new token for this account, replacing whatever it had.

    Returns the token in the clear. This is the only moment it is ever
    readable: everything afterwards shows it masked, because a secret that can
    be read back is a secret sitting in the scrollback of whoever last looked.
    """
    token = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    account.attributes.add(TOKEN_ATTR, token)
    logger.log_info(f"agent token minted for {account}")
    return token


def clear(account):
    """Take away this account's token. Any agent using it is on its own."""
    account.attributes.remove(TOKEN_ATTR)
    logger.log_info(f"agent token cleared for {account}")


def token_of(account):
    """The account's token, or None. For masking, never for comparing."""
    return account.attributes.get(TOKEN_ATTR)


def account_for(token):
    """
    Whose token this is, or None.

    Every account holding a token is compared against, and every comparison is
    `hmac.compare_digest`, so the work done is the same whether the first
    character matches or the last. The loop is over accounts that have a token
    at all, which on a mud of this size is a handful and on a mud of any size
    is still far fewer than the accounts.
    """
    if not token or not isinstance(token, str):
        return None
    for account in _accounts_with_tokens():
        held = account.attributes.get(TOKEN_ATTR)
        if isinstance(held, str) and hmac.compare_digest(held, token):
            return account
    return None


def _accounts_with_tokens():
    """Every account holding a token, asked of the database once."""
    from evennia.accounts.models import AccountDB

    return AccountDB.objects.filter(
        db_attributes__db_key=TOKEN_ATTR).distinct()


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------

def warn_displaced(session, account):
    """
    Tell whoever is already playing as this account that they are about to be
    dropped, and by what.

    Displacement is Evennia's, not ours: one character per account means
    `sessionhandler.login` disconnects the sessions that were here first, the
    same as logging in from a second terminal. What this game adds is the
    reason, because somebody thrown out of a half-answered menu by their own
    tooling should not have to guess. §4.3.
    """
    for other in account.sessions.all():
        if other is session or not other.logged_in:
            continue
        other.msg("|yAn agent connected with your token. It takes the "
                  "character from here; you are being disconnected.|n")


def greeting(account):
    """What an agent is told once it is in. MCP shows this as instructions."""
    return (
        f"Connected to aimud as {account.key}. You are playing a text mud, "
        "typing at it with the `send` tool exactly as a person would. "
        "Everything this game can do is reachable by typing, menus included: "
        "`help` lists commands, `look` describes where you are, and a menu "
        "tells you what to type next. Use `poll` to hear what happens while "
        "you are not typing.")


# ---------------------------------------------------------------------------
# Tools the Server owns
# ---------------------------------------------------------------------------

def tool_schemas(session):
    """
    Every tool this session is offered beyond `send` and `poll`, as MCP
    describes a tool.

    Filled in by phases 4 and 5 of docs/mcp.md: the world document, and the
    lookups `world/lookups.py` already collects. Empty until then, which is a
    complete and honest answer -- an agent with `send` alone can already play
    and build, because everything is reachable by typing.
    """
    return []


def run_tool(session, name, args):
    """
    Run one tool and answer `(what to say, whether it went wrong)`.

    Never raises: the Portal is holding a request open, and a traceback that
    reaches nobody is a timeout with no reason attached.
    """
    return f"No tool called {name!r}.", True
