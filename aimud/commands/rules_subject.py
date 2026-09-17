"""
A world's rules, as subjects: what they say, what they do, and what is wrong.

These were one `rules` command with eight subcommands, plus `effects` and
`worldcheck`. Reading and changing are separate verbs now, so reading stays
open to anybody standing in a world -- the open sandbox -- and changing is for
whoever made it.

  view rules [<verb>]           every rule, or one verb's in firing order
  edit rules [<id>]             suspend or restore a rule
  edit rules <id> suspend|restore
  edit rules dead [yes]         suspend every rule that provably cannot fire
  view suggestions              what the world's faults and refusals suggest
  edit suggestions [<id>]       accept or decline one
  edit suggestions <id> accept|reject
  edit suggestions judge [yes]  ask a model to rule on the whole queue
  view effects [<verb>]         what a verb will actually do
  view faults [<world number>]  what the rules say about each other
  reset verb <verb> [yes]       forget what a verb takes, so it is asked again

Only `judge` costs anything. The rest is read out of what the world already
wrote down.
"""

from commands.subjects import (Subject, Use, answered, asking, builder,
                               in_world, names_for, owns_here,
                               require_builder, require_owner, require_world,
                               said)
from world import lore, menus
from world import sponsor as sponsor_mod


def _caller(ctx):
    return ctx.character or ctx.caller


