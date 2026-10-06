"""
Make the built-in sounds again from their specs. docs/sound.md 4.3.

Every built-in sound is a `<name>.ogg` beside a `<name>.json` that says what
it is called, what it sounds like, who made it, and the genny spec that made
it. The spec is the source; the Ogg file is what ships, so that starting the
server never needs genny and a new genny never silently changes a hash.

This is a developer's tool, not part of the game. Run it from the repo root
with genny available, after changing a spec:

    uv run --with "genny @ git+https://github.com/ogomez92/genny@54f409e" \
        python aimud/world/sounds/rebuild.py [group/name ...]

With no names it rebuilds every sound. Each is rendered to WAV by genny and
encoded to Ogg Vorbis by soundfile, the same encoder the game uses for the
sounds genny makes in play, and steadied (`world/ogg.py`), so a sound whose
spec did not change comes out the same file with the same hash.
"""

import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# `world.ogg` without the game around it: it imports nothing of Django's.
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from world import ogg  # noqa: E402

#: libsndfile's Vorbis compression level, 0 the best and 1 the smallest. At
#: its default a bright chirp lost an audible part of its top; at 0.2 the
#: menu sounds come back within 6% of genny's WAV and stay near 10 KB.
QUALITY = 0.2


def specs(wanted=()):
    """(ref, json path) for every built-in sound, or for those named."""
    for group in sorted(os.listdir(HERE)):
        folder = os.path.join(HERE, group)
        if not os.path.isdir(folder) or group.startswith("_"):
            continue
        for entry in sorted(os.listdir(folder)):
            if entry.endswith(".json"):
                ref = f"{group}/{entry[:-5]}"
                if not wanted or ref in wanted:
                    yield ref, os.path.join(folder, entry)


def rebuild(ref, path):
    import soundfile

    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    spec = dict(doc["made_with"]["spec"])
    with tempfile.TemporaryDirectory() as work:
        wav = os.path.join(work, "out.wav")
        spec["out"] = wav
        subprocess.run([sys.executable, "-m", "genny.cli", "render", "-",
                        "--quiet"], input=json.dumps(spec), text=True,
                       check=True)
        data, rate = soundfile.read(wav)
        encoded = io.BytesIO()
        soundfile.write(encoded, data, rate, format="OGG", subtype="VORBIS",
                        compression_level=QUALITY)
    with open(path[:-5] + ".ogg", "wb") as out:
        out.write(ogg.steady(encoded.getvalue()))
    print(f"{ref}: rebuilt")


if __name__ == "__main__":
    for found in specs(set(sys.argv[1:])):
        rebuild(*found)
