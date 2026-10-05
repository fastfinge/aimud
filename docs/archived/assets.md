# Development plan: assets

Status: **built**, phases 0 to 6, on the `assets` branch. Where the building
changed the plan, §18 says how and why. This answers the `future-plans.md` item "how a
player gets a file to the server, and gets one off it", and gives MSP sounds,
MXP images and AIML a place to keep their files before any of them is built.

An **asset** is a file the game keeps for a player or a tool: a world
document today, and a sound, an image or an AIML file once the system that
uses it exists. Players name it, describe it, pick it from menus and never see
where it lives. Models can list and use assets the way they list rules, and a
tool that makes a file hands back an asset.

---

## 1. The change, on one page

* **One register, every asset.** Each asset has a record (name, description,
  type, size, who added it, where it came from, licence) and a file named by
  the hash of its contents. Assets never change: replacing one makes a new
  one. The same file added twice is kept once. §3.
* **Types are registered by the system that uses them.** A type says what a
  file of its kind looks like, checks it really is one by parsing it, says
  which versions it accepts, and sets its own size limit. The first and only
  type in this plan is `world`: a world document. MSP, MXP and AIML each add
  theirs when they are built, along with a permit for generating one. §4.
* **Four ways in, one writer.** `create asset` fetches a file from a URL. A
  form on the website takes an upload from a logged-in player. Importing a
  world fetches the assets it names. A tool that makes a file stores it. All
  four go through `assets.add`, which checks the file, the type and the quota
  before anything is kept. §5, §6.
* **Fetching is the dangerous part, and is done once.** A player-supplied
  URL can point at the server's own network. One function, `assets.fetch`,
  is the only thing that downloads. It refuses private, loopback,
  link-local and cloud-metadata addresses, including after a redirect or a
  DNS change, stops at the type's size limit, and runs off the main thread.
  §6.
* **Every account has a quota.** `ASSET_QUOTA` in settings, 500 MB by
  default. An admin can raise it for one account. An asset counts against
  whoever paid for it to exist: the player who added it, or the account whose
  key paid for a tool to make it. Using somebody else's asset costs nothing.
  An asset in use can be given up to a server pool with its own quota, which
  sheds its least-used assets when full. §7.
* **Every asset is served, by hash.** `/media/assets/<hash>.<ext>`, through
  Evennia's existing media serving, which lists no directories. A hash name
  is hard to guess, and changes whenever the content does, so a client never
  plays a stale copy. §8.
* **A world carries its assets by name and address.** Exporting a world lists
  every asset it uses, with its hash and where it can be downloaded. Importing
  one reuses any asset this server already has, and downloads the rest,
  checking each against its hash. An asset that cannot be fetched is marked
  missing and can be fetched again later. §9.
* **Players pick, never browse.** `menus.Picker` offers only assets of the
  type a field can use. `import world` picks a world asset. A model gets a
  `list_assets` lookup, and a tool that makes an asset hands its id back.
  Nobody is ever shown a path. §10.
* **Admins can review and remove.** `view assets recent` lists what has been
  added, by whom and from where. An admin can delete any asset. §12.

## 2. What is already there

* **The shared folder** (`WORLD_DIRS`, `aimud/worlds/`, gitignored).
  `exchange.write`, `exchange.read` and `exchange.folder` are what `export
  world` and `import world` use today. It becomes the first asset type, and the
  folder is brought into the register once (§13).
* **World documents already carry a version** (`exchange.VERSION = 1`), and
  `import world` already refuses "a document from a later aimud". That is §4's
  versioning, already written for one type.
* **`exchange.MOST_BYTES`** (8 MB) is the most a world document may be, and
  becomes the `world` type's size limit.
* **Evennia serves `MEDIA_ROOT`** (`server/.media/`, gitignored) at `/media/`,
  without directory listings (`evennia/server/webserver.py`).
* **The website has login** (Django auth, `LOGIN_URL`), so an upload form can
  know whose account an upload belongs to.
* **`commonsense.download`** is the existing pattern for a large download over
  a confirmation, off the main thread.
* **`services.address_complaint`** refuses only the game's own MCP endpoint.
  That is right for an address an admin adds, and not enough for one a player
  types (§6).
* **Libraries already installed:** `httpx` (through the MCP SDK), `pillow`
  and `defusedxml`.
