These are plans for things I want to do later. Not fully scoped yet, still in the idea stage. But we should make current decisions that will allow for them later where possible. Remove items from here when they're done.

* should we use our verb conjugator to write memories in past tense? Would this help or hurt us?
* more grammar work: "and" to specify multiple specific objects ("get the blue ball and the yellow ball"), then to specify a second command ("get the yellow ball and then drop it"). Before and after are not needed. Should recurse for "get the blue ball and the yellow ball and the red ball then drop it and throw the yellow ball". Stop after first failure. No need to be atomic or roleback partly executed commands of this type. Can't just run all check rules in advance because "get the red ball then eat the red ball then throw the red ball" would fail after step 2, but if checked up front all steps would be possible. "and" and "then" should work with all built-in and generated verbs and rules without issues, I think.
* activitypub: fediverse login instead of account system. Use https://codeberg.org/socialhome/federation or takahe https://github.com/jointakahe/takahe?
    * allow logins from an activitypub account: better security, replace our account system, people get whatever security (two factor etc) there server offers?
    * post to fediverse accounts from aimud?
    * our characters can be fediverse actors?
* show when busy: show something every 10-15 seconds when an LLM is processing for a player so they know things are happening and the mud didn't just crash
* new action: rules can show player a menu with options to pick and get returned the result chosen
* disambiguation uses Evennia's built-in functions to show players a menu to pick the object they meant or quit
* MSP (mud sound protocol) allowing associating sounds with actions or room kinds/traits, perhaps generating sounds with
 elevenlabs, or letting world creators provide sounds by url? Needs to intigrate with the webserver so clients supporting MSP can get the sounds.
* gmcp/msdp: sending all the data we have via OOB protocols to mud clients in a standard machine-readable format, so
they can use mappers, create health gages, etc.
* mccp (mud client compression protocol): to save bandwidth for hosted worlds.
* MXP: clickable menus based on the world's kinds/verbs/rules? Image generators for pictures of items, characters, and rooms?
* full menu-based building of worlds for players who want to create something fun without having to use AI: create
rooms, characters, rules, etc. Give npcs goals, and so on.
* shared worlds: players can share worlds and play together. a world uses the key of the person who created it.
Worldmode gets extended to have a "none" option, and is always in none mode if the creator is logged out, so other
players can experience what's there without costing money. Npcs pick random actions or random goals from the list of
current possible actions or goals when idle, instead of using an LLM, when worldmode is none. Something similar to AIML
is used to let NPCs answer basic questions like "What do you want?" without an LLM in worldmode none. Ways for llms to
create AIML entries for characters, as well as menu based creator for players to create AIML files and attach them to
characters. In theory an entire mud that could run with wordnet, commonsense, and no LLM at all if players want to be
the builders. Just depend on AIML here maybe? But replace support for JavaScript with ability to execute an action instead.
* allow changing the api url so players can use providers other than openrouter if they want (nano-gpt.com is the
primary use case)
* do something interesting with the web interface. Web editor? Examine stats in the browser? Prettier looking interface
for playing in browser? Ability to read help files and documentation online, with hyperlinks?
* let characters use Evennia's built-in discord/IRC support so characters can reach out of their world
* world import and export? Players can create interesting worlds and export them to be played by people on other aimud
instances
* affect plugins: let players write Python code that can be added to worlds as unique affects the other systems can use,
 expanding the hardcoded menu. Let them share plugins with other aimud owners. All the hardcoded lists and vocabularies
