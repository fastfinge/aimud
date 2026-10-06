# Development plan: sound

Status: **phases 0 to 2 built** on the `sound` branch; §17 says where the
building changed the plan. This answers the `future-plans.md` item on MSP, and the
part of the assets item that was waiting for "the first type with a
consumer". It covers sending sounds to a player's client, keeping sounds as
assets, deciding what makes a sound and when, ambience that follows a player
from room to room, a sound ruleset, sounds for menus, and making sounds with
genny.

A **sound** is an asset of the `sound` type. It plays because something
happened (an **event sound**), or keeps playing because of where you are and
what is near you (**ambience**). The client gets a URL and plays the file.
Everything about what to play and when is decided in the game, and every
sound is also a line of text for anyone who cannot hear it.

---

## 1. The change, on one page

* **One way to play a sound, three ways to send it.** `world/sound.py` has
  `play` and `stop`. They know which protocol a session speaks: MSP over
  telnet, GMCP `Client.Media` (Mudlet and others), or the web client. Nothing
  outside that module knows MSP exists. §3.
* **`sound` is an asset type.** WAV, Ogg Vorbis and MP3, checked by decoding
  them with `soundfile`. Up to 10 MB each. Sounds made in the game are stored
  as Ogg. §4.
* **Some sounds ship with the game.** Built-in sounds are files in the repo,
  together with the genny spec that made each one. They are added to the
  register at startup, charged to nobody, and cannot be deleted or evicted.
  The four menu sounds are the first. §4.3.
* **Event sounds are an effect.** `play_sound` goes in the effects
  vocabulary, so any rule can play one: a verb's `carry_out`, `after` or
  `instead`, and a `becomes` rule when a fact changes. The sound travels on
  the `Event`, and each listener gets it the way they get the words. §5.
* **Ambience is data, not rules.** A room, a zone, a kind, a state or a
  single thing can say what it sounds like. When anything changes (you move,
  a fire is lit, a clock is carried in), the game works out what you should
  hear now and sends only the difference. A sound that is in both places keeps
  playing across the move. §6.
* **Every sound is also text.** The asset's description is its caption. A
  `look` says what you can hear, `listen` asks directly, and captions can be
  turned on for event sounds. Agents and players without sound have them by
  default. Deaf players and MCP agents get the same game. §7.
* **Menus make sounds.** `menus.PRESENTER` was left for this. Opening,
  closing, choosing and "that is not one of the choices" each play a built-in
  sound. A player can change any of them to another sound asset. §8.
* **genny makes sounds, for everyone.** Players use `create sound`, agents
  type the same command, and models get a `make_sound` tool behind a new
  `sounds` permit. All of them go through one function that checks the spec,
  renders it in a separate process with a time limit, and stores the result
  as an asset. §9.
* **A `sound` ruleset.** An optional ruleset with ambience for common places
  and states, and sounds for common verbs, all made with genny and shipped
  with the game. A world chooses it like any other ruleset. §10.

## 2. What is already there

* **Assets** (docs/archived/assets.md). There is a register, `assets.add`,
  hash-named files served at `/media/assets/`, quotas, the pool, and world
  export listing assets by hash and URL. `ASSET_BASE_URL` gives the full URL a
  client needs. `assets.from_tool` and `assets.made_before` were built for a
  tool's file results, and nothing has used them yet.
* **`menus.Presenter`**: `opened`, `shown`, `chose`, `refused`, `confirmed`
  and `closed`. The menu engine already calls each of these at the right
  moment, and today they do nothing. Its docstring says "Sounds, MXP and OOB
  come later, through `PRESENTER`."
* **`events.Event`** keeps the facts of what happened apart from the words,
  and gives each viewer their own rendering. Its docstring names sound as the
  first thing that wants those facts.
* **The effects vocabulary** (`effects.VOCABULARY`) is a register. Each
  effect has a `means`, `fields`, `backwards` and `answers`, and the rule
  forms, the rule generator and the planner all read it.
* **`becoming`** fires rules when a fact changes, through the doors every
  change already uses: states, traits, moves, owners and clothing. Ambience
  needs to know about exactly these changes, at exactly these points.
* **Zones nest**, and rooms, zones and things all have kinds, read through
  WordNet's hypernyms (`kinds.py`). A rule scoped to a kind covers its
  hyponyms.