def _root(ctx):
    room = getattr(_caller(ctx), "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Reading rules
# ---------------------------------------------------------------------------

def rule_line(rule, root):
    """One rule as a line: where it applies, and what it says."""
    from world import conditions, rulebooks, standard_rules

    marks = []
    if not rule.get("listed", True):
        marks.append("suspended")
    if standard_rules.is_standard(rule):
        marks.append("standard")
    if rule.get("source") == "derived":
        # Permanent, accepted or not, so that an audit years later can ask
        # what this world decided and what was suggested to it.
        marks.append("derived")
    text = rule.get("name") or ""
    if not text and rule.get("conditions"):
        text = conditions.describe(rule["conditions"][0])
    # A rule's name is what somebody called it, and a name is allowed to be
    # wrong. What it DOES is not a matter of naming, so a rule that changes
    # something says so here whatever it is called.
    if not text and not rule.get("conditions"):
        from world import effects, rulecheck

        doing = rulecheck.effects_of(rule)
        text = effects.say(doing[0]) if doing else ""
    where = rulebooks.said_scope(rule.get("scope"), root)
    note = f" |x({', '.join(marks)})|n" if marks else ""
    return f"{where} -- {text}{note}"


def one_verb(root, verb):
    """What a world holds about one verb, phase by phase, in firing order."""
    from world import actions, rulebooks

    lines = [f"|w{verb}|n"]
    declared = actions.spec(root, verb)
    if declared:
        takes = ", ".join(
            f"{r['role']} ({r['access']}"
            + (", optional)" if r["optional"] else ")")
            for r in declared.get("applies_to") or []) or "nothing"
        lines.append(f"  takes {takes}")
        # The one thing on a declaration that loosens rather than tightens,
        # and "why did that work while I was dead" has to be answerable here.
        waived = declared.get("despite") or []
        if waived:
            doing = {"acting": "act", "moving": "move", "speaking": "speak"}
            lines.append("  works even when you cannot "
                         + " or ".join(doing.get(g, g) for g in sorted(waived)))
        if declared.get("means"):
            lines.append(f"  |x{declared['means']}|n")
    else:
        lines.append("  |xnobody has declared what it takes yet|n")

    found = [r for r in rulebooks.all_rules(root)
             if r.get("action") in (None, verb)]
    if not found:
        lines += ["", "  No rules about it yet."]
        return "\n".join(lines)

    for phase in rulebooks.PHASES:
        here = sorted((r for r in found if r.get("phase") == phase),
                      key=lambda r: rulebooks.rank(r, None, root))
        if not here:
            continue
        lines += ["", f"  |y{phase.replace('_', ' ')}|n"]
        lines += [f"    {rule_line(rule, root)}" for rule in here]
    return "\n".join(lines)


def every_rule(root):
    from world import rulebooks

    found = rulebooks.all_rules(root)
    if not found:
        return "This world has no rules yet."
    becoming = [r for r in found if r.get("phase") == rulebooks.BECOMES]
    found = [r for r in found if r.get("phase") != rulebooks.BECOMES]
    by_action = {}
    for rule in found:
        by_action.setdefault(rule.get("action") or "any action", []).append(rule)
    lines = [f"|w{lore.title(root)}|n has {len(found)} rules, "
             f"over {len(by_action)} verbs.", ""]
    for action in sorted(by_action):
        lines.append(f"  |w{action}|n")
        for rule in sorted(by_action[action],
                           key=lambda r: rulebooks.rank(r, None, root)):
            lines.append(f"    {rule.get('phase', ''):10} {rule_line(rule, root)}")
    lines += changing_lines(root, becoming)
    lines += ["", "|xType |wview rules <verb>|x for one verb in firing order.|n"]
    return "\n".join(lines)


def changing_lines(root, rules):
    """
    The becomes rules, in the order they fire, each with what it watches and
    what it says.

    Most general first, which is the reverse of every other listing and the
    order they really fire in: nothing wins here, so the specific rule lands
    last and has the last word. Said so, because a listing that sorted them
    the ordinary way would describe a world that does not exist.
    """
    from world import rulebooks

    if not rules:
        return []
    ordered = sorted(rules, key=lambda r: rulebooks.rank(r, None, root),
                     reverse=True)
    lines = ["", "  |wwhen things change|n, most general first, which is the "
                 "order they fire in"]
    for rule in ordered:
        lines.append(f"    {rule_line(rule, root)}")
        for guard in (rule.get("when") or []):
            lines += condition_lines(guard, "      ", lead="|xwhen |n")
        if rule.get("report"):
            lines.append(f"      |xsays:|n {rule['report']}")
    return lines


def _seeded(root):
    from world import standard_rules

    standard_rules.seed(root)
    return root


def _rule_verbs(root):
    from world import rulebooks

    return sorted({rule.get("action") for rule in rulebooks.all_rules(root)
                   if rule.get("action")})


def _verb_entry(verb, show, command):
    return menus.Action(f"verb-{verb}", verb,
                        run=lambda ctx: show(_seeded(_root(ctx)), verb),
                        aliases=names_for(verb), topic=verb,
                        command=lambda ctx: f"{command} {verb}")


VIEW_RULES = menus.Form(
    key="rules", title="Rules", kind=menus.VIEW,
    intro=lambda ctx: every_rule(_seeded(_root(ctx))),
    items=lambda ctx: [_verb_entry(verb, one_verb, "view rules")
                       for verb in _rule_verbs(_root(ctx))],
    choices_line="One verb in firing order:",
)


def view_rules_run(cmd, ctx, words):
    from world import verbs

    root = require_world(cmd.caller)
    if root is None:
        return
    _seeded(root)
    if words:
        cmd.caller.msg(one_verb(root, verbs.canonical_verb(" ".join(words))))
        return
    menus.open_menu(cmd.caller, VIEW_RULES, session=cmd.session)


# ---------------------------------------------------------------------------
# Changing rules
# ---------------------------------------------------------------------------

def set_listed(root, rule_id, listed):
    """
    Take a rule out of the book, or put it back.

    Never deleted: an unlisted rule is still readable, still says who wrote it
    and why, and can be restored by whoever decides the suspension was wrong.
    """
    from world import rulebooks

    rule = rulebooks.set_listed(root, rule_id, listed)
    if rule is None:
        return f"There is no rule |w{rule_id}|n in this world."
    state = "back in force" if listed else "suspended"
    return f"|w{rule['id']}|n is {state}: {rule.get('name') or '(unnamed)'}"


def suspend_dead(root):
    """
    Take out every rule the scan proves can never fire.

    One step because the set is not a matter of opinion: a check rule
    demanding the exact condition its own verb produces admits only a thing
    something else already did.
    """
    from world import rulebooks, rulecheck

    findings = rulecheck.scan(rulecheck.of_world(root))
    dead = [rule_id for rule_id, _action, _states, _name
            in (findings.get("self_defeating") or [])
            + (findings.get("after_self_defeating") or [])]
    if not dead:
        return "Nothing in this world is provably dead."
    done = [rulebooks.set_listed(root, rule_id, False) for rule_id in dead]
    verbs = sorted({r["action"] for r in done if r and r.get("action")})
    return "\n".join([
        f"|w{len([r for r in done if r])}|n rules suspended, over "
        f"{len(verbs)} verbs: {', '.join(verbs)}.",
        "|xEach demanded the condition its own verb produces, or followed only "
        "when it had not produced it. They are still "
        "in the book -- |wview rules <verb>|n shows them marked suspended, "
        "and |wedit rules <id> restore|n puts one back.|n",
    ])


DEAD_QUESTION = ("Suspend every rule that provably cannot fire? They stay in "
                 "the book and can each be restored.")


def _rule_form(rule_id):
    def items(ctx):
        from world import rulebooks

        rule = rulebooks.get(_root(ctx), rule_id)
        if rule is None:
            return []
        listed = rule.get("listed", True)
        return [menus.Action(
            "restore" if not listed else "suspend",
            "Put it back in force" if not listed else "Suspend it",
            run=lambda ctx: set_listed(_root(ctx), rule_id, not listed),
            after=menus.BACK,
            command=lambda ctx: f"edit rules {rule_id} "
                                f"{'restore' if not listed else 'suspend'}")]

    def intro(ctx):
        from world import rulebooks

        root = _root(ctx)
        rule = rulebooks.get(root, rule_id)
        return rule_line(rule, root) if rule else "That rule is gone."

    return menus.Form(key=f"rule-{rule_id}", title=f"Rule {rule_id}",
                      intro=intro, items=items)


def _edit_rules_items(ctx):
    from world import rulebooks

    root = _seeded(_root(ctx))
    items = [menus.Action("dead", "Suspend every rule that provably cannot "
                                  "fire",
                          run=lambda ctx: suspend_dead(_root(ctx)),
                          confirm="bulk_rules", question=DEAD_QUESTION,
                          command=lambda ctx: "edit rules dead")]
    for rule in rulebooks.all_rules(root):
        rule_id = rule["id"]
        items.append(menus.Submenu(
            rule_id, f"{rule_id}: {rule.get('action') or 'any action'}, "
                     f"{rule_line(rule, root)}",
            _rule_form(rule_id), aliases=names_for(rule_id)))
    return items


EDIT_RULES = menus.Form(
    key="edit-rules", title="Which rule?",
    intro="Suspending a rule takes it out of force and keeps it readable, "
          "so it can be put back.",
    items=_edit_rules_items,
)


def edit_rules_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "change its rules"):
        return
    _seeded(root)
    words, yes = answered(words)
    if not words:
        menus.open_menu(caller, EDIT_RULES, session=cmd.session)
        return
    first = words[0]
    if first.lower() == "dead":
        asking(cmd, DEAD_QUESTION, "bulk_rules", "edit rules dead",
               lambda: caller.msg(suspend_dead(root)), already=yes)
        return
    action = words[1].lower() if len(words) > 1 else ""
    if action in ("suspend", "unlist"):
        caller.msg(set_listed(root, first, False))
    elif action in ("restore", "unsuspend", "list"):
        caller.msg(set_listed(root, first, True))
    elif action:
        caller.msg(f"A rule can be suspended or restored: |wedit rules "
                   f"{first} suspend|n.")
    else:
        from world import rulebooks

        if rulebooks.get(root, first) is None:
            caller.msg(f"There is no rule |w{first}|n in this world.")
            return
        menus.open_menu(caller, EDIT_RULES, session=cmd.session,
                        path=[first])


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def suggestions_report(root):
    """
    Derive what this world's own faults and refusals support, and list it.

    Generating costs nothing -- no model, no network -- so it runs every time
    somebody asks rather than on a timer somebody has to remember. What costs
    something is deciding.
    """
    from world import suggest

    made = suggest.generate(root)
    text = suggest.report(root)
    if made:
        text = f"|x{len(made)} newly derived from what this world has done.|n\n{text}"
    return text