should be extendable via plugin, so worlds can become unique in ways our models can't make them.
* federation: I3 or IMC to let players chat with each other over different muds. Make it social without requiring one
central mud for everyone. Or via activitypub? Or xmpp? Or matrix?
* massive security audit: before hosting this for other people. Make sure API keys won't leak, money can't be spent
unexpectedly, etc.
* secure mud connections via SSL for remotely hosted worlds. Players shouldn't have to pass API keys over unencrypted connections unless they want to
* some sort of npc emotion system? Personality arcatypes? Memory already has support for NPC emotions somehow. Support this in the mud with emotions on npcs and rule conditions and actions about them?
* mcp servers: let other AI's play? Give generators and npcs new tools?
* editor improvements: evennia's editor is based on vi and confusing. Let "@" on a blank line stop editing, the same way MOO does it. Support the local editor OOB protocol and MUD Client Protocol v2.1 for players who have better editors
* Agent Client Protocol (ACP): let your coding agent or claude join you in the mud and help you make things? By its nature this mud welcomes players and bots on equal footing. The idea is have fun, no matter who or what you are.
* Plural objects as a single bound thing: use wordnet or something for better pluralizing. Objects with a quantity trait that reduces and is plural. Somehow without hardcoding? Can we do better than the verb tenses Evennia already gives us with wordnet/conceptnet?
* Co-ownership and institutional owners: worth having for corporations, countries, gangs, guilds, etc.
* define command: just for player interest. define returns everything conceptnet and wordnet both know about a term. Useful for players to get ideas if they're building themselves with no LLM. And things they build can get associated with wordnet senses, so players will need the ability to explore the lexicons anyway.
* add term: allow players to add terms on top of the wordnet and conceptnet lexicons? Then players could invent terms for there worlds that all the other machineries could reuse. Don't think models should be doing this.
* tools for the models: tools the models can use to explore the lexicons, to get ideas if they know they want to make a type of sword or something?
* go through Evennia's crafting contrib. Could our rules and actions express everything here if fully used? If not, what are we missing? https://www.evennia.com/docs/latest/Contribs/Contrib-Crafting.html
* a hand-built "endless alchemy" world, that ships with aimud. Gives the player earth, air, fire, and water. Let's them combine two of them, and the LLM decide what results from combining two things. Contains hand-built npc with a quest chain asking for different things for the player to try and make. Demonstrates hand-built rules and models working together, and how the player can build something fun that's more of a classic game shape, and the LLM can expand on it. With tutorial doc explaining how the world was made. Updated as new features are added, as the flagship to demonstrate what aimud is capable of.
* a hand-built world that ships with aimud based on the 1979 computer game Taipan! and multiplayer derivatives like Dope Wars, but with spaceships and planets instead. Makes sure we can express everything in our system that we think we can. Again demonstrates hand-coded rules and an LLM working together. Second flagship world. Shows off multiplayer: all characters would affect the economy.
* Worldrenew command to set a world back to just things included by default/that the player built, so players can reset a world without losing all the custom work. So it's unplayed again but still a custom world, not a blank one like worldreset would make. Add a warning to the prompt that requires confirm letting players know if worldreset would delete something a player built custom and suggesting worldrenew instead. Add a command so a player can hoist something the llm made into being a default part of the world that worldrenew keeps.
* let worlds give the player things the first time they enter a world they've never played before. Endless alchemy can give them the first stock of substances to try with, Taipan! can give them money to purchase a spaceship, and so-on.
* let players configure what llms can do in a world they build. Allow endless alchemy to generate new objects/kinds, but not new verbs/rooms/npcs. Allow Taipan! to generate everything so space and planets can expand endlessly. Switch should be "llm can generate based on player action", "llm can generate based on any action", or "llm cannot generate at all" for each type of thing.
* allow players to configure npc autonomy per world or per character: "npcs can idle and react based on probability, or npcs only react to direct mentions from the player. Npcs can generate goals, npcs can make plans and attempt them". If a player builds a world where one NPC is critical to a quest or puzzle, we don't want them wandering off to Jupiter, having children, and then getting killed by a monster. But we do want them to talk to the player.
* allow objects from templates: every coin can be the same. In a world that doesn't track differences between bottles of beer or barrels of wool, generating a new one doesn't need an LLM call. Not sure how/if models can use this without risking them just always making the same object everywhere? Maybe if the model asks for an object with an identical name to one that already exists in this world, just make an exact copy of it? Once generated from a template it's a complete object that can be modified etc. Point is to save pointless LLM calls, and let players make rules that can generate items and npcs based on rules in a world where worldmode is none.
* pronouns in a player's own speech: an NPC's "says" and emotes are rendered per watcher now, so a talkative character reads "He says" after the first line, but a player's speech is still Evennia's `at_say` building the line per receiver with its own funcparser, so watching another player talk names them in full every time. Wants `at_say` reimplemented over `events` -- `msg_self`, `receivers`, whispers and the `msg_type` hooks all go through it, which is why P4 left it alone.