* **Rulesets** are validated JSON: rules, actions, kinds, states and figures.
* **Evennia** speaks GMCP, MSDP and MXP over telnet, and OOB to its web
  client. It has no MSP. `TELNET_PROTOCOL_CLASS` lets a game swap in a
  subclass of the telnet protocol.
* **`permits.MAKES`** decides what a model may bring into being in a world,
  and `sponsor.will` asks it.
* **`world/workers.py`** is where slow work runs, off Twisted's shared pool.

## 3. Sending sounds

### 3.1 What each protocol can do

| | MSP (telnet option 90) | GMCP `Client.Media` | web client |
|---|---|---|---|
| clients | VIP Mud, MUSHclient with a plugin, zMUD, Mudlet | Mudlet, and others that adopted MCMP | Evennia's own |
| one-shot sounds | `!!SOUND(...)` | `Client.Media.Play` | yes |
| loops | one at a time, on `!!MUSIC` with `L=-1` | any number, each with a `key` | any number |
| stop one sound | no: `!!SOUND(Off)` stops every sound | `Client.Media.Stop {key}` | yes |
| keep playing if already playing | `C=1` on `!!MUSIC` | `continue: true` | yes |
| fades | no | `fadein` and `fadeout` | yes |
| preload | no | `Client.Media.Load` | yes |
| volume and type | `V=`, `T=` | `volume`, `tag` | yes |

So `Client.Media` gets the full design. MSP gets every event sound, and the
single loudest ambience loop on `!!MUSIC` with `C=1`. That is how MSP muds
have always done room ambience, and `C=1` gives MSP clients the seamless
crossing in §6.4 too. The web client gets the full design through a small
plugin that turns `Client.Media` OOB messages into Web Audio.

### 3.2 Knowing what a session speaks

* **MSP:** the portal sends `IAC WILL MSP` along with its other handshakes,
  and a client that answers `DO` has MSP. This needs a subclass of Evennia's
  `TelnetProtocol` (`server/conf/telnet_msp.py`), named in
  `TELNET_PROTOCOL_CLASS` and the SSL setting. It adds one handshake and sets
  a protocol flag.
* **`Client.Media`:** the client lists `Client.Media 1` in GMCP
  `Core.Supports.Set`. This is read in an input function.
* **Web client:** always supported, once the plugin is loaded.
* **MCP agents and anything else:** no sound. They get captions (§7).

Some clients parse MSP without ever negotiating it. A **sound protocol**
setting (auto, MSP, `Client.Media`, off) covers them, and `auto` is the
default.

### 3.3 One door

`world/sound.py`:

* `play(listener, asset, *, category, volume=100, pan=0, loop=False,
  key=None, fade=0)` plays a sound for every session puppeting `listener`, in
  whatever protocol each one speaks, and honours that player's settings
  (§3.6). An asset that is missing or not present plays nothing (assets.md
  §9).
* `stop(listener, key, fade=0)`
* `preload(session, assets)` asks for the UI sounds at login, on protocols
  that can preload, so the first menu doesn't wait for a download.
* `url(asset)` is `ASSET_BASE_URL` plus the asset's served path. **If
  `ASSET_BASE_URL` is not set, no sound is sent.** An admin is told once at
  login, and `view assets` already says why.
* Every play stamps `assets.touch`, so a sound in use is not the first thing
  to leave the pool.

MSP lines go out as their own line, before the text they belong with, and
are never sent to a session that has not got MSP. A client that didn't ask
for MSP never sees `!!SOUND`.

### 3.4 Panning

A sound can come from the left or the right: `pan` runs from -100 (fully
left) to 100 (fully right), and 0 is the centre. A world uses it to say
where a sound comes from. The obvious case is a direction: a door slamming
to the east is heard on the right. The map is north-up, the way audio games
draw theirs, so east is right, west is left, north and south are centre,
and the diagonals are halfway.

**No MUD protocol can pan.** MSP has no parameter for it, and neither has
`Client.Media` (its keys are name, url, type, tag, volume, fadein,
fadeout, start, finish, loops, priority, continue, key and caption). So:

* **The web client pans by itself**, with a Web Audio `StereoPannerNode`.
* **Every other client gets a panned copy of the file.** The pan is
  rounded to one of **seven positions** (-100, -67, -33, 0, 33, 67, 100).
  A sound at any position other than centre is made once, with genny's
  `pan` effect on a `file` layer, and kept as an asset whose origin is
  `derived`. It belongs to the asset it was made from: it is charged to
  nobody, it does not count against the pool, it goes when its source goes,
  and it is made again whenever it is next needed. Seven positions limit
  a sound to six copies. Because genny always renders the same file from
  the same spec, the copy always has the same hash.