def answer_suggestion(root, rule_id, taking):
    """Take a suggestion up, or decline it and remember that."""
    from world import suggest

    if taking:
        rule = suggest.accept(root, rule_id)
        if rule is None:
            return (f"There is no suggestion |w{rule_id}|n. Only a suggestion "
                    f"can be accepted; a rule the world wrote for itself is "
                    f"already in force.")
        return (f"|w{rule_id}|n is in force: {rule.get('name') or ''}\n"
                f"|xIt keeps its derived mark, so what this world was "
                f"suggested stays answerable later.|n")
    rule = suggest.reject(root, rule_id)
    if rule is None:
        return f"There is no suggestion |w{rule_id}|n."
    return (f"|w{rule_id}|n declined, and remembered as declined so it is "
            f"not offered again.")


def judge(caller, root):
    """
    Hand the whole queue to a model at once, and apply what comes back.

    The only thing here that costs anything. The world pays for judging
    itself.
    """
    from world import busy, suggest

    standing = suggest.queue(root)
    if not standing:
        return "There is nothing waiting to be judged."
    caller.msg(f"Asking about {len(standing)} suggestions...")

    def done(taken, declined):
        lines = []
        if taken:
            lines.append(f"Accepted: {', '.join(taken)}")
        if declined:
            lines.append(f"Declined: {', '.join(declined)}")
        if not lines:
            lines.append("No verdicts came back that named anything in the "
                         "queue.")
        lines.append("|xEvery one keeps its derived mark. |wview rules|x "
                     "shows which.|n")
        caller.msg("\n".join(lines))

    wait = busy.start(caller, f"judging {len(standing)} suggestions")
    suggest.judge(sponsor_mod.of(caller), root,
                  on_success=busy.closing(wait, done),
                  on_error=busy.closing(wait, lambda err: caller.msg(f"|r{err}|n")))
    return None