* **The sponsor and `permits`** decide who pays for a generated file and
  whether a world allows one.
* **`menus.Picker` and `making.picker`** let a form pick from a register, and
  `toolkit`/`lookups` are where a model-facing lookup goes.

## 3. What an asset is

### 3.1 The record

A small Django model in its own app (`aimud/assets/`), because quota sums,
"recently added" and search are database queries. It needs one `evennia
migrate`. Fields:

| field | what it holds |
|---|---|
| `hash` | SHA-256 of the contents: the identity, and the file name |
| `type` | a registered type key, e.g. `world` |
| `version` | what the type read off the file, e.g. world format 1 |
| `name` | what players call it. Not unique: two "rain" sounds may exist |
| `description` | required. For a screen reader user and for a model, the description *is* the asset |
| `size` | bytes |
| `added_by` | the account that brought it in, kept for review even after it is given up |
| `added` | when |
| `origin` | `upload`, `url`, `import` or `tool` |
| `source` | the URL it came from, if any |
| `author`, `licence` | for credit. Freesound and most image sources need it |
| `made_with` | for a tool: which service and tool, the model, its settings (temperature and so on), and the request |
| `status` | `present` or `missing` (§9) |
| `charged_to` | the account whose quota it counts against, or none once given up to the pool (§7.1) |
| `last_used` | when anything last used it, for choosing what leaves a full pool |

### 3.2 One file, many records?

No: one file, one record. Two players adding the same file get the one asset
that already exists, with its name and description. The second player is told
it was already there and is charged nothing. A name of their own would be a
second record pointing at one file, which makes deleting ambiguous for no real
gain.

### 3.3 Never changed

An asset's file never changes once kept, since its name is its hash. Its name,
description, author and licence may be edited by whoever added it, or by an
admin. Replacing the file means adding a new asset.

## 4. Types

`world/asset_types.py` holds the register. Each type is a small object:

* `key`, `label`, and `extensions` (used for the served file name only, never
  for deciding what a file is)
* `sniff(head)`: whether the first bytes look like this type. Checked first,
  because it is cheap.
* `check(path)`: parse the whole file as this type, returning `(version,
  complaint)`. This is the real test. A world document goes through
  `exchange.problems`, an image through Pillow, an AIML file through
  `defusedxml`.
* `accepts(version)`: whether this server can use that version. A world from
  a later aimud is refused with the version named.
* `most_bytes`: its size limit
* `permit`: the `permits.MAKES` entry for generating one, or none for a type
  only players supply
* `served`: whether `/media/` serves it. Every type is served (your call, §8),
  but the flag keeps that a per-type decision.

**Only `world` is registered in this plan.** Every other type arrives with the
system that uses it, as you decided. For later, from the MXP specification:
the `IMAGE` tag requires only **GIF and BMP**; anything else is a
client-specific filter. Mudlet supports MXP links and menus and only part of
the rest, so whether PNG or JPEG are worth accepting is a question for the MXP
plan, not this one.

**No type can be code.** There is no type for scripts, executables, HTML or
SVG, and adding one is refused in review. A test walks the register and fails
on any extension in a deny list (`py`, `exe`, `js`, `html`, `svg`, and so on).

## 5. Getting one in

### 5.1 `create asset`

A maker in `world/making.py`, with its form in `world/makers/assets.py`.
Fields: URL, name, description (`~` fills it), author, licence. The type is
read off the file, never asked. Saving fetches in a thread (§6), checks the
file (§4) and the quota (§7), and then stores it. While that runs, the player
gets the busy notices that slow model calls already give.

### 5.2 The upload page

`/assets/upload/` on the website, behind login, using Django's CSRF and
upload handling. Fields as above, with a file in place of the URL. Django's
`DATA_UPLOAD_MAX_MEMORY_SIZE` and `FILE_UPLOAD_MAX_MEMORY_SIZE` are set from
the largest type's `most_bytes`, so an oversized upload stops at the door.
The page shows the account's quota, and says what each type is for.

The website runs in Evennia's Server process, so the view calls
`assets.add` directly, with the same checks as in game. The in-game way to do
the same thing is `create asset` with a URL. A player who only has a file and
no URL uses the website.

### 5.3 Agents

An agent adds assets the way a player does: `create asset` over `send`. It
gets `list_assets` like any model (§10). No upload tool: MCP clients that can
send files are rare, and a URL covers them.