* Making a copy takes a moment, so the first time it is wanted, the sound
  plays from the centre and the copy is made in the background. Every later
  play is panned. Built-in sounds that are known to pan can have their
  copies made at startup.
* **Without genny, nothing pans**, and every sound plays from the centre.
* A **pan** setting turns it off for players who want every sound in the
  centre, such as somebody with hearing in one ear.

### 3.5 Categories

Every sound has a category. The category is MSP's `T=` and `Client.Media`'s
`tag`, and players set a volume for each one:

* `ui`: menus, and the "I don't understand" of the parser
* `event`: sounds rules play
* `ambience`: loops from rooms, zones, kinds, states and things
* `music`: reserved. Nothing plays music in this plan, but adding it later
  should not mean another setting.

### 3.6 Settings

A new **Sound** group in `world/preferences.py`, stored on the account:

* sound on or off
* the sound protocol (§3.2)
* volume for each category, 0 to 100
* panning on or off (§3.4)
* captions for event sounds, and for ambience changes (§7). These are on by
  default when the session has no sound.
* the sound for each menu moment (§8.3), each a `Picker` over `sound` assets

These go in `exchange.LEFT`. They belong to a player, not a world.

## 4. The `sound` asset type

### 4.1 The type

* `sniff`: `RIFF....WAVE`, `OggS`, `ID3`, or an MP3 frame sync.
* `check`: decode the whole file with **`soundfile`** (libsndfile, whose
  wheels include Vorbis and MP3 on every platform), and refuse anything that
  does not decode. The version it returns is the codec: `pcm`, `vorbis` or
  `mp3`. `refuses` turns away the codecs that MUD clients can't play, such
  as Opus in an Ogg container.
* `most_bytes`: 10 MB, as settled for assets.
* `permit`: `sounds` (§9.5).
* `uses(asset)` and `used_in(world)`: every place a world mentions the sound,
  whether in a rule's `play_sound` or in ambience on a room, zone, kind, state
  or thing. That is what lets deleting, the pool warnings and export work
  with no further changes.

**One change to the type register:** a type has one `extension` today, and a
sound can be any of three formats. A type gains `extension_of(path)`, which
by default returns `extension`, and the store names the file from it.

### 4.2 What the record learns

`view asset` on a sound adds its duration, channels, loudness and
sharpness, from `soundfile` and the same measures `genny info` uses.
Somebody who cannot hear a sound, a model included, can at least tell
that it is half a second long and not piercing. Whether it was made to loop
is in `made_with`, and ambience pickers list those first.

### 4.3 Built-in sounds

* They live in the repo at `aimud/world/sounds/<group>/<name>.ogg`. Beside
  each one is `<name>.json`, the genny spec that made it, with its name,
  description, author and licence.
* At startup, a pass like `take_in_folder` adds each file with origin
  `builtin`, charged to nobody. If a file changes, its hash changes, so it
  becomes a new asset, and the setting that pointed at the old built-in
  sound moves to the new one (§8.3).
* A built-in asset cannot be deleted, given up or evicted. It does not
  count against the pool.
* Rulesets and settings name built-in sounds by `group/name`, which is
  resolved to a hash at load time. Worlds and exports name them by hash, as
  they do every other asset.

## 5. Event sounds

### 5.1 Where they attach

There are four places a sound could attach, and one answer covers them:

* **Actions:** yes, through the rules about them. A rule is how a world
  says anything about a verb.
* **Reports:** a report is text and stays text. A rule that has a report can
  also have a `play_sound` effect, and both are delivered with the same
  event.
* **Conditions:** a condition is a question, and a question makes no noise.
  "When this becomes true, play this" is a `becomes` rule with a
  `play_sound` effect. "While this is true, you hear this" is ambience on a
  state (§6). Between them they cover the two meanings of the word.
* **Effects:** yes. `play_sound` is the one door, so actions, `becomes`
  rules and everything that runs effects all get sound at once.

### 5.2 The effect

```
play_sound: {sound: <asset hash>, to: "actor" | "others" | "everyone" | <role>,
             volume: 0..100, pan: -100..100 | from: <an exit or direction>}
```

`from` works the pan out from a direction (§3.4), so a rule can say "the
sound comes from the way the actor went" without knowing which way that is.

* In `effects.VOCABULARY` with `backwards: False` (a sound changes nothing
  a planner could aim at) and `answers: False`.