JUDGE_QUESTION = ("Ask a model to rule on every waiting suggestion? That is a "
                  "model call, paid for by this world.")


def view_suggestions_run(cmd, ctx, words):
    root = require_world(cmd.caller)
    if root is not None:
        cmd.caller.msg(suggestions_report(_seeded(root)))


def _suggestion_form(rule_id):
    return menus.Form(
        key=f"suggestion-{rule_id}", title=f"Suggestion {rule_id}",
        items=[
            menus.Action("accept", "Put it in force",
                         run=lambda ctx: answer_suggestion(_root(ctx),
                                                           rule_id, True),
                         after=menus.BACK,
                         command=lambda ctx: f"edit suggestions {rule_id} "
                                             f"accept"),
            menus.Action("reject", "Decline it",
                         run=lambda ctx: answer_suggestion(_root(ctx),
                                                           rule_id, False),
                         after=menus.BACK,
                         command=lambda ctx: f"edit suggestions {rule_id} "
                                             f"reject"),
        ])


def _edit_suggestions_items(ctx):
    from world import suggest

    root = _root(ctx)
    items = [menus.Action("judge", "Ask a model to rule on all of them",
                          run=lambda ctx: judge(_caller(ctx), _root(ctx)),
                          confirm="spend", question=JUDGE_QUESTION,
                          command=lambda ctx: "edit suggestions judge")]
    for rule in suggest.queue(root):
        rule_id = rule["id"]
        items.append(menus.Submenu(
            rule_id, f"{rule_id}: {rule_line(rule, root)}",
            _suggestion_form(rule_id), aliases=names_for(rule_id)))
    return items


EDIT_SUGGESTIONS = menus.Form(
    key="edit-suggestions", title="Suggestions",
    intro=lambda ctx: "" if len(_edit_suggestions_items(ctx)) > 1
    else "Nothing is waiting. |wview suggestions|n derives anything new.",
    items=_edit_suggestions_items,
)


def edit_suggestions_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "change its rules"):
        return
    words, yes = answered(words)
    if not words:
        menus.open_menu(caller, EDIT_SUGGESTIONS, session=cmd.session)
        return
    first = words[0]
    if first.lower() == "judge":
        asking(cmd, JUDGE_QUESTION, "spend", "edit suggestions judge",
               lambda: said(caller, judge(caller, root)), already=yes)
        return
    action = words[1].lower() if len(words) > 1 else ""
    if action in ("accept", "take"):
        caller.msg(answer_suggestion(root, first, True))
    elif action in ("reject", "decline"):
        caller.msg(answer_suggestion(root, first, False))
    else:
        caller.msg(f"A suggestion can be accepted or rejected: |wedit "
                   f"suggestions {first} accept|n.")


# ---------------------------------------------------------------------------
# Effects: what a verb will actually do
# ---------------------------------------------------------------------------

