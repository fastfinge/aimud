"""
Filling in a menu field with a model: what `~` does.

A player writing a world's room guidance, or a word list's entries, or how
they look in a world, can ask for a first draft instead. The model is shown
the whole form -- every field's label, what it is for and what it is set to --
so it writes the title for *this* description, not a title.

**One conversation, one answer.** Whether one field or every empty one is
being filled, the model is given a single finish tool with a parameter for
each, and it answers once. Each value goes through the field's own `read`, the
same check a typed value gets, and anything refused is sent back with the
reason for the model to put right -- the loop every generator has used since
docs/generator-tool-loops.md.

**Nothing secret is sent.** A secret field is never offered and never shown
to the model, not even its label. That is decided in `menus.Field`, where
`suggestible` can never be true of a secret.

**Nothing is written here.** What comes back is a proposal; the menu decides
whether to ask first (`suggestion` in the confirmations) and writes it through
the field. This module only asks.

**It costs one conversation each time `~` is used, and nothing otherwise.**
The job is `menus`, so it can be given its own model in `settings models` and
is counted in `view rounds` like every other.
"""

from world import menus as m

#: The job the model is chosen for. See `world.preferences.JOBS`.
JOB = "menus"

#: Rounds a fill may take: enough to be told a value was refused and fix it.
ROUNDS = 4

SYSTEM = """You fill in fields of a form for a player of a text game.

You are shown the form: what it is for, every field with what it means and
what it holds now, and which fields to fill. Write what the player would
plausibly want there, consistent with everything else already filled in.

- Answer by calling fill, with a value for every field you were asked to fill.
- Fit each value to what the field says it is for. A title is short. A
  description can run to a paragraph. A choice must be one of its options.
- Build on what is already written. Never contradict it.
- If a value is refused, you are told why. Fix it and call fill again.
- Write the values themselves, with no commentary around them."""


def _value_for_prompt(ctx, field):
    """A field's current value as the model is shown it."""
    if field.kind == m.SECRET:
        return None
    if not field.is_set(ctx):
        return "(empty)"
    return field.shown(ctx) if field.kind in (m.CHOICE, m.BOOLEAN) \
        else str(field.value(ctx))


def prompt(ctx, form, fields):
    """The messages a fill is asked with."""
    lines = [f"Form: {form.title_for(ctx)}"]
    intro = form.intro_for(ctx)
    if intro:
        lines.append(intro)
    extra = str(m._call(form.context, ctx, "")
                or getattr(ctx, "world_context", "") or "").strip()
    if extra:
        lines += ["", extra]
    command = str(m._call(form.command, ctx, "") or "").strip()
    if command:
        lines.append(f"(The player reached this form with: {command})")

    lines += ["", "Fields:"]
    for item in form.items_for(ctx):
        if not isinstance(item, m.Field) or item.kind == m.SECRET:
            continue
        label = item.label_for(ctx)
        about = item.help_for(ctx)
        lines.append(f"- {item.key} ({label}): {about}".rstrip(": "))
        if item.kind in (m.CHOICE, m.BOOLEAN):
            options = ", ".join(str(m._call(choice.label, ctx, ""))
                                for choice in item.choices_for(ctx))
            lines.append(f"  options: {options}")
        lines.append(f"  now: {_value_for_prompt(ctx, item)}")

    wanted = ", ".join(field.key for field in fields)
    lines += ["", f"Fill in: {wanted}."]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(lines)}]


def _choice_key(choice):
    return str(choice.value)


def _property(ctx, field):
    """The JSON schema for one field's value."""
    from world import toolbox as tb

    about = f"{field.label_for(ctx)}. {field.help_for(ctx)}".strip()
    if field.kind == m.BOOLEAN:
        return {"type": "boolean", "description": about}
    if field.kind == m.NUMBER:
        spec = {"type": "number", "description": about}
        if field.minimum is not None:
            spec["minimum"] = field.minimum
        if field.maximum is not None:
            spec["maximum"] = field.maximum
        return spec
    if field.kind == m.CHOICE:
        return tb.choice([_choice_key(choice)
                          for choice in field.choices_for(ctx)], about)
    return {"type": "string", "description": about}


def _read(ctx, field, raw):
    """(value, complaint) for what the model sent for one field."""
    if field.kind == m.BOOLEAN:
        if isinstance(raw, bool):
            return raw, ""
        return None, "has to be true or false"
    if field.kind == m.CHOICE:
        for choice in field.choices_for(ctx):
            if _choice_key(choice) == str(raw):
                return choice.value, ""
        return None, "has to be one of the options"
    text = str(raw if raw is not None else "").strip()
    if not text:
        return None, "cannot be empty"
    value, complaint = field.read(ctx, text)
    return value, complaint or ""


def fill_tool(ctx, fields):
    """The one finish tool: a value for each field, checked by the field."""
    from world import toolbox as tb

    properties = {field.key: _property(ctx, field) for field in fields}

    def handler(_tool_ctx, args, answer):
        values, problems = {}, []
        for field in fields:
            value, complaint = _read(ctx, field, args.get(field.key))
            if complaint:
                problems.append(f"{field.key} {complaint}")
            else:
                values[field.key] = value
        if problems:
            return answer(tb.complain("; ".join(problems) + ".", values))
        return answer(tb.accept(values))

    return tb.Tool("fill", "Give a value for every field you were asked to "
                           "fill.",
                   tb.params(properties, required=list(properties)),
                   handler, finishes=True)


def fillable(ctx, form):
    """The fields `~` may fill on this form, in the form's order."""
    return [item for item in form.items_for(ctx)
            if isinstance(item, m.Field) and item.suggestible]


def sponsor_for(ctx, form):
    """
    Who pays, or None when this form cannot be filled in by a model.

    **The form says, or whoever opened it does.** A form declaring its own
    payer is the original arrangement and still the first answer; the second
    exists because the building forms are all opened by one piece of code
    (`commands/making_subject.py`) over a world that knows perfectly well
    whose key it spends. Written on each of twenty forms it would have been
    missing from the twenty-first, and it was: every maker form carried
    `suggestible` fields and not one of them could be filled in, so `~` said
    there was nothing to fill in exactly where there was most.

    Still opt-in either way -- a context with no sponsor in it cannot be
    filled from -- and a sub-form inherits it, because `Context.child` passes
    the data down.
    """
    if form.sponsor is not None:
        return form.sponsor(ctx)
    return getattr(ctx, "sponsor", None)


def fill(ctx, form, fields, on_done, on_error, wait=None):
    """
    Ask a model for a value for each of `fields`.

    `on_done({key: value})` with values that have passed each field's own
    check, or `on_error(text)` saying why there are none. Never both.
    """
    from world import llm
    from world import toolbox as tb

    payer = sponsor_for(ctx, form)
    if payer is None:
        return on_error("Nothing here can be filled in by a model.")
    try:
        payer.key()
    except ValueError as err:
        return on_error(str(err))

    box = tb.Toolbox([fill_tool(ctx, fields)],
                     tb.ToolContext(sponsor=payer, job=JOB))
    llm.converse(payer, payer.model_for(JOB), prompt(ctx, form, fields), box,
                 on_done=on_done, on_error=on_error,
                 on_exhausted=lambda _last: on_error(
                     "The model did not give values that fit."),
                 rounds=ROUNDS, timeout=llm.SLOW_TIMEOUT, wait=wait)
    return None