## 6. Fetching safely

One function, `assets.fetch(url, most_bytes)`, is the only thing in the game
that downloads a file a player named. Everything it does is held by tests
that plant the attack (§14).

* **http and https only.** No `file:`, no `ftp:`, no anything else.
* **No private destinations.** Every address the host resolves to must be
  public (`ipaddress.ip_address(...).is_global`), which covers loopback,
  private ranges, link-local and cloud metadata (`169.254.169.254`), plus the
  IPv6 forms of each.
* **No DNS tricks.** The connection goes to the address that was checked, not
  to a second lookup of the name.
* **Redirects are checked hop by hop**, at most five.
* **The size limit is enforced on bytes received**, not on what
  `Content-Length` claims. The download stops the moment it passes the type's
  `most_bytes`.
* **A timeout**, and the whole thing runs in a thread, as
  `commonsense.download` does.

**Library: Drawbridge, behind one function.** No mature, maintained Python
library does all of this. *Advocate*, the well-known one, was archived in 2023
and pins `urllib3<2`. *safehttpx* sends every hostname to Google's DNS and
doesn't say what it does with redirects. *Drawbridge* (MIT) wraps the `httpx`
we already have. It does the hard part the right way: it connects to the
address it checked, checks again on every redirect, and blocks cloud
metadata. But it is alpha (0.1.x), unaudited and small. So the plan is to use
it pinned, inside `assets.fetch` only, with our own byte cap and timeout
around it. The tests in §14 hold the guarantees, not the library. If it
breaks or is abandoned, the alternative is about a hundred lines of our own
that do the same thing under the same tests. §17 records the choice: Drawbridge.

There is no separate "safe download" library. `httpx`'s streaming responses
plus the byte counter above are the download.

## 7. Quotas

* **`ASSET_QUOTA`** in `settings.py`: 500 MB by default, `None` for no limit.
* **Per account:** `account.db.asset_quota`, set by an admin with `edit
  quota <account> <size>`. It overrides the default either way, so it can
  raise or lower one account's quota.
* **Used** is the total size of the assets an account is charged for.
* **Who is charged: whoever paid for the file to exist**, once, when it first
  exists. One rule, and the account that pays money and the account whose
  disk is used are always the same:

  | how it arrived | charged to |
  |---|---|
  | uploaded, or fetched from a URL | the player who added it |
  | downloaded during a world import | the importer |
  | made by a tool | the sponsor's payer: whoever's key paid for the call. In a shared world that is its creator, whoever caused it, an NPC included |

* **Reusing an asset charges nobody**, in any world, whoever owns it. An
  asset belongs to no world, so a charge never moves because of where it is
  used. Adding a file the server already has charges nobody either.
* **A full quota stops new files the way a missing key does.** A tool that
  would make an asset over its payer's quota is refused. Visitors see that
  nothing new happens, and the creator is told their quota is full. With
  permits, sharing and logging out, it is a fourth brake a creator holds on
  what visitors can spend.
* **Shown:** `view assets` opens with "You are using 42 MB of 500 MB".
  Anything that would go over is refused before it is stored, with how much
  room is left.

### 7.1 Giving an asset up, and the server's pool

An asset that is in use cannot be deleted (§12), so without a way out it
would count against whoever added it for ever. So:

* **Give it up.** Whoever is charged for an asset may hand it to the server.
  It stops counting against them, and everything using it keeps it. From then
  on only an admin may delete it. An account being deleted gives up all of its
  assets.
* **The pool has its own quota**, `ASSET_POOL_QUOTA` in settings (1 GB by
  default). Without it, a player could add files for a friend and give them
  up, filling the server's disk on nobody's quota.
* **When the pool is full, its least-used assets go.** Least used means
  fewest things using it, then longest since anything last used it. That
  means a `last_used` stamp on the record, written by each system that uses
  an asset and throttled the way `activity.note_player_nearby` throttles its
  stamp. Evicted files are deleted, and their records are marked `missing`,
  keeping their source URL, so every world using one treats it as missing
  (§9). An asset larger than the whole pool cannot be given up. Evicting never
  removes the asset being given up.
* **Adopt.** Any player may take a given-up asset back onto their own quota,
  which protects it from eviction. A missing asset with a source URL can be
  fetched again the same way, and is charged to whoever fetches it.