def every_effect(root):
    """
    Every verb this world has worked out something to do, and how much.

    The world's own only: every world is seeded with what looking means, and
    listing that would be the engine taking credit.
    """
    from world import rulebooks, rulecheck, standard_rules

    doing = {}
    for rule in rulebooks.all_rules(root):
        if not rule.get("listed", True) or standard_rules.is_standard(rule):
            continue
        if rule.get("phase") not in (rulebooks.CARRY_OUT, rulebooks.AFTER):
            continue
        action = rule.get("action")
        if not action:
            continue
        doing.setdefault(action, 0)
        doing[action] += len(rulecheck.effects_of(rule))

    if not doing:
        return ("This world has not worked out what any verb does yet. "
                "Try one on something and it will.")
    counted = f"|w{len(doing)} verbs|n" if len(doing) != 1 else "|wone verb|n"
    lines = [f"{counted} this world can do something with.", ""]
    for action in sorted(doing):
        changes = doing[action]
        lines.append(f"  |w{action}|n |x-- {changes} "
                     f"{'change' if changes == 1 else 'changes'}|n")
    return "\n".join(lines)


def _effect_verbs(root):
    from world import rulebooks, standard_rules

    return sorted({rule.get("action") for rule in rulebooks.all_rules(root)
                   if rule.get("action") and rule.get("listed", True)
                   and not standard_rules.is_standard(rule)
                   and rule.get("phase") in (rulebooks.CARRY_OUT,
                                             rulebooks.AFTER)})


def one_effect(root, verb, caller):
    """One verb, in the order the world runs it."""
    from world import actions, checks, rulebooks, standard_rules

    lines = [f"|w{verb}|n"]
    declared = actions.spec(root, verb)
    if declared and declared.get("means"):
        lines.append(f"  |x{declared['means']}|n")

    found = [r for r in rulebooks.all_rules(root)
             if r.get("action") in (None, verb)]
    listed = [r for r in found if r.get("listed", True)]
    # Whether this WORLD has decided anything, or whether what you are reading
    # is only what the engine gives everybody.
    its_own = [r for r in listed if not standard_rules.is_standard(r)
               and r.get("action") == verb]
    heading = {
        rulebooks.INSTEAD: "instead of it",
        rulebooks.CHECK: "it will not work unless",
        rulebooks.CARRY_OUT: "it does",
        rulebooks.AFTER: "and afterwards",
    }
    for phase in rulebooks.PHASES:
        here = sorted((r for r in listed if r.get("phase") == phase),
                      key=lambda r: rulebooks.rank(r, None, root))
        if not here:
            if phase == rulebooks.CARRY_OUT:
                # Two different nothings, and the difference is what to do
                # next: a verb never asked about is settled by typing it, and
                # one written only refusals for will not be.
                why = ("Nothing is known about it yet -- typing it at "
                       "something is what settles that" if not its_own
                       else "nothing -- this world has not worked out what it "
                            "does yet")
                lines += ["", "  |yit does|n", f"    |r{why}|n"]
            continue
        lines += ["", f"  |y{heading[phase]}|n"]
        for rule in here:
            lines += _effect_rule(root, rule)

    contest = next((r.get("contest") for r in listed
                    if r.get("phase") == rulebooks.CARRY_OUT
                    and r.get("contest")), None)
    chance = checks.prospect(caller, contest, {}, root) if contest else None
    if chance:
        lines += ["", "  " + checks.said_prospect(chance)]
    elif any(r.get("phase") == rulebooks.CARRY_OUT for r in listed):
        lines += ["", "  |xnot contested: it works or it is refused, never a "
                      "matter of luck|n"]
    return "\n".join(lines)


def _effect_rule(root, rule):
    """One rule as the lines under a phase heading, marked with where."""
    from world import conditions, effects as effects_mod
    from world import rulebooks, rulecheck, standard_rules

    standard = standard_rules.is_standard(rule)
    where = rulebooks.said_scope(rule.get("scope"), root)
    mark = f"|x({where}, standard)|n" if standard else f"|x({where})|n"
    out = []
    for condition in (rule.get("conditions") or []):
        out += condition_lines(condition, "    ", suffix=f" {mark}")
    for effect in rulecheck.effects_of(rule):
        out.append(f"    {effects_mod.say(effect)} {mark}")
    if not out:
        out.append(f"    {rule.get('name') or 'nothing'} {mark}")
    # A standard rule's guards are machinery rather than meaning, and every
    # verb gathers the same ones, so they are not printed.
    if not standard:
        for guard in (rule.get("when") or []):
            out += condition_lines(guard, "      ", lead="|xonly when ",
                                   suffix="|n")
    return out