* Applying it adds `(sound, to, volume)` to `Event.sounds`, a new slot.
  `events.deliver` plays it to each listener it renders for. Each listener
  hears the event once, whatever order they are told in.
* Listeners are whoever would be told the event. A sound is not heard
  through walls in this plan (§13).
* The rule forms get a `play_sound` field with a sound `Picker`. This is the
  first form `assets.picker` sits in. The rule generator learns about the
  effect, but uses it only when the world permits `sounds` and an asset that
  fits already exists. Writing a rule never makes a sound.

### 5.3 Captions

When captions are on, a listener gets the asset's description as a line of
its own, after the narration:

> The heavy door swings open. *(a slow iron creak)*

## 6. Ambience

### 6.1 What can have it

An `ambience` list, `[{sound, volume, pan}]`, can be set on (a sea to the
east of a shore, say, is panned right):

| on | heard | example |
|---|---|---|
| a room | in that room | the hum of the engine room |
| a zone | in every room of that zone that sets none of its own, inherited down the zone tree | wind across the whole moor |
| a kind | in any room of that kind, or near any thing of that kind | every `forest.n.01` has birdsong. A `clock.n.01` ticks |
| a state | near anything in that state | anything `burning` crackles |
| a thing | near that thing | this one music box |

Each of these goes through the writer the thing already has:
`kinds.remember`, the state store, zone records, and the room and object
makers. Each goes into `exchange.CARRIED` and is listed by `used_in`.

### 6.2 What you hear

For a listener in a room, the **place layer** is the first of these that has
anything: the room itself, then its zones from nearest to farthest, then the
room's kinds from most to least specific. One answer, because a room that
says what it sounds like means that and nothing more general.

Then the **things layer** is added: the ambience of everything you can
perceive in the room (its contents and what you carry, but nothing inside a
closed container), from each thing's own ambience, its states and its kinds.

At most **four loops** play at once, the loudest first. The single loudest
loop in the place layer is what MSP gets on `!!MUSIC`.

### 6.3 When it is worked out again

Ambience never ticks. It is worked out again only for listeners where
something changed, and only through doors that already exist:

* a character moving: `at_post_move`
* a thing arriving or leaving: `at_object_receive`, and the leaving side of
  the same move
* a state, a kind or ambience changing: the `becoming.mark` and `settle`
  doors, which already see every one of these changes
* a setting changing, logging in, or puppeting

A listener is a character with a session that has sound or captions on. A
room with no listeners costs nothing.

### 6.4 Crossing between places

Each session keeps what it is hearing, as `{key: (asset, volume)}`, where
the key is the asset's hash. A change sends only the difference:

* **The same sound in both places keeps playing.** Walking through a forest
  zone doesn't restart the birdsong in every room, and neither does walking
  from one forest into another. (`continue: true`, or `C=1` for MSP.)
* **A sound that has stopped applying fades out** over about a second, and a
  new one fades in, so a doorway is a crossfade and not a cut.
* **A volume change is a change**, so a fire that dies down can get
  quieter.

### 6.5 Text

* `look` at a room ends with what can be heard there, from the captions of
  the place layer and the things layer: *"You hear wind across the moor, and
  a fire crackling."*
* `listen` (or `listen to <thing>`) says the same, or about one thing.
* With ambience captions on, a crossing that changes what you hear says so
  once: *"The wind fades, and you hear rain on a tin roof."*

## 7. Captions, and who gets what

The principle is that an agent, a deaf player and a player whose client has
no sound all get the same game as a player with speakers:

* **Every sound already has a description**, because the asset register
  requires one, and that description is the caption.
* What a room sounds like is part of `look` for everybody. It costs one
  line, and it means a world can be written for the ear and still be fair to
  anybody reading it.
* Event captions and ambience-change captions are settings, on by default
  for sessions with no sound (MCP agents among them) and off for sessions
  that play sound.
* `Client.Media` has a `caption` key for exactly this, and every play sends
  the asset's description in it. A client that shows captions does that
  itself.
* MCP agents hear nothing, so to an agent a sound is its caption.
  `list_assets` and `show_asset` already let an agent find sounds, and §9.4
  lets one make them.

## 8. Menu sounds

### 8.1 The moments

| presenter call | sound |
|---|---|
| `opened` | open |
| `closed` (quit, back, finished, walked away) | close |
| `chose` (a field, an action, a submenu, a page) | select |
| `confirmed` yes | select |
| `confirmed` no | close |
| `refused`, and any `Refuse` an action raises | error |