* **The pool is visible:** `view assets pool` shows how full it is, and
  which assets are next in line to go.
* **World owners are warned**, so they can choose to adopt. The worlds
  using an asset come from each type's `uses(asset)` query (§12), and their
  creators are told:
  * **when one of their assets is given up:** *"The rain sound, used by The
    Drowned Library, has been given up to the server and could be removed
    when it runs short of room. `adopt asset rain` keeps it, on your quota
    (2 MB)."* Said at once if they are logged in, and otherwise once at their
    next login, in one message listing everything that changed while they were
    away.
  * **when one is next in line to go**, meaning the pool is more than 90% full
    and the asset is among those that would be evicted to make room for one
    more of the largest type. Again said once, not every time they enter.
  * **when one has gone:** it is missing now, and can be fetched again from
    its source URL, if it has one.
  * **and always when they look:** `view world` lists the given-up assets the
    world uses, each with its size and whether it is next in line, and with the
    command that adopts it.

  Nothing is repeated on entering a world. A warning that comes every time
  gets tuned out, and one that comes once, at login or when it happens, plus a
  line in `view world`, is enough to act on. A world's owner is the only one
  warned: a visitor using somebody else's world cannot adopt on its behalf in
  any way that matters.

## 8. Serving

Files are stored as `server/.media/assets/<hash>.<ext>` and served at
`/media/assets/<hash>.<ext>`. Nothing about the URL says who added an asset
or what it is called. Every type is served, as you decided: it is a game, and
the hash makes a URL hard to guess.

**The server has to know its own address.** An MSP client, and another
server importing a world, both need a full URL, and a server cannot work out
its public address on its own. So there is a new setting, `ASSET_BASE_URL`
(e.g. `https://mud.example.com:4001`). Until it is set, exports carry hashes
without URLs, and `view assets` says why.

**Storage is behind an interface** (`assets.store`): `put`, `open`,
`exists`, `delete` and `url`, with `ASSET_STORE` naming the class in
settings. The local-folder store is the only one written. An S3 store would
be a new class with no other changes, as you asked.

## 9. Worlds carry their assets

* **Export** adds `assets: [{name, type, hash, url, description, author,
  licence}]`, listing every asset the world uses. Today that is none, since
  no world-using type exists yet. The field is defined now so that MSP and
  MXP fill it in rather than changing the document format.
* **Import:** for each entry, if this server already has the hash, reuse it
  without a download. That is the reset-on-the-same-server case. Otherwise,
  fetch the URL and **check that the hash matches**: a server that hands back
  something else has not handed back the asset. Anything that cannot be
  fetched or doesn't match gets a record with `status: missing` and its
  source URL. The world still imports.
* **Missing is visible and recoverable.** `view assets missing` lists them,
  and `edit asset <name> fetch` tries again. A system using an asset treats
  one that is missing as absent: no sound plays.
* **Quota:** downloaded assets are charged to the importer. An import that
  would go over says so before it starts, from the sizes the document lists.

## 10. Using one

* **Pickers.** `assets.picker(key, label, type)` builds a `menus.Picker`
  listing only assets of that type, by name and description, with search.
  Each system's forms use it, and so does `import world` (§13).
* **For models:** a `list_assets(type, words)` lookup, in `toolkit` like
  every other lookup, offered to agents. It returns ids, names and
  descriptions, never paths or URLs. A model uses an asset by id.
* **A tool that makes a file** (§11) returns the new asset's id to whatever
  called it, a rule or a model, in place of the file.

## 11. Assets that tools make

* **`tool_calls` learns a new kind of result.** An MCP tool can return an
  image or audio, or a link to one. A result mapped to an asset is fetched or
  decoded, checked as its type, stored through `assets.add` with `origin:
  tool` and `made_with` filled in, and its id handed back.
* **Paid for and permitted like everything else.** The sponsor pays.
  `sponsor.will(<type's permit>)` decides, so a world can say no, and a
  shared world's creator pays only while logged in.
* **Asked once.** The same tool with the same arguments gives back the asset
  it made last time. The request is stored in `made_with`, so it can be
  matched rather than paid for twice.
* **The name and description come from the request**, and can be edited
  afterwards like any asset's.

## 12. Deleting, and admins

* **Who may delete:** whoever is charged for an asset, or an admin. A
  given-up asset is the admin's alone (§7.1).
