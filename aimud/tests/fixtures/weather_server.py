"""
A small MCP server for the tests: one tool of every shape a rule meets.

Served in process by `tests.support.serving`, and as a real process by the one
stdio test, which runs this file. Nothing here touches the network.

* `forecast` looks outward and answers in structure, with a bounded field (an
  enum, so it can become a state) and a numeric one (a trait).
* `roll` is contained: the server says nothing leaves the machine.
* `send_postcard` says nothing about itself, so it is guessed to act outward,
  and it counts what it was sent so a test can see it was sent once.
* `pubs` answers in text only, which can be told or become a description.
* `ledger` takes a nested object, which no rule's arguments can fill.
* `flaky` fails as a tool, which is a reached service saying no.
"""

import logging
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import BaseModel

server = MCPServer("weather")

# `flaky` failing is the point of it; the server's own traceback for each
# failure is noise in a test run.
logging.getLogger("mcp.server").setLevel(logging.CRITICAL)
logging.getLogger("fastmcp").setLevel(logging.CRITICAL)

#: What `send_postcard` was sent, in order: the proof a test reads.
SENT = []


class Forecast(BaseModel):
    conditions: Literal["sunny", "rain", "storm"]
    high_c: float


#: What `forecast` answers, by city; a test may change it.
WEATHER = {"london": ("rain", 12.0), "lisbon": ("sunny", 24.0)}


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=True))
def forecast(city: str) -> Forecast:
    """Gets today's forecast for a city."""
    conditions, high = WEATHER.get(city.strip().lower(), ("storm", 3.0))
    return Forecast(conditions=conditions, high_c=high)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=False,
                                         idempotentHint=True))
def roll(sides: int = 6) -> str:
    """Rolls a die with this many sides. Always the highest, for testing."""
    return str(sides)


@server.tool()
def send_postcard(to: str, text: str) -> str:
    """Sends a postcard to somebody in the real world."""
    SENT.append((to, text))
    return f"Sent to {to}."


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=True))
def pubs(near: str) -> str:
    """Finds pubs near a place."""
    return f"Near {near}: The Lamb, The Eagle, The Dove."


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def ledger(entry: dict) -> str:
    """Takes a nested object, which no rule can fill."""
    return "ok"


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=False))
def flaky(why: str = "") -> str:
    """Always fails."""
    raise ValueError(why or "it always fails")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=True))
def search(query: str, include_domains: list[str] | None = None,
           time_relative: Literal["day", "week", "month"] | None = None,
           tuning: dict | None = None) -> str:
    """
    Shaped as kagi's own search is: every optional parameter is `X | None`,
    which the SDK writes as anyOf with null. `tuning` is optional and no rule
    can fill it, so it is left out rather than refusing the tool.
    """
    return f"{query}|{include_domains}|{time_relative}"


@server.tool(annotations=ToolAnnotations(readOnlyHint=True,
                                         openWorldHint=False))
def where() -> str:
    """Says where this process is running and what it calls home."""
    import os

    return f"{os.getcwd()}|{os.environ.get('HOME', '')}"


if __name__ == "__main__":
    server.run()