`SoundPresenter` replaces `PRESENTER` at startup and calls `sound.play`
with the `ui` category. `shown` changes nothing.

The parser's "I don't understand that" has a **sound of its own**: a short
drum hit, also in `ui`. It is not the menu error sound. In a menu there is a
fixed set of choices, and missing them is a mistake. In the game, typing
something it doesn't know is part of playing, so it gets a softer sound
that you can hear many times without it nagging. It is a fifth setting in
§8.3, beside the menu moments.

### 8.2 The sounds

The two samples in `menu-samples/` cannot ship, so the shipped sounds are
made with genny to the same design. Measured, the samples are one family:

* **error.ogg:** 0.23 s, loud (peak -0.6 dB). A buzzy tone at about 340 Hz
  (a slightly flat F4), with a resonance sweeping down its harmonics from
  about 4 kHz to 1.7 kHz, **twice**: a "bzzrt-bzzrt".
* **open.ogg:** 0.37 s, quiet (peak -7 dB), bright (a third of its energy is
  above 5 kHz). The same kind of tone at about 367 Hz (F#4), after 85 ms of
  silence, with the resonance sweeping **up** from 1.8 kHz to 2.6 kHz and then
  landing on a bright top at 2.9 kHz and 8.8 kHz, **three times**, 85 ms
  apart: a chirped "brrp-brrp-brrp".

So the family is a buzzy tone with a moving resonance. Up means opening,
down means closing or failing, and the number of chirps sets the weight.
The genny versions follow that grammar:

* **open:** three rising chirps at 367 Hz, quiet and bright. The last one is
  three semitones higher, so the sound ends going up.
* **close:** the mirror of open, three falling chirps, with no lead-in. The
  last one is three semitones lower, so the sound ends going down.
* **select:** one rising chirp, 85 ms. It is the shortest sound, because it
  plays the most.
* **error:** two falling buzzes at 340 Hz, as loud as the sample
* **huh** (the parser's "I don't understand"): one short, damped low tom
  (110 Hz, 0.14 s decay) with a little room reverb. It is
  `menu-samples/genny-drafts/huh/huh_tom.ogg`, chosen from four candidates.

The drafts are in `menu-samples/genny-drafts/`, along with the script that
writes their spec. You approved them, with the final chirps of open and
close pitched up and down. Phase 0 moves them to `aimud/world/sounds/menu/`
with their specs, which say they were made with genny for aimud, under
aimud's licence.

### 8.3 Choosing your own

Each moment is a setting holding a sound asset, which defaults to the
built-in sound. A player can choose any `sound` asset with a `Picker`, or
none. An admin can change the server's defaults. That way the popular
sounds can be used by somebody who has them, on their own server, without
aimud shipping them.

## 9. genny

### 9.1 What it is

genny (github.com/ogomez92/genny) is a procedural sound generator,
written in Python with only numpy and scipy. It renders a JSON spec to
a WAV: 82 instruments, drums, about fifty sound effects, a car engine, a
formant speech synthesiser with character voices, an effects rack, seamless
loops, and `genny info` measures of loudness and sharpness. It calls no
model and needs no network, and the same spec always renders the same file.
It was written to be driven by AI agents, so its catalog
(`genny list --json`) describes every parameter.

### 9.2 Depending on it

* **A git dependency, never a copy.** genny is not on PyPI, so it goes in
  `pyproject.toml` as `genny @ git+https://github.com/ogomez92/genny@<commit>`.
  `uv` fetches it from the author's repository onto each machine that
  installs aimud. aimud never carries its code: there is no vendored copy,
  no fork and no wheel of ours. The pin is a commit, so that a push upstream
  cannot change what renders, and it is updated deliberately.
* **It has no licence file.** Depending on it this way redistributes
  nothing. Its README tells people to install and run it, which is as plain
  an invitation to use it as there is. Asking the author to add a licence is
  still worth doing, but nothing here waits for it. The output of a tool
  belongs to whoever made it, so the shipped sounds are ours to license.
* If the repository disappears, a new install cannot fetch genny. Making
  sounds then stops with a clear message. Playing sounds needs only
  `soundfile`, so it keeps working, and so does every sound already made.
* It brings scipy. numpy is already installed.

### 9.3 One door: `world/sound_gen.py`

Every way of making a sound ends at `sound_gen.render(spec, *, name,
description, payer, made_by)`:

* **The spec is checked before anything runs.** genny trusts its spec, and
  this must not:
  * `out` and `out_dir` are removed. The output path is ours.
  * A `file` layer may name only a `sound` asset by hash. We resolve that
    to a temporary copy, so a spec can build on an existing sound ("this
    door, but underwater"), and no spec can name a path.
  * Limits on length (30 s, or 60 s for a loop), layers (32), `repeat`
    (64), nesting depth and sample rate (22.05 kHz or 44.1 kHz). These are
    settings.
  * Names of instruments, sound effects, effects and parameters are checked
    against the catalog, so a bad spec is refused with what was wrong, in
    words, and costs nothing.
* **Rendered in a separate process**, `python -m genny.cli render -`, with
  the spec on stdin, on the worker pool. It has a time limit (20 s) and is
  killed if it overruns. A spec cannot hang the server, and a crash in numpy
  cannot take the server down with it.
* **Encoded to Ogg Vorbis** with `soundfile`, then stored with
  `assets.add(origin="tool")`. `made_with` records `{tool: "genny",
  version, commit, spec}`.
* **Asked once.** The same spec returns the same asset through
  `assets.made_before`, without rendering. Because genny is deterministic, a
  render that happens anyway still adds nothing, since its hash is the same.
* **Charged as assets already are:** to the player who made it, or for a
  model, the sponsor's payer.

### 9.4 Players and agents

* **`create sound`** opens a menu of the ways to make a sound. Today it has
  one entry, **genny**. Freesound search, and a paid service like
  ElevenLabs, are later entries in the same menu. `create sound genny` goes
  straight to it. Each source is a small register entry (a key, a label,
  and the form it opens), so adding one doesn't touch the others.
* **`create sound genny`** opens a form: name, description, and **how**:
  * a sound effect, an instrument playing notes, a drum, or speech. Each
    field is **built from genny's catalog** (parameters, defaults and help),
    so a new version of genny adds its features to the form without a code
    change.
  * effects on an existing sound, chosen with a `Picker`
  * a whole spec, as long text, for anything layered
  * whether it loops, and how long it is
  * a **try it** action, which renders the sound and plays it to you. What
    you try is kept only if you save it.
* **`view sound <name>`** plays the sound and describes it (§4.2).
* **`edit sound <name>`** opens the form filled in from the sound's spec.
  Saving makes a new asset, since assets never change, and the old one stays
  until it is deleted.
* **Agents** type the same commands. A new manual page, `sound`, explains
  specs, with genny's own guidance for agents adapted for aimud, and a
  `sound_catalog` lookup returns the catalog.

### 9.5 Models

* A new `sounds` entry in `permits.MAKES`, with the same three choices as
  the others: whenever asked, only for a player, or never. A world decides
  whether a model may make sounds.
* A `make_sound(spec, name, description)` tool in `toolkit`, gated by
  `sponsor.will("sounds")`. It returns the new asset's id.
* Two places use it. A builder's `~` on a sound field ("suggest a sound for
  this") does, which is the paid key it always is. And when a world permits
  sounds, the room and item generators may write ambience for what they
  make, first looking for an existing sound with `list_assets` and only then
  making one.
* The `call_tool` mapping from a tool's file result to an asset
  (assets.md §11) is wired in here as well. A rule can then hold the asset's
  id in a `play_sound`, and an outside sound service (ElevenLabs, later)
  plugs in as a service with no new code.

## 10. The `sound` ruleset

`world/rulesets/sound.json`, which a world chooses like any other ruleset.
Choosing it is a world creator's decision about what the world sounds like.
The sound system does not depend on it.

* **Ambience on common kinds of place**, at the level of WordNet hypernyms
  so that they cover a lot: forest, field, shore, river, cave, city street,
  tavern and inn, ship, and indoors (a quiet room tone).
* **Ambience on common states:** burning, flowing, raining, and running for
  machines.
* **Sounds for common verbs:** opening and closing (doors, chests), eating,
  drinking, taking and dropping, and a footstep for going.
* Every sound is made with genny, and its spec and file ship under
  `aimud/world/sounds/ruleset/`.

The ruleset document gains an `ambience` field on its `kinds` and `states`
entries, and a sound reference that names a built-in sound, which is checked
at load time like everything else a ruleset names.

## 11. Testing

* **Protocol:** MSP negotiation (a client that says `DO`, one that says
  `DONT`, one that says nothing), the `!!SOUND` and `!!MUSIC` lines with
  `U=`, never sending MSP to a session that has not got it, `Client.Media`
  payloads, and preload at login. Nothing is sent without `ASSET_BASE_URL`.
* **Type:** a WAV, an Ogg and an MP3 are each accepted. A renamed text file
  and a renamed Opus file are refused. `extension_of` names the file.
* **Built-ins:** added once at startup, charged to nobody, undeletable and
  never evicted. A changed file moves the settings that pointed at it.
* **Events:** `play_sound` from `carry_out`, `after`, `instead` and
  `becomes`. `to` actor, others, everyone or a role. Each listener hears it
  once. Captions follow the setting.
* **Ambience:** the precedence of room, zone, kind and things. The four-loop
  limit. Crossing within a zone and between zones with a shared sound keeps
  it playing. A crossfade sends a stop and a play. A state change re-works
  ambience only for listeners in that room. A closed box is silent. `look`
  and `listen` text.
* **Menus:** each presenter call plays its sound, a player's own choice
  overrides it, and turning sound off plays nothing.
* **genny:** a spec with `out`, a path in a `file` layer, too long, too many
  layers or an unknown name is refused before anything renders. A render
  that overruns is killed. The same spec gives the same asset with one
  render. `made_with` is filled in. The `sounds` permit and the quota both
  stop a model.
* **Plumbing:** the new attributes are in `CARRIED` or `LEFT` (the AST
  test). `used_in` finds the sound in every place it can be. A round trip of
  export and import carries ambience and `play_sound`.
* **Never a path:** sound messages, captions and lookups are checked like
  every other asset message.

## 12. Phases

* **Phase 0: the type.** `soundfile`, the `sound` type, `extension_of`,
  built-in sounds and their startup pass, and the five UI sounds (open,
  close, select, error and huh), final, with their specs.
* **Phase 1: sending.** `world/sound.py`, MSP negotiation, `Client.Media`,
  the Sound settings and preload. `pan` is accepted, and plays from the
  centre until phase 5.
* **Phase 2: menus.** `SoundPresenter`, the parser's error, and choosing
  your own menu sounds. This is the first sound a player hears.
* **Phase 3: event sounds.** `play_sound`, `Event.sounds`, captions, and
  the rule forms with the first `assets.picker`.
* **Phase 4: ambience.** Data on rooms, zones, kinds, states and things,
  working out what to hear, crossings, `look`, `listen` and the makers'
  fields.
* **Phase 5: genny.** The git dependency, `sound_gen`, `create`,
  `view` and `edit sound`, the catalog-built forms, the manual page and
  `sound_catalog`. Panned copies (§3.4), so panning works in every client.
* **Phase 6: models.** The `sounds` permit, `make_sound`, `~` on sound
  fields, generators writing ambience, and `call_tool` file results.
* **Phase 7: the ruleset.** `sound.json` and its sounds.
* **Phase 8: the web client.** The `Client.Media` plugin, which pans for
  itself.
* **Phase 9: docs.** README, help, the manual, and `future-plans.md`.

Phases 0 to 2 are the smallest piece that is worth having on its own: menus
that sound right in Mudlet and VIP Mud.

## 13. Not in this plan

* **Hearing through walls.** A sound next door, quieter and muffled, can
  be done with genny's `muffle` effect and the map. It needs a decision about
  how far sound carries, and is worth its own plan.
* **Music.** The category is reserved, and nothing plays music yet.
* **Freesound search**, which is still assets.md's later plan.
* **ElevenLabs** and other paid generators. §9.5 makes them a service a
  world adds, with no new code.
* **Front and back, and distance.** Stereo has left and right and nothing
  else. Positional audio would need a client that supports it.
* **Players uploading genny specs as files.** A spec is typed, or comes from
  a form, and is never an asset.

## 14. Decisions this plan makes (say if any are wrong)

1. Event sounds are one effect, `play_sound`, not a field on actions,
   reports or conditions. `becomes` rules cover "when this becomes true".
2. Ambience is data on rooms, zones, kinds, states and things, worked out
   by the engine, and not rules. The `sound` ruleset ships data and rules
   for it, and is optional.
3. `Client.Media` is the full protocol. MSP gets event sounds and one
   ambience loop. The web client comes last.
4. Sounds made in the game are stored as Ogg Vorbis. The samples are Ogg,
   so the clients your players use already play it.
5. Every sound is also text: `look` always says what you hear, and
   captions are on by default for anybody without sound.
6. genny runs in its own process, with a checked spec and a time limit, and
   never in the server's process.
7. Built-in sounds are committed as files with their specs, and are not
   rendered at startup. Rendering at startup would make genny a hard
   dependency of starting the server, and a new version of genny would
   silently change every hash.

## 15. Open questions

None.

## 16. Settled

1. **genny is a git dependency, pinned by commit (2026-10-06).** uv fetches
   it from the author's repository, so aimud redistributes none of its code.
   No phase waits on a licence.
2. **The menu sounds (2026-10-06).** The drafts were right, once the last
   chirp of open was three semitones higher and the last chirp of close three
   semitones lower.
3. **The parser has its own sound (2026-10-06).** "I don't understand that"
   plays a short drum hit, not the menu error sound: `huh_tom.ogg`.
4. **Sounds can be panned (2026-10-06).** No MUD protocol can pan, so the web
   client pans by itself, and every other client gets a copy panned by genny
   at one of seven positions (§3.4).
5. **`create sound` is a menu of sources (2026-10-06).** genny is its only
   entry for now, as `create sound genny`, and Freesound can join it later.

## 17. As built

Where building phases 0 to 2 departed from the plan above, and what it found.

* **A sound's codec names its file (§4.1).** The plan gave a type
  `extension_of(path)`. A sound's version is already its codec (`pcm`,
  `vorbis`, `mp3`), so a type answers `extension_for(version)` instead, and
  the record needs no new column. `register` checks every extension a type
  may use against the list of code extensions.
* **Ogg files are steadied (§4.3, §9.3).** libsndfile writes a random serial
  number into every Ogg stream, so encoding the same sound twice gave two
  hashes. `world/ogg.py` sets the serial to a fixed number and recomputes
  each page's checksum, so the same samples give the same file. Without it,
  "asked once" and "the same panned copy every time" would not have held.
* **Vorbis quality 0.2.** libsndfile's default lost an audible part of the
  bright chirps. At compression level 0.2 the menu sounds come back within
  6% of genny's WAV, at about 10 KB each. `world/sounds/rebuild.py` uses
  this level, and phase 5 should use the same.
* **The built-ins carry their spec.** Each `world/sounds/<group>/<name>.json`
  holds the name, the description, the author and licence, and
  `made_with: {tool, commit, spec}`. `rebuild.py` renders the specs with a
  pinned genny through `uv run --with`, so rebuilding needs genny only on a
  developer's machine.
* **A copy of a built-in becomes the built-in.** A player who had uploaded
  the same file as a built-in stops being charged for it once the game ships
  it. The new `derived` origin is there for phase 5 already, so the
  migration only has to be run once.
* **Telnet over TLS needed nothing (§3.2).** Evennia's SSL protocol
  subclasses whatever `TELNET_PROTOCOL_CLASS` names, so MSP comes with it. A
  second class for it would have been a circular import.
* **`Core.Supports.Set` was being read wrongly.** Evennia mapped it to
  `client_options`, which reads keyword arguments only. Mudlet sends a list
  of package names, which was ignored, and the session's options were sent
  back. `server/conf/inputfuncs.py` now reads the list, and hands on any
  keyword arguments as before.
* **Settings arrive with their sounds (§3.6).** The Sound group has sound
  on or off, the protocol, the menu-sound volume, and a sound for each
  moment. Event volume, ambience volume, panning and captions are added in
  the phases that play those sounds, so no setting does nothing.
* **Select plays when a field is answered (§8.1).** The menu engine reports
  a field as chosen when its value is set, not when its prompt opens, so
  that is when choosing sounds. Actions and submenus sound when chosen.
* **Two moments, not one, are "not understood" (§8.1).** They are Evennia's
  "Huh?" outside a world, and a near miss for a command ("There is no
  worldg command. Did you mean...?"). Inside a world, anything else typed is
  attempted as an action, and the world answers it in words, so it was
  understood.
* **A sound plays to the session that asked.** A menu is open in one
  window, so `play(session=...)` sends its sounds there and not to every
  window the player has.
* **Refusals inside a menu now reach the presenter.** A `Refuse` raised by
  an action or a field was being printed directly, past `refused`, so it
  would have been silent. Both places now go through the same refusal as
  "that is not one of the choices".
* **Heard live (2026-10-06).** Menu sounds play in Mudlet over GMCP
  `Client.Media` and in MUSHclient over MSP, from a server on localhost with
  `ASSET_BASE_URL` set. VIP Mud has not been tried yet.

