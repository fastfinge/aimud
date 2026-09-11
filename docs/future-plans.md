These are plans for things I want to do later. Not fully scoped yet, still in the idea stage. But we should make current decisions that will allow for them later where possible.

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
for playing in browser?
* let characters use Evennia's built-in discord/IRC support so characters can reach out of their world
* world import and export? Players can create interesting worlds and export them to be played by people on other aimud
instances
* affect plugins: let players write Python code that can be added to worlds as unique affects the other systems can use,
 expanding the hardcoded menu. Let them share plugins with other aimud owners. All the hardcoded lists and vocabularies
should be extendable via plugin, so worlds can become unique in ways our models can't make them.
* federation: I3 or IMC to let players chat with each other over different muds. Make it social without requiring one
central mud for everyone.
* massive security audit: before hosting this for other people. Make sure API keys won't leak, money can't be spent
unexpectedly, etc.
* secure mud connections via SSL for remotely hosted worlds. Players shouldn't have to pass API keys over unencrypted connections unless they want to
* some sort of npc emotion system? Personality arcatypes? Memory already has support for NPC emotions somehow. Support this in the mud with emotions on npcs and rule conditions and actions about them?
* mcp servers: let other AI's play? Give generators and npcs new tools?
* editor improvements: evennia's editor is based on vi and confusing. Let "@" on a blank line stop editing, the same way MOO does it. Support the local editor OOB protocol and MUD Client Protocol v2.1 for players who have better editors
* Agent Client Protocol (ACP): let your coding agent or claude join you in the mud and help you make things? By its nature this mud welcomes players and bots on equal footing. The idea is have fun, no matter who or what you are.