def condition_lines(condition, indent, lead="", suffix=""):
    """
    One condition as the lines of a listing.

    A plain condition is one line. An `any` or an `all` is a heading and then
    a line per member, indented under it, because this is read aloud at least
    as often as it is looked at, and "any of these" followed by a short list
    is easier to follow by ear than one long sentence joined by "or".
    """
    from world import conditions

    kind, members = conditions.node_of(condition)
    if not kind:
        return [f"{indent}{lead}{conditions.describe(condition)}{suffix}"]
    heading = "any one of these" if kind == conditions.ANY else "all of these"
    lines = [f"{indent}{lead}{heading}:{suffix}"]
    for member in members:
        lines += condition_lines(member, indent + "  ")
    return lines


VIEW_EFFECTS = menus.Form(
    key="effects", title="What verbs do", kind=menus.VIEW,
    intro=lambda ctx: every_effect(_seeded(_root(ctx))),
    items=lambda ctx: [
        menus.Action(f"verb-{verb}", verb,
                     run=lambda ctx, verb=verb: one_effect(
                         _seeded(_root(ctx)), verb, _caller(ctx)),
                     aliases=names_for(verb), topic=verb,
                     command=lambda ctx, verb=verb: f"view effects {verb}")
        for verb in _effect_verbs(_root(ctx))],
    choices_line="What one of them does:",
)


def view_effects_run(cmd, ctx, words):
    from world import verbs

    root = require_world(cmd.caller)
    if root is None:
        return
    _seeded(root)
    if words:
        verb = verbs.canonical_verb(" ".join(words))
        cmd.caller.msg(one_effect(root, verb, cmd.caller))
        return
    menus.open_menu(cmd.caller, VIEW_EFFECTS, session=cmd.session)


# ---------------------------------------------------------------------------
# Faults: what a world's rules say about each other
# ---------------------------------------------------------------------------

def faults_report(root):
    """
    What the rules cannot do between them, and what the world has been asked.

    Costs nothing. Nothing is repaired; it says if anything is waiting in the
    suggestions.
    """
    from world import counters, rulecheck, suggest

    findings = rulecheck.scan(rulecheck.of_world(root))
    lines = [rulecheck.report(findings, lore.title(root)), "",
             counters.report(root)]
    from world import becoming

    looping = dict(getattr(root.db, becoming.OVERFLOW_ATTR, None) or {})
    if looping:
        lines += ["", f"|w{len(looping)} rules|n about what becomes true kept "
                      f"setting each other off, and were stopped each time: "
                      + ", ".join(f"{rule_id} ({count} times)"
                                  for rule_id, count in sorted(looping.items()))
                      + "."]
    standing = len(suggest.queue(root))
    if standing:
        lines += ["", f"|w{standing} suggestions|n are waiting. "
                      f"|wview suggestions|n reads them."]
    return "\n".join(lines)


def view_faults_run(cmd, ctx, words):
    caller = cmd.caller
    if not require_builder(caller):
        return
    if words:
        from commands.world_subject import _pick_world

        picked = _pick_world(caller, [w for w in words if w.lower() != "world"])
        if picked is not None:
            caller.msg(faults_report(picked[0]))
        return
    root = require_world(caller)
    if root is not None:
        caller.msg(faults_report(root))


# ---------------------------------------------------------------------------
# reset verb: forget what a verb takes
# ---------------------------------------------------------------------------

def redeclare(root, verb):
    """
    Drop what a verb was declared to take, so the next use asks again.

    The deliberate exception to "first answer stands", made out loud. The rules
    about the verb stay exactly as they are.
    """
    from world import actions

    store = dict(getattr(root.db, actions.ATTR, None) or {})
    if verb not in store:
        return f"Nothing has been declared about |w{verb}|n."
    store.pop(verb)
    setattr(root.db, actions.ATTR, store)
    return (f"|w{verb}|n is undeclared. The next time somebody tries it the "
            f"world will be asked afresh what it takes.\n"
            f"|xIts rules are untouched -- |wview rules {verb}|n shows them.|n")


