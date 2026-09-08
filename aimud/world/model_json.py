"""
Reading JSON back out of a model that very nearly wrote some.

Every generator in this game asks a model for a JSON object and then parses
it, and models are good at that until they are not: a trailing comma before
the closing brace, a `//` note explaining a field, `True` where `true` was
meant, an answer that stopped mid-sentence because it hit the token limit.
Each of those is one character away from valid and none of them are worth
losing a room, an item or an NPC over -- especially since the retry costs
another call and often comes back with the same comma in it.

So this module repairs before it gives up. It scans the text once, tracking
whether it is inside a string, and fixes what it can see: comments and
trailing commas are dropped, Python's literals become JSON's, unquoted keys
and single- or smart-quoted strings get real double quotes, and a response
that was cut off has its open brackets closed. The scan is what makes this
safe -- a comma inside a description is a comma, not a syntax error, and
nothing here touches the inside of a string except to make it quotable.

When even that fails, the error names the offending line and the raw response
goes to the log, because "Expecting property name enclosed in double quotes:
line 44 column 9" tells whoever is playing precisely nothing.
"""

import json

from evennia.utils import logger

#: What closes a string that did not open with a plain double quote. Models
#: reach for these when they are writing prose rather than data.
_CLOSERS = {
    "'": "'",
    '"': '"',
    "“": "”",
    "‘": "’",
}

#: Bare words that mean something in JSON once they are spelled its way.
#: NaN and Infinity are accepted by Python's parser but by very little else,
#: and a number nothing can compare against is no more use than a missing one.
_LITERALS = {
    "true": "true",
    "false": "false",
    "null": "null",
    "none": "null",
    "nil": "null",
    "nan": "null",
    "infinity": "null",
    "undefined": "null",
}

#: How much of a hopeless response to quote back. Enough to recognise, short
#: enough that it does not fill somebody's screen.
_EXCERPT = 400


def parse_object(content):
    """
    Parse a model response that should be a single JSON object.

    Returns the value unchanged if it has already been parsed, which is what
    a structured-output model hands back.
    """
    return _parse(content, "{", "}")


def parse_array(content):
    """Parse a model response that should be a single JSON array."""
    return _parse(content, "[", "]")


def _parse(content, opener, closer):
    if not isinstance(content, str):
        return content

    text = _strip_fence(content)

    # The overwhelmingly common case: it is just JSON.
    try:
        return json.loads(text)
    except ValueError:
        pass

    # Models like to introduce their answer. Take everything between the
    # first opening bracket and the last closing one; if the answer was cut
    # off there is no closing one, so take the rest.
    start = text.find(opener)
    if start < 0:
        raise ValueError(_no_json(content))
    end = text.rfind(closer)
    span = text[start:end + 1] if end > start else text[start:]

    try:
        return json.loads(span)
    except ValueError:
        pass

    repaired = _repair(span)
    try:
        return json.loads(repaired)
    except ValueError as exc:
        logger.log_err(f"Unparseable model JSON:\n{content}")
        raise ValueError(_unrepairable(repaired, exc)) from exc


