## Basic Principles

We are creating the mud I wish existed, and a foundation to build and generate the kinds of games and worlds I've always wanted to play, as a blind screen reader user locked out of many main-stream gaming experiences.

AI Mud is inspired by:
* muds like Alter Aeon, Lost Souls, Aardwolf, DIKU, discworld, Triad City, and Procedural Realms
* AAA games like The Sims, Sim City, Rimworld, Dwarf Fortress, worldbox, and Minecraft
* interactive fiction like Zork and The Hobbit
* companies like Infocom, Smart Monsters, and Magnetic Scrolls
* creation systems like Inform7, moo, mush, LPC, ZIL, coffeemud, wheelmud, and TADS
* AI projects like AIML, pixelmind, 20questions.net/20q, AI Dungeon, Friends and Fables, SHRDLU, racter and The Policeman's beard is half-constructed, megahal, the Dadadodo stochastic text generator, recursive transition networks, rmutt, the dada engine, and Mark V. Shaney

These are the basic principles for what I am trying to build:
* generative gameplay: every system and feature we build should support generative gameplay, and avoid hardcoding behaviors or interactions whenever possible.
* hardcoded rules: every rule we hardcode should use existing systems where possible
* system reuse: if a new behavior or feature can reuse an existing system, or be built entirely with it, it should do so. If multiple systems are growing the same subsystem inside themselves, that system should be pulled out and made generic for everything to share.
* library reuse: we should avoid re-inventing techniques if something that fits already exists
* system interaction: all systems should interact with one another. AIMud is a set of interlocking and interacting systems, not a set of independent systems running alongside each other
* Many AI techniques: LLMs are one technique of many. They should not be the star of the show, and should be used where they make sense, along with other available techniques. AIMud already uses wordnet, conceptnet, learnings from inform7, research from SHRDLU, research from linguistics and NLP, the HAP planning engine from Carnegie Mellon University's OZ project, state machines, and more. This is AIMud, not LLMMud. Each technique should be used where it is best able to support and assist the other systems.
* an open sandbox: players should be able to examine and understand the state of the world and its systems. NPC characters, player characters, and AI assistants should all have equal access to the world.
* low population, distributed servers: AIMud is a mud to be hosted for yourself, and perhaps some friends. It is not a monolith where everyone plays on a single mud. We should support each server and world being unique and diverging in fun and interesting ways, similar to Minecraft servers, with hundreds of mods running on thousands of smaller servers for friends and families to play together. It should also be fun to play on your own.
* AIMud is a state of the art text game: using ram, hard disc, and CPU is okay, the same way it would be for a state of the art graphical game. However, AIMud, as it is text only, should be able to create better, more in depth, more customizable, and more interesting gameplay than a graphical game could with the same resources.
* security: no player, character, model, or rule can write Python code from inside the game. Python code can only be added by a server administrator installing a plugin. Should a small programming language turn out to be needed, it must be scoped, programs must be buildable via menus, in-game tools and systems, or in-game commands, and it should only be able to modify the game itself via other existing systems, not via filesystem or network access. Generous recursion should be permitted, but with guards to prevent run-away loops. Network access may only be provided to in-game entities via strictly scoped surfaces, like MCP servers added to the world, API's offered by AI providers, federation with other AIMud servers, or on-demand in-game resource downloads and update checks. Nothing inside the game should be able to make uncontrolled network requests directly.
* text should have the chance to be grounded and meaningful: text should never exist if it will always be exclusively decoration, and can never be promoted to affect a game system in some way.
* a world that remembers, grows, and changes: the world, items, and characters should be able to change over time, grow in logical and meaningful ways, and create meaningful stories and experiences for players and characters.
* no censorship: players should be able to create and have any experience they wish. It is not our place to police players for violence, content, or other taboos. 