def _redeclare_question(verb):
    return (f"Forget what {verb} takes, so the world is asked again next time "
            f"somebody tries it? Its rules are not changed.")


def _declared_verbs(root):
    from world import actions

    return sorted((getattr(root.db, actions.ATTR, None) or {}).keys())


RESET_VERB = menus.Form(
    key="reset-verb", title="Which verb?",
    intro=lambda ctx: "" if _declared_verbs(_root(ctx))
    else "Nothing has been declared about any verb here yet.",
    items=lambda ctx: [
        menus.Action(f"verb-{verb}", verb,
                     run=lambda ctx, verb=verb: redeclare(_root(ctx), verb),
                     confirm="reset_verb", question=_redeclare_question(verb),
                     after=menus.CLOSE, aliases=names_for(verb),
                     command=lambda ctx, verb=verb: f"reset verb {verb}")
        for verb in _declared_verbs(_root(ctx))],
)


def reset_verb_run(cmd, ctx, words):
    from world import verbs

    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "change its rules"):
        return
    words, yes = answered(words)
    if not words:
        if not menus.interactive(caller):
            caller.msg("Which verb? |wreset verb respawn|n forgets what "
                       "respawn takes, so the world is asked again next time "
                       "somebody tries it.")
            return
        menus.open_menu(caller, RESET_VERB, session=cmd.session)
        return
    verb = verbs.canonical_verb(" ".join(words).lower())
    asking(cmd, _redeclare_question(verb), "reset_verb",
           f"reset verb {verb}", lambda: caller.msg(redeclare(root, verb)),
           already=yes)


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

def _submenu(key, label, form, help):
    return lambda ctx: [menus.Submenu(key, label, form, help=help)]


def _text(key, label, show, help, command):
    return lambda ctx: [menus.Action(key, label, run=show, after=menus.CLOSE,
                                     help=help, command=lambda ctx: command)]


SUBJECTS = [
    Subject(
        "rules", ("rules", "rule"),
        uses={
            "view": Use(view_rules_run, _submenu(
                "rules", "This world's rules", VIEW_RULES,
                "Every rule this world holds, and one verb's in the order "
                "they fire."), offered=in_world),
            "edit": Use(edit_rules_run, _submenu(
                "rules", "This world's rules", EDIT_RULES,
                "Suspend a rule or put one back."), offered=owns_here),
        },
        help="What this world's rules say, and the order they say it in.",
    ),
    Subject(
        "suggestions", ("suggestions", "suggestion"),
        uses={
            "view": Use(view_suggestions_run, _text(
                "suggestions", "Suggestions for this world's rules",
                lambda ctx: suggestions_report(_seeded(_root(ctx))),
                "What this world's own faults and refusals suggest.",
                "view suggestions"), offered=in_world),
            "edit": Use(edit_suggestions_run, _submenu(
                "suggestions", "Suggestions for this world's rules",
                EDIT_SUGGESTIONS,
                "Accept or decline a suggestion, or have a model judge them "
                "all."), offered=owns_here),
        },
        help="Rules this world's faults and refusals suggest it is missing.",
    ),
    Subject(
        "effects", ("effects", "effect", "affects"),
        uses={"view": Use(view_effects_run, _submenu(
            "effects", "What verbs do here", VIEW_EFFECTS,
            "What a verb needs, what it changes, and the odds."),
            offered=in_world)},
        help="What a verb will actually do in this world.",
    ),
    Subject(
        "faults", ("faults", "fault"),
        uses={"view": Use(view_faults_run, _text(
            "faults", "What is wrong with this world's rules",
            lambda ctx: faults_report(_root(ctx)),
            "Conditions nothing can bring about, rules that cannot fire, and "
            "what the world has refused and why.", "view faults"),
            offered=lambda ctx: builder(ctx) and in_world(ctx))},
        help="What this world's rules cannot do between them. For builders.",
    ),
    Subject(
        "verb", ("verb",),
        uses={"reset": Use(reset_verb_run, _submenu(
            "verb", "What a verb takes", RESET_VERB,
            "Forget what a verb takes, so the world asks again."),
            offered=owns_here)},
        help="What a verb takes, so the world is asked again.",
    ),
]