def _strip_fence(text):
    """Drop a ```json ... ``` wrapper, which is not part of the answer."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    body = text[3:]
    newline = body.find("\n")
    if newline >= 0 and not body[:newline].strip().startswith(("{", "[")):
        body = body[newline + 1:]  # the language tag on the opening fence
    fence = body.rfind("```")
    return (body[:fence] if fence >= 0 else body).strip()


#: What a literal control character inside a string has to become for the
#: string to survive being double-quoted.
_ESCAPES = {"\r": "", "\n": "\\n", "\t": "\\t"}

#: The only characters JSON lets a backslash introduce.
_VALID_ESCAPES = '"\\/bfnrtu'


def _escape(char):
    """
    Rewrite one backslash escape as one JSON accepts.

    A model writing a single-quoted string escapes the apostrophe in it, and
    `\\'` is not an escape JSON has heard of. Anything else unrecognised was
    meant as a literal backslash -- `\\d` in a pattern, a Windows path -- so
    the backslash is doubled rather than dropped, which keeps the character
    the model wrote.
    """
    if not char:
        return ""  # a backslash was the last thing the answer got out
    if char in "'‘’":
        return char
    if char in "“”":
        return '\\"'
    if char in _VALID_ESCAPES:
        return "\\" + char
    return "\\\\" + char


def _repair(text):
    """
    Rewrite `text` as the JSON it was trying to be.

    One pass, left to right, carrying two pieces of state: whether we are
    inside a string (because nothing is a syntax error in there) and which
    brackets are still open (so a truncated answer can be closed).
    """
    out = []
    stack = []
    quote = ""
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if quote:
            if char == "\\":
                out.append(_escape(text[index + 1:index + 2]))
                index += 2
                continue
            if char == quote:
                out.append('"')
                quote = ""
                index += 1
                continue
            if char == '"':
                # A real quote inside a string that opened with something
                # else. It needs escaping now that the string is a
                # double-quoted one.
                out.append('\\"')
                index += 1
                continue
            if char in _ESCAPES:
                out.append(_ESCAPES[char])
                index += 1
                continue
            out.append(char)
            index += 1
            continue

        if char in _CLOSERS:
            quote = _CLOSERS[char]
            out.append('"')
            index += 1
            continue

        if text.startswith("//", index) or char == "#":
            newline = text.find("\n", index)
            index = length if newline < 0 else newline
            continue

        if text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = length if close < 0 else close + 2
            continue

        if char == ",":
            # A trailing comma is one the next thing along closes.
            ahead = index + 1
            while ahead < length and text[ahead].isspace():
                ahead += 1
            if ahead < length and text[ahead] in "}]":
                index += 1
                continue
            out.append(char)
            index += 1
            continue

        if char in "{[":
            stack.append("}" if char == "{" else "]")
            out.append(char)
            index += 1
            continue

        if char in "}]":
            if stack:
                stack.pop()
            out.append(char)
            index += 1
            continue

        if char.isalpha() or char == "_":
            end = index
            while end < length and (text[end].isalnum() or text[end] in "_-"):
                end += 1
            word = text[index:end]
            literal = _LITERALS.get(word.lower())
            if literal:
                if out and out[-1] in "+-":
                    out.pop()  # -Infinity is not a negative null
                out.append(literal)
            elif index and (text[index - 1].isdigit() or text[index - 1] in ".+-"):
                out.append(word)  # the exponent of 1e5, not a bare word
            else:
                out.append(f'"{word}"')
            index = end
            continue

        out.append(char)
        index += 1

    if quote:
        out.append('"')  # the answer stopped mid-sentence

    return _close(out, stack)


def _close(out, stack):
    """Tidy off a truncated answer and shut the brackets it left open."""
    body = "".join(out).rstrip()
    while body and body[-1] in ",:":
        if body[-1] == ":":
            body = _drop_dangling_key(body)
        else:
            body = body[:-1].rstrip()
    return body + "".join(reversed(stack))


def _drop_dangling_key(body):
    """Remove a `"key":` that never got a value, and the comma before it."""
    body = body[:-1].rstrip()
    if body.endswith('"'):
        opening = body.rfind('"', 0, len(body) - 1)
        if opening >= 0:
            body = body[:opening].rstrip()
    return body


def _no_json(content):
    return f"The model answered with no JSON at all: {_excerpt(content)}"


def _unrepairable(repaired, exc):
    lines = repaired.splitlines()
    line = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
    where = f" near {line.strip()!r}" if line.strip() else ""
    return f"The model's JSON could not be repaired: {exc.msg}{where}"


def _excerpt(content):
    text = str(content).strip()
    return repr(text if len(text) <= _EXCERPT else text[:_EXCERPT] + "...")
