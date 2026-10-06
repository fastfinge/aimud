"""
Making sounds with genny. docs/sound.md 9.

genny (github.com/ogomez92/genny) renders a JSON spec to a WAV: instruments,
drums, sound effects, a formant voice, an effects rack, seamless loops. It
calls no model and needs no network, and the same spec always renders the
same file. Every way a sound is made in this game -- a player's form, an
agent typing the same, a model's `make_sound`, a copy of a sound panned to
one side -- ends at `render` here.

**genny trusts its spec, and this does not.** A spec's `out` writes wherever
it says and a `file` layer reads whatever path it names, so `check` takes
`out` away, lets a `file` layer name only a sound asset (which is decoded to
a WAV of our own making for the render), and holds a spec to limits on its
length, its layers and its repeats before anything runs.

**It renders in a process of its own**, on the `sound` pool, with a time
limit: a spec that would run for ever is killed, and numpy failing cannot
take the server with it.

**Asked once.** A spec already rendered gives back the asset it made, and
because the encoded file is steadied (`world/ogg.py`) a render that happens
anyway is the same file, which the register keeps once.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from evennia.utils import logger

#: The genny this was written against, recorded on everything it makes.
COMMIT = "54f409e"

#: libsndfile's Vorbis compression level: the menu sounds' quality, see
#: `world/sounds/rebuild.py`.
QUALITY = 0.2

#: What a spec may be, from settings.
RATES = (22050, 44100)


def _limit(name, default):
    found = getattr(settings, name, None)
    try:
        return default if found is None else float(found)
    except (TypeError, ValueError):
        return default


def most_seconds(loop=False):
    if loop:
        return _limit("SOUND_MOST_LOOP_SECONDS", 60)
    return _limit("SOUND_MOST_SECONDS", 30)


def most_layers():
    return int(_limit("SOUND_MOST_LAYERS", 32))


def most_repeats():
    return int(_limit("SOUND_MOST_REPEATS", 64))


def render_seconds():
    return _limit("SOUND_RENDER_SECONDS", 20)


#: How deep groups may nest.
MOST_DEPTH = 4

#: Layer types, as genny spells each, and which catalog its name is from.
LAYERS = {
    "synth": "instruments", "note": "instruments", "notes": "instruments",
    "seq": "instruments", "sequence": "instruments", "melody": "instruments",
    "drum": "drums", "pattern": "drums", "sfx": "sfx",
    "speech": None, "say": None, "voice": None,
    "file": None, "sample": None, "silence": None, "group": None,
}

#: Where a layer says which one: an instrument by `inst`, the rest by `kind`.
_NAMED_BY = {"instruments": "inst", "drums": "kind", "sfx": "kind"}

#: Keys a spec may not carry, because genny would read or write a path.
_PATHS = ("out", "out_dir")


class Refused(Exception):
    """The spec cannot be rendered; the message says why, in words."""


# ---------------------------------------------------------------------------
# What genny has
# ---------------------------------------------------------------------------

_catalog = None


def available():
    """Whether genny is installed here."""
    try:
        import genny  # noqa: F401
    except ImportError:
        return False
    return True


def catalog():
    """
    genny's catalog -- instruments, drums, sound effects, effects and the
    voice, each with its parameters, defaults and help -- read once. What
    the forms are built from, and what `sound_catalog` hands a model.
    """
    global _catalog
    if _catalog is None:
        from genny import cli, speech

        _catalog = cli._catalog()
        _catalog["words"] = list(getattr(speech, "WORDS", []) or [])
    return _catalog


# ---------------------------------------------------------------------------
# Checking a spec
# ---------------------------------------------------------------------------

def check(spec):
    """
    `(spec, complaints)`: the spec as it will be rendered, and everything
    wrong with it in words. Nothing is rendered when there are complaints.
    """
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError as exc:
            return {}, [f"that is not JSON this can read: {exc}"]
    if not isinstance(spec, dict):
        return {}, ["a spec is one sound, written as a JSON object"]
    if "sounds" in spec:
        return {}, ["one sound at a time: a spec here is a single sound, "
                    "not a batch"]
    spec = copy.deepcopy(spec)
    for key in _PATHS:
        spec.pop(key, None)
    wrong = []
    rate = spec.get("sr", 44100)
    if rate not in RATES:
        wrong.append(f"the sample rate is {rate}; it may be "
                     + " or ".join(str(r) for r in RATES))
    loop = bool(spec.get("loop"))
    longest = most_seconds(loop)
    for key in ("duration",):
        if spec.get(key) is not None:
            try:
                if float(spec[key]) > longest:
                    wrong.append(f"{spec[key]} seconds is longer than "
                                 f"{longest:g}, the most a "
                                 f"{'loop' if loop else 'sound'} may be")
            except (TypeError, ValueError):
                wrong.append(f"{key} has to be a number of seconds")
    known = catalog() if available() else {}
    counted = [0]
    _check_fx(spec.get("fx"), known, wrong)
    _check_layers(spec.get("layers"), known, wrong, counted, depth=1)
    if not spec.get("layers"):
        wrong.append("a sound needs at least one layer")
    if counted[0] > most_layers():
        wrong.append(f"{counted[0]} layers is more than {most_layers()}")
    return spec, wrong


def _check_fx(chain, known, wrong):
    if chain is None:
        return
    if not isinstance(chain, list):
        wrong.append("an effects chain is a list")
        return
    for effect in chain:
        name = effect.get("type") if isinstance(effect, dict) else None
        if not name:
            wrong.append("every effect says its type")
        elif known and name not in known.get("fx", {}):
            wrong.append(f"there is no effect called {name}")


def _check_layers(layers, known, wrong, counted, depth):
    from world import sound

    if layers is None:
        return
    if not isinstance(layers, list):
        wrong.append("layers are a list")
        return
    if depth > MOST_DEPTH:
        wrong.append(f"groups nest at most {MOST_DEPTH} deep")
        return
    for layer in layers:
        if not isinstance(layer, dict):
            wrong.append("every layer is an object")
            continue
        counted[0] += 1
        kind = str(layer.get("type") or "")
        if kind not in LAYERS:
            wrong.append(f"there is no layer type {kind or 'missing'}; "
                         f"there are {', '.join(sorted(LAYERS))}")
            continue
        register = LAYERS[kind]
        if register and known:
            field = _NAMED_BY[register]
            named = layer.get(field, "synth" if field == "inst" else None)
            if named not in known.get(register, {}):
                wrong.append(f"there is no {register[:-1] if register != 'sfx' else 'sound effect'} "
                             f"called {named}")
        if kind in ("file", "sample"):
            found = sound.resolve(layer.get("path"))
            if found is None or found.type != "sound":
                wrong.append("a file layer names a sound this server keeps, "
                             "by its name's id, never a path")
            else:
                layer["path"] = found.hash
        for key in ("repeat", "bars"):
            if layer.get(key) is not None:
                try:
                    if int(layer[key]) > most_repeats():
                        wrong.append(f"{key} {layer[key]} is more than "
                                     f"{most_repeats()}")
                except (TypeError, ValueError):
                    wrong.append(f"{key} has to be a whole number")
        _check_fx(layer.get("fx"), known, wrong)
        if kind == "group":
            _check_layers(layer.get("layers"), known, wrong, counted,
                          depth + 1)


def request(spec):
    """What a render was asked, the same for two identical specs."""
    return {"spec": json.dumps(spec, sort_keys=True)}


# ---------------------------------------------------------------------------
# Rendering one
# ---------------------------------------------------------------------------

def _prepare(spec, folder):
    """
    The spec as genny will read it: every `file` layer pointed at a WAV
    decoded here from the sound asset it names. On the main thread, because
    finding an asset is a database question.
    """
    import soundfile

    from world import assets

    ready = copy.deepcopy(spec)
    count = [0]

    def walk(layers):
        for layer in layers or []:
            if layer.get("type") in ("file", "sample"):
                asset = assets.find(layer.get("path"))
                if asset is None:
                    raise Refused("a sound it is made from is missing")
                with assets.opened(asset) as handle:
                    data, rate = soundfile.read(io_bytes(handle.read()))
                count[0] += 1
                path = os.path.join(folder, f"in{count[0]}.wav")
                soundfile.write(path, data, rate, subtype="PCM_16")
                layer["path"] = path
            if layer.get("type") == "group":
                walk(layer.get("layers"))

    walk(ready.get("layers"))
    ready["out"] = os.path.join(folder, "out.wav")
    return ready


def io_bytes(data):
    import io

    return io.BytesIO(data)


def _render_file(ready, folder, seconds):
    """
    Render a prepared spec in its own process and encode it. Runs on the
    `sound` pool, touching no database. Returns `(ogg bytes, duration)`.
    """
    import soundfile

    from world import ogg

    spec_path = os.path.join(folder, "spec.json")
    with open(spec_path, "w", encoding="utf-8") as handle:
        json.dump(ready, handle)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "genny.cli", "render", spec_path,
             "--quiet", "--strict"],
            capture_output=True, text=True, timeout=seconds, cwd=folder)
    except subprocess.TimeoutExpired:
        raise Refused(f"it took longer than {seconds:g} seconds to make, and "
                      f"was stopped")
    if done.returncode != 0 or not os.path.exists(ready["out"]):
        said = (done.stderr or done.stdout or "").strip().splitlines()
        said = [line.replace("error:", "").strip() for line in said
                if line.strip() and folder not in line]
        raise Refused("genny could not make it"
                      + (f": {said[-1]}" if said else ""))
    data, rate = soundfile.read(ready["out"])
    encoded = io_bytes(b"")
    soundfile.write(encoded, data, rate, format="OGG", subtype="VORBIS",
                    compression_level=QUALITY)
    return ogg.steady(encoded.getvalue()), len(data) / float(rate)


def render(spec, *, name, description, added_by=None, charged_to=None,
           origin="tool", made_with=None, on_done, on_fail, wait=False):
    """
    Check, render and keep a sound. `on_done(asset, said)` or
    `on_fail(why)` is called on the main thread when it is done.

    `wait` renders here and now, for a test or a developer's script; the
    game never waits on a render.
    """
    from world import assets

    if not available():
        on_fail("genny is not installed on this server, so sounds cannot "
                "be made here; every sound already made still plays")
        return
    spec, wrong = check(spec)
    if wrong:
        on_fail("; ".join(wrong))
        return
    asked = request(spec)
    already = assets.made_before("genny", "render", asked)
    if already is not None:
        on_done(already, f"|w{already.name}|n was made from that already, "
                         f"and costs nothing.")
        return

    folder = tempfile.mkdtemp(prefix="aimud-genny-")
    try:
        ready = _prepare(spec, folder)
    except Refused as refusal:
        shutil.rmtree(folder, True)
        on_fail(str(refusal))
        return

    def kept(answer):
        data, seconds = answer
        longest = most_seconds(bool(spec.get("loop")))
        if seconds > longest + 0.5:
            raise Refused(f"it came out {seconds:.1f} seconds long, and "
                          f"{longest:g} is the most")
        record = {"service": "genny", "tool": "render", "commit": COMMIT,
                  "request": assets.request_of("genny", "render", asked),
                  "spec": spec, "loop": bool(spec.get("loop")),
                  "seconds": round(seconds, 2)}
        record.update(made_with or {})
        return assets.add_bytes(
            data, name=name, description=description, added_by=added_by,
            charged_to=charged_to, origin=origin, made_with=record,
            author="made with genny (github.com/ogomez92/genny)",
            wanted="sound")

    def finish(answer):
        try:
            asset, said = kept(answer)
        except (Refused, assets.Refused) as refusal:
            on_fail(str(refusal))
        else:
            on_done(asset, said)
        finally:
            shutil.rmtree(folder, True)

    def failed(failure):
        shutil.rmtree(folder, True)
        refusal = failure.value
        if not isinstance(refusal, Refused):
            logger.log_trace(f"sound_gen: a render failed: {refusal!r}")
            on_fail("it could not be made")
            return
        on_fail(str(refusal))

    if wait:
        try:
            answer = _render_file(ready, folder, render_seconds())
        except Refused as refusal:
            shutil.rmtree(folder, True)
            on_fail(str(refusal))
            return
        finish(answer)
        return

    from world import workers

    work = workers.defer("sound", _render_file, ready, folder,
                         render_seconds())
    work.addCallbacks(finish, failed)


# ---------------------------------------------------------------------------
# Panned copies. docs/sound.md 3.4
# ---------------------------------------------------------------------------

#: The places a sound may be put, from all the way left to all the way right.
POSITIONS = (-100, -67, -33, 0, 33, 67, 100)

_making = set()


def position(pan):
    """The nearest of `POSITIONS` to a pan from -100 to 100."""
    try:
        pan = max(-100, min(100, int(pan)))
    except (TypeError, ValueError):
        return 0
    return min(POSITIONS, key=lambda found: abs(found - pan))


def copies_of(asset):
    """Every panned copy made from this asset."""
    from world import assets

    return [found for found in assets.search("sound", status=None).filter(
        origin="derived")
        if (found.made_with or {}).get("from") == asset.hash]


def panned(asset, pan, wait=False):
    """
    The copy of `asset` panned to the nearest position, or None while it is
    being made -- which is then started, so the next play is panned. The
    centre is the asset itself.
    """
    where = position(pan)
    if where == 0 or asset is None:
        return asset
    for found in copies_of(asset):
        if (found.made_with or {}).get("pan") == where:
            if found.status == "present":
                return found
    wanted = (asset.hash, where)
    if wanted in _making or not available():
        return None
    _making.add(wanted)
    side = "left" if where < 0 else "right"
    spec = {"layers": [{"type": "file", "path": asset.hash}],
            "fx": [{"type": "pan", "pos": where / 100.0}],
            "normalize": None, "max_loudness": None, "trim": False,
            "declick": False}
    made = []

    def done(copy_made, _said):
        _making.discard(wanted)
        made.append(copy_made)

    def fail(why):
        _making.discard(wanted)
        logger.log_info(f"sound_gen: no {side} copy of {asset.name}: {why}")

    render(spec, name=f"{asset.name}, {abs(where)} {side}",
           description=asset.description, origin="derived",
           made_with={"from": asset.hash, "pan": where},
           on_done=done, on_fail=fail, wait=wait)
    return made[0] if made else None


def forget_copies(asset):
    """Delete the copies made from an asset that is going."""
    from world import asset_store, assets

    for found in copies_of(asset):
        asset_store.store().delete(found.hash, assets.extension_of(found))
        found.delete()


# ---------------------------------------------------------------------------
# For a model, or an agent. docs/sound.md 9.4
# ---------------------------------------------------------------------------

#: What `sound_catalog` can list.
SECTIONS = ("instruments", "drums", "sfx", "fx", "speech")


def lookup_tools():
    """`sound_catalog`: what genny can make, from genny itself."""
    from world import toolbox as tb

    def reading(ctx, args):
        if not available():
            return "genny is not installed here, so no sound can be made."
        found = catalog()
        section = str(args.get("section") or "").strip()
        name = str(args.get("name") or "").strip()
        if section not in SECTIONS:
            return ("Sections: " + ", ".join(
                f"{key} ({len(found.get(key) or {})})" for key in SECTIONS)
                + ". Name one, and then a name in it for its parameters.")
        entries = found.get(section) or {}
        if name:
            entry = entries.get(name)
            if entry is None:
                return f"There is no {name} in {section}."
            lines = [f"{name}: {entry.get('desc', '')}"]
            for param, info in sorted((entry.get("params") or {}).items()):
                lines.append(f"  {param} (default {info.get('default')}): "
                             f"{info.get('help', '')}")
            return "\n".join(lines)
        return tb.paged([f"{key} -- {entry.get('desc', '')}"
                         for key, entry in sorted(entries.items())],
                        args, section, most=60)

    return [tb.Tool(
        "sound_catalog",
        "What genny makes sounds from, and each one's parameters.",
        tb.params({"section": {"type": "string", "enum": list(SECTIONS),
                               "description": "Which list"},
                   "name": {"type": "string",
                            "description": "One entry, for its parameters"},
                   "page": {"type": "integer",
                            "description": "Which page of a long list"}}),
        tb.answering(reading), doing="reading what genny can make",
        looks=True)]


def make_sound_tool():
    """
    `make_sound`: genny, for a model writing something that should be heard.

    Gated by the world's `sounds` permit like any other generator, and paid
    for -- in disk, since genny costs nothing else -- by whoever pays for the
    model asking. A model is meant to look first: `list_assets` with type
    sound, and only then make one.
    """
    from world import toolbox as tb

    def allowed(ctx):
        sponsor = getattr(ctx, "sponsor", None)
        return bool(sponsor is not None and available()
                    and sponsor.will("sounds"))

    def making(ctx, args, answer):
        sponsor = getattr(ctx, "sponsor", None)
        if not allowed(ctx):
            answer("This world does not have new sounds made for it. Use one "
                   "list_assets finds, or none.")
            return
        name = " ".join(str(args.get("name") or "").split())
        description = str(args.get("description") or "").strip()
        if not (name and description):
            answer("A sound needs a name and a description: the description "
                   "is all anybody who cannot hear it has.")
            return
        payer = getattr(sponsor, "payer", None)
        actor = getattr(sponsor, "actor", None)
        render(args.get("spec") or "", name=name, description=description,
               added_by=getattr(actor, "account", None) or payer,
               charged_to=payer,
               made_with={"asked_by": "model", "job": getattr(ctx, "job", "")},
               on_done=lambda asset, said: answer(
                   f"Made {asset.name!r}: its id is {asset.hash[:12]}. Use "
                   f"that id wherever a sound is named."),
               on_fail=lambda why: answer(f"Not made: {why}. Fix the spec "
                                          f"and try again, or use a sound "
                                          f"that is already here."))

    return tb.Tool(
        "make_sound",
        "Make a sound with genny, for nothing but a moment, when no sound "
        "list_assets finds fits. The spec is genny's JSON (the manual's "
        "sound page, and sound_catalog, say what may be in it). Answers "
        "with the new sound's id.",
        tb.params({"spec": {"type": "string",
                            "description": "One genny sound spec, as JSON"},
                   "name": {"type": "string",
                            "description": "What it is called: rain on a "
                                           "tin roof"},
                   "description": {"type": "string",
                                   "description": "What it sounds like, in "
                                                  "a sentence, for anybody "
                                                  "who cannot hear it"}},
                  ["spec", "name", "description"]),
        making, doing="making a sound", available=allowed)


def tools():
    """The tools here that act: `make_sound`, offered to the rule loop."""
    return [make_sound_tool()]