* **An asset something uses cannot be deleted.** Each consuming type
  registers a `uses(asset)` query, and deleting says what is using the asset.
  An admin may force a delete, which leaves those users holding a missing
  asset rather than a broken reference.
* **Review:** `view assets recent [<n>]`, for admins, newest first, with who
  added each, where from and how big. Most of the review is reading the
  descriptions, so it reads well with a screen reader.
* **Confirmations:** deleting an asset, and forcing a delete, each get a
  `CONFIRMATIONS` entry.

## 13. The shared folder becomes the `world` type

* `export world` stores a `world` asset and stops writing to `worlds/`.
* `import world` opens a picker of `world` assets.
* `view exports` and `delete export` become `view assets world` and `delete
  asset`. The old spellings point to the new ones, the way retired commands
  already do.
* On first start, every file in `WORLD_DIRS` is added to the register as an
  asset charged to nobody, then left where it is. Keeping `WORLD_DIRS` lets an
  admin still drop a file in by hand, and a startup pass picks it up.
* Whether an export is `exchange.LEFT` or `CARRIED` does not change: the
  asset list in the document is new and named (§9).

## 14. Testing

* **Fetch:** each refusal planted against a local test server (loopback,
  private, link-local, metadata, an IPv6 mapped address, a redirect to each,
  a DNS answer that changes between the check and the connect), plus a body
  that lies about its length and one that never ends. No test touches the
  real network.
* **Types:** a file with the right extension and wrong contents is refused,
  a future version is refused by name, and the deny-list test fails on a
  code type.
* **Quota:** refused at the edge, an admin override, a duplicate costs
  nothing, a tool-made asset is charged to the sponsor's payer whoever caused
  it, and a full quota refuses a tool the way a missing key does.
* **The pool:** giving up frees the quota, the pool refuses an asset larger
  than itself, eviction takes the least used first and never the asset being
  given up, an evicted asset is missing everywhere it was used, and adopting
  moves it back onto a quota.
* **Owner warnings:** a world's creator is told when an asset it uses is
  given up, when it is next in line, and when it has gone. They are told at
  once if logged in, or at their next login if not, once each time, and never
  on entering the world. `view world` lists the given-up assets every time.
  Visitors are never warned.
* **Round trip:** export, then import elsewhere: a known hash is reused, an
  unknown one is fetched and checked, a wrong hash is missing, an
  unreachable URL is missing, and fetching again works.
* **Upload page:** login required, CSRF, an oversized file refused, the same
  checks as in game.
* **Never a path:** every message, listing and lookup result is checked for
  `server/`, `.media` and the store's root.
* **Plumbing:** `asset_quota` on accounts, and `asset_notices` (warnings
  waiting for an owner's next login), go in `exchange.LEFT` (the AST test makes
  sure), and the deletion confirmation is in `CONFIRMATIONS`.

## 15. Phases

* **Phase 0: the register.** The app, the model, the migration, the store
  interface and local store, the type register with `world`, and
  `assets.add`.
* **Phase 1: fetching.** `assets.fetch` and its tests. Nothing calls it yet
  but tests.
* **Phase 2: in game.** `create asset`, `view assets`, `edit asset`, `delete
  asset`, quota, giving up, the pool and its eviction, adopting, owner
  warnings, admin review and confirmations.
* **Phase 3: the website.** The upload page.
* **Phase 4: worlds.** Export lists assets and `import world` picks one. The
  shared folder is brought in, the old commands are retired, and import
  downloads and checks assets.
* **Phase 5: models and tools.** `list_assets`, results that become assets,
  and asked-once.
* **Phase 6: docs.** README, help, manual pages, and `future-plans.md`.

## 16. Decisions

* Assets are server-wide. Only whoever added one or an admin may delete it,
  and nothing still in use is deleted without an admin forcing it.
* Worlds carry their assets by name, hash and URL. Import reuses known
  hashes, fetches the rest, checks each hash, and marks failures missing.
* Every type is served by hash.
* Types arrive with the system that uses them, each with a permit. `world`
  is the only one now.
* Types read and accept versions.
* 500 MB default quota in settings, with per-account overrides. Charged to
  whoever paid for the file to exist, once, never to somebody reusing it, so
  money and disk always land on the same account.
* An asset in use can be given up to a server pool with its own quota (1 GB).
  When the pool is full, its least-used assets are deleted and marked
  missing. Any player may adopt a given-up asset onto their own quota.
* Owners of worlds using a given-up asset are warned when it is given up,
  when it is next in line to go, and when it has gone, so they can adopt it.
  Once each, at login or as it happens, and always in `view world`.
* Provenance includes the tool, model and settings for anything a tool
  made.
* Storage is swappable. Only the local store is built.

## 17. Settled

These were open questions, and are answered (2026-10-05):

1. **Drawbridge, not our own.** Pinned, used only inside `assets.fetch`, with
   our own byte cap and timeout around it. The §14 tests hold the guarantees,
   so replacing it later changes one function.
2. **A player's quota covers the worlds they import.** The importer is who
   brings the files to this server. A big world full of music can use up a new
   player's quota, and import says so before it starts, from the sizes the
   document lists.
3. **Freesound search is a later plan**, once there is a sound type to put
   results in. The record already has `author` and `licence` for it.

## 18. As built

Where the building departed from the plan above, and what it found.

* **A subject, not a maker (§5.1).** Everything in `world/making.py` is a fact
  about one world, listed by `listing(root)` and owned by that world's
  creator. An asset belongs to no world. So assets are
  `commands/assets_subject.py`, the shape `services_subject.py` already has
  for the other server-wide register.
* **`edit asset <name> giveup`, `adopt` and `fetch`, not `adopt asset`
  (§7.1, §9).** The verbs are fixed (`commands/subjects.py`), and all three
  change who an asset belongs to or whether it is here, which is editing it.
  The warnings say the command as built.
* **`~` does not fill a description yet (§5.1).** A model filling in what a
  file is would be describing a file it cannot see. It comes with images, as
  a vision model offered on purpose (`future-plans.md`).
* **Drawbridge's own size cap does nothing in stream mode.** A download is
  streamed to disk, and Drawbridge enforces `max_response_bytes` only for
  responses it reads whole. Our byte counter is the limit; a planted fault
  removing it lets an endless body through, and the tests go red.
* **Ports are a setting.** Drawbridge allows 80, 443, 8080 and 8443 by
  default, and an aimud's website is on 4001, so a world could not have been
  imported from another aimud. `ASSET_FETCH_PORTS` adds 4001; whatever it
  lists, nothing private is ever fetched.
* **A server that sends more than its `Content-Length` is cut at what it
  said.** That is HTTP framing, not something this code does. The lie that
  matters is no length and no end, and that is refused by the byte counter.
* **The upload view is CSRF-exempt and its inner function is protected.**
  Django's CSRF check reads the body, after which the upload handlers that
  stop an oversized file cannot be swapped in. That is Django's documented
  pattern, and a test without a token gets 403 and keeps nothing.
* **The shared folder's functions are gone (§13).** `exchange.write`,
  `read`, `remove`, `available` and `folder` had no callers once export and
  import moved to assets; `directories()` stays for `take_in_folder`. The old
  tests of the folder became tests of taking it in.
* **`view exports` and `delete export` say what is typed now**
  (`commands/exchange_subject.py`) rather than doing it under another name.
* **Two more origins:** `export` (from `export world`) and `folder` (put in
  `WORLD_DIRS` by hand). The migration was regenerated rather than added to,
  since it had never been applied anywhere.
* **`uses(asset)` answers `{"said", "world"}`, and `used_in(world)` was
  added (§12, §9).** Deleting needs what to say, warning needs whose world,
  and exporting needs the reverse question.
* **A world's document lists `assets` only when it uses any (§9),** so every
  world exported before this exports exactly as it did.
* **Tool results that are files are kept, but no rule reaches them yet
  (§11).** `services.Answer.files` holds the images, sounds and blobs a tool
  sends back, `assets.from_tool` keeps one charged to the sponsor's payer
  with its `made_with`, and `assets.made_before` finds a repeat. Nothing in a
  rule can hold an asset's id until a type has a consumer, so the
  `tool_calls` mapping waits for MSP. So does `assets.picker` (§10), which
  wants a form to sit in. Both are in `future-plans.md`.
* **Fixture accounts are Developers**, which outranks Admin, so the command
  tests take that away and give `Admin` back only where a test wants an
  admin.
* **Not watched live:** an upload from a real browser, a fetch over the real
  internet, and an import from a second aimud. The server needs `evennia
  migrate` for the new table before any of it runs.
