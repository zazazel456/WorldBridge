"""Italian texts of WorldBridge: English source text -> Italian (see i18n.py).  Generated
section by section; edit freely, keeping the {placeholders} of the English text."""

_SECTIONS = {
    'worldbridge/cli.py': {
        '--move-to moves the selected chunks: give --chunks too':
            '--move-to sposta i chunk selezionati: indica anche --chunks',
        "--version: '{version}' is not a version number (e.g. 1.20.1 or 26.3)":
            "--version: '{version}' non è un numero di versione (es. 1.20.1 o 26.3)",
        "--version: {version} is not a {edition} version WorldBridge knows (see 'worldbridge versions')":
            "--version: {version} non è una versione {edition} che WorldBridge conosce (vedi 'worldbridge versions')",
        'Note: {version} is written as {known}, the newest version WorldBridge knows before it; the game upgrades it when the world is opened.':
            'Nota: {version} viene scritta come {known}, la versione più recente che WorldBridge conosce prima di essa; il gioco la aggiorna all\'apertura del mondo.',
        'DURATION':
            'DURATA',
        'minimum time spent near a chunk to keep it (e.g. 30s, 1m, 5m, 2h or ticks; default 1m)':
            'tempo minimo di permanenza per tenere un chunk (es. 30s, 1m, 5m, 2h o tick; predefinito 1m)',
        'chunks kept around every used chunk (default 1)':
            'chunk tenuti attorno a ogni chunk usato (predefinito 1)',
        'chunks around the spawn always kept (default 2, -1 = none)':
            'chunk attorno allo spawn sempre tenuti (predefinito 2, -1 = nessuno)',
        'do not protect the chunks loaded with /forceload':
            'non proteggere i chunk caricati con /forceload',
        'also remove the chunks whose InhabitedTime cannot be read':
            'rimuove anche i chunk di cui non si riesce a leggere InhabitedTime',
        'Trim not available: {error}':
            'Trim non disponibile: {error}',
        '{dim}: kept {kept} / {total}':
            '{dim}: tenuti {kept} / {total}',
        'Total: {summary}':
            'Totale: {summary}',
        'Selection saved to {path}':
            'Selezione salvata in {path}',
        'Give an output folder to write the trimmed world (the original world is not touched).':
            'Indica una cartella di output per scrivere il mondo ripulito (il mondo originale non viene toccato).',
        "For this format the trim is applied while converting: use 'convert ... --trim'.":
            "Per questo formato il trim si applica durante la conversione: usa 'convert ... --trim'.",
        'Done: {n} chunks removed · {before} → {after}  ({path})':
            'Fatto: {n} chunk rimossi · {before} → {after}  ({path})',
        'universal Minecraft world converter':
            'convertitore universale di mondi Minecraft',
        "language of the messages (default: the system's)":
            'lingua dei messaggi (predefinita: quella del sistema)',
        'recognise the format of a world':
            'riconosce il formato di un mondo',
        'convert a world':
            'converte un mondo',
        'output folder (it will be created)':
            'cartella di destinazione (verrà creata)',
        'auto = latest version by the best route; dfu = a world upgraded by the game; amulet = pre-converted to --version':
            'auto = ultima versione col percorso migliore; dfu = mondo aggiornato dal gioco; amulet = pre-convertito alla --version',
        'target version inside the chosen format: --java-mode numeric 1.2 … 1.12; mcregion b1.3, b1.4, b1.5, b1.6, b1.7, b1.8, 1.0, 1.1; alpha: alpha (Alpha 1.2.x), b1.2 (Beta 1.0 – 1.2_02, default)':
            'versione di destinazione dentro al formato scelto: --java-mode numeric 1.2 … 1.12; mcregion b1.3, b1.4, b1.5, b1.6, b1.7, b1.8, 1.0, 1.1; alpha: alpha (Alpha 1.2.x), b1.2 (Beta 1.0 – 1.2_02, predefinito)',
        'target version (e.g. 1.20.1 or 1.21.0)':
            'versione di destinazione (es. 1.20.1 o 1.21.0)',
        'LCE platform: win64, xbox360, ps3, wiiu, vita, ps4, xboxone, switch':
            'piattaforma LCE: win64, xbox360, ps3, wiiu, vita, ps4, xboxone, switch',
        'LCE console version: tu54 (default), tu46, tu31. Windows64 is always neoLegacy TU31':
            'versione LCE delle console: tu54 (predefinita), tu46, tu31. Windows64 è sempre neoLegacy TU31',
        'width of the LCE world in chunks (54, 64, 192, 320; default 320 for Windows64/PS4/XB1/Switch/Wii U, 54 for X360/PS3/Vita)':
            'larghezza del mondo LCE in chunk (54, 64, 192, 320; predefinito 320 per Windows64/PS4/XB1/Switch/Wii U, 54 per X360/PS3/Vita)',
        'centre the LCE world on the spawn':
            'centra il mondo LCE sullo spawn',
        'source chunk that becomes the centre of the LCE world (x,z)':
            'chunk sorgente che diventa il centro del mondo LCE (x,z)',
        'name of the target world':
            'nome del mondo di destinazione',
        'LCE PC/Xbox/Wii U/Switch: the id of the main player (its file name in players/: the XUID on PC and Xbox, 32 hex digits on Wii U)':
            'LCE PC/Xbox/Wii U/Switch: id del giocatore principale (il nome del suo file in players/: lo XUID su PC e Xbox, 32 cifre esadecimali su Wii U)',
        'Java / Bedrock 1.18+: no game blending (the chunks of a pre-1.18 world are written in the new format: the game does not blend them with new terrain nor generate the part below y 0)':
            'Java / Bedrock 1.18+: niente blending del gioco (i chunk di un mondo pre-1.18 vengono scritti nel formato nuovo: il gioco non li fonde col terreno nuovo e non genera la parte sotto y 0)',
        'no WorldBridge ring (Java Alpha 1.2 – 1.17, neoLegacy, Nether and End) and no filling of finite maps (PE 0.x, LCE 54 / 64 chunks)':
            'niente anello di raccordo di WorldBridge (Java Alpha 1.2 – 1.17, neoLegacy, Nether ed End) e niente riempimento delle mappe finite (PE 0.x, LCE 54 / 64 chunk)',
        '128-block-high worlds (Alpha, Beta, Java 1.0 – 1.1, PE 0.x): taller mountains are compressed (default: the surface comes down whole) or cut at y 127':
            'mondi alti 128 blocchi (Alpha, Beta, Java 1.0 – 1.1, PE 0.x): le montagne più alte vengono compresse (predefinito: la superficie scende intera) oppure tagliate a y 127',
        '1.18+ worlds to games that start at y 0: auto = flat or low worlds keep their underground, the others are cut (default); cut = the underground below y 0 is dropped, keep = everything kept (the world rises by 64), negative Y = kept from that y':
            'mondi 1.18+ verso giochi che partono da y 0: auto = i mondi piatti o bassi tengono il sottosuolo, gli altri vengono tagliati (predefinito); cut = il sottosuolo sotto y 0 sparisce, keep = tutto tenuto (il mondo sale di 64), Y negativo = tenuto da quella y',
        'do not convert the Nether / the End: the game generates them anew when first entered (repeatable)':
            "non converte il Nether / l'End: il gioco li genera da capo al primo ingresso (ripetibile)",
        'convert only the chunks of an MCA Selector CSV file (DIM = overworld, nether, end; repeatable). Dimensions without a file are left out':
            'converte solo i chunk del file CSV di MCA Selector (DIM = overworld, nether, end; ripetibile). Le dimensioni senza file vengono escluse',
        'BIOME':
            'BIOMA',
        'give a biome (name or number, e.g. plains, swampland, cherry_grove) to the chunks of an MCA Selector CSV; repeatable':
            'dà il bioma (nome o numero, es. plains, swampland, cherry_grove) ai chunk del CSV di MCA Selector; ripetibile',
        'new world spawn point':
            'nuovo punto di spawn del mondo',
        'move the selected chunks (--chunks): their centre goes to the world centre (0, 0) or to the given X,Z coordinates, with the entities, spawn and players on them':
            'sposta i chunk selezionati (--chunks): il loro centro va al centro del mondo (0, 0) o alle coordinate X,Z date, con entità, spawn e giocatori che ci stanno sopra',
        'KEY':
            'CHIAVE',
        "players to transfer (the first becomes the main player) and the nicknames to link them to; KEY as shown by 'worldbridge players'. Repeatable":
            "giocatori da trasferire (il primo diventa il giocatore principale) e nickname a cui collegarli; CHIAVE come mostrata da 'worldbridge players'. Ripetibile",
        'Java: use offline UUIDs (non-premium servers)':
            'Java: usa gli UUID offline (server non premium)',
        "Better than Adventure: .properties file choosing the vanilla woods of BTA's painted wood (see worldbridge/bta/data/palette.example.properties)":
            'Better than Adventure: file .properties che sceglie i legni vanilla del legno dipinto BTA (vedi worldbridge/bta/data/palette.example.properties)',
        'Better than Adventure: how many blocks to lower the Overworld (default automatic: the BTA sea ends at y 63, e.g. 65 for "extended" worlds)':
            'Better than Adventure: di quanti blocchi abbassare l\'overworld (predefinito automatico: il mare BTA finisce a y 63, es. 65 per i mondi "extended")',
        'convert only the chunks really used (world trim by InhabitedTime; default: < 1 minute = removed, 1-chunk protective ring, spawn ±2 chunks)':
            'converte solo i chunk davvero usati (world trim su InhabitedTime, predefinito: < 1 minuto = rimosso, anello di protezione di 1 chunk, spawn ±2 chunk)',
        'copy of the world without the chunks never used (world trim by InhabitedTime)':
            'copia del mondo senza i chunk mai usati (world trim su InhabitedTime)',
        'folder of the trimmed world (it will be created)':
            'cartella del mondo ripulito (verrà creata)',
        'only show how many chunks would be removed':
            'mostra solo quanti chunk verrebbero rimossi',
        'save the chunks to keep (Overworld) as an MCA Selector selection':
            'salva i chunk da tenere (overworld) come selezione MCA Selector',
        'list the players saved in a world':
            'elenca i giocatori salvati in un mondo',
        'list the supported Java / Bedrock versions':
            'elenca le versioni Java/Bedrock supportate',
        'Format not recognised':
            'Formato non riconosciuto',
        'path: {path}':
            'percorso: {path}',
        'name: {name} · save version {version}':
            'nome: {name} · versione salvataggio {version}',
        'Overworld “{type}” (sea at y {sea}): it will be lowered by {blocks} blocks':
            'overworld «{type}» (mare a y {sea}): verrà abbassato di {blocks} blocchi',
        '{dim}: {n} regions':
            '{dim}: {n} regioni',
        'possible target: Java 26.3 (--to java)':
            'destinazione possibile: Java 26.3 (--to java)',
        'Note: Alpha and Beta up to 1.2_02 only see the World1 … World5 folders of .minecraft/saves: rename the output folder to one of them.':
            'Nota: Alpha e Beta fino alla 1.2_02 vedono solo le cartelle World1 … World5 di .minecraft/saves: rinomina la cartella di output in una di queste.',
        'Cancelled':
            'Annullato',
        'Error: {error}':
            'Errore: {error}',
        'Done: {path}  ({n} chunks, {seconds}s)':
            'Fatto: {path}  ({n} chunk, {seconds}s)',
        "expected {n} numbers separated by commas (e.g. {example}), not '{value}'":
            "servono {n} numeri separati da virgole (es. {example}), non '{value}'",
        "expected auto, cut, keep or a height such as -64, not '{value}'":
            "serve auto, cut, keep o un'altezza come -64, non '{value}'",
        'file not found: {path}':
            'file non trovato: {path}',
        "expected BIOME=[DIM:]FILE, not '{value}'":
            "serve BIOMA=[DIM:]FILE, non '{value}'",
        '{option} {file}: no chunk coordinates found (an MCA Selector CSV file is expected)':
            '{option} {file}: nessuna coordinata di chunk trovata (serve un file CSV di MCA Selector)',
        'contains: {description}':
            'contiene: {description}',
    },
    'worldbridge/convert.py': {
        'Finite map: only the chunks that reach it (with a margin for its edge) are translated.':
            'Mappa finita: vengono tradotti solo i chunk che la raggiungono (con un margine per il bordo).',
        '{version} (latest)':
            '{version} (ultima)',
        'Java Edition 1.9 → latest (upgraded by the game)':
            'Java Edition 1.9 → ultima (aggiornato dal gioco)',
        'Translating the blocks to the numeric Java 1.12.2 format with Amulet…':
            'Traduzione dei blocchi in formato numerico Java 1.12.2 con Amulet…',
        'Source format not supported: {kind}':
            'Formato sorgente non supportato: {kind}',
        '--java-limit {limit} is not valid for the {format} format: use {choices}':
            '--java-limit {limit} non valido per il formato {format}: usa {choices}',
        'The output folder is not empty: {path}':
            'La cartella di destinazione non è vuota: {path}',
        'Analysing the source world':
            'Analisi del mondo sorgente',
        'World format not recognised. Choose the world folder or the save file.':
            'Formato del mondo non riconosciuto. Seleziona la cartella del mondo o il file di salvataggio.',
        'The archive does not contain a recognised world.':
            "L'archivio non contiene un mondo riconosciuto.",
        'Source: {description}  ({path})':
            'Sorgente: {description}  ({path})',
        'Working copy of the source world (the original is never opened for writing)…':
            "Copia di lavoro del mondo sorgente (l'originale non viene mai aperto in scrittura)…",
        'Target: {target}  ({path})':
            'Destinazione: {target}  ({path})',
        'Selection: {n} chunks':
            'Selezione: {n} chunk',
        'Nether and End: not converted, the game generates them anew when first entered.':
            'Nether e End: non convertiti, il gioco li genera da capo al primo ingresso.',
        '{dim}: not converted, the game generates it anew when first entered.':
            '{dim}: non convertito, il gioco lo genera da capo al primo ingresso.',
        '{n} chunks the game had not finished (at the edge of the explored area: only planned or bare rock) are not converted: the game or the ring generates them properly.':
            "{n} chunk non ancora completati dal gioco (ai margini dell'area esplorata: solo pianificati o roccia nuda) non vengono convertiti: il gioco o il raccordo li generano come si deve.",
        'sub chunk {y} of chunk {cx}, {cz} (dimension {dim}) not found':
            'sub-chunk {y} del chunk {cx}, {cz} (dimensione {dim}) non trovato',
        'record {key} not found':
            'record {key} non trovato',
        '{n} chunks the game had not finished are kept: Minecraft finishes them when it loads them.':
            'I {n} chunk non ancora completati dal gioco vengono mantenuti: Minecraft li completa quando li carica.',
        'The {n} chunks Bedrock had not finished hold {tiles} block entities and {entities} entities (villages, dungeons...): they are lost with the chunks.':
            'I {n} chunk non completati da Bedrock contengono {tiles} blocchi-entità e {entities} entità (villaggi, dungeon...): vanno persi insieme ai chunk.',
        'Copying the world (Minecraft will upgrade it with its own blending)':
            'Copia del mondo (Minecraft lo aggiornerà con il blending ufficiale)',
        'Copying the world (Minecraft will upgrade it when it is opened)':
            "Copia del mondo (Minecraft lo aggiornerà all'apertura)",
        "The target version is the same as the world's or newer: the world is kept as it is, and Minecraft upgrades it with its own upgrade when it is opened.":
            "La versione di destinazione è uguale a quella del mondo o più recente: il mondo viene mantenuto così com'è e Minecraft lo aggiorna con il proprio aggiornamento all'apertura.",
        'The world is pre-1.18: it is kept as it is; when it is opened, Minecraft runs its own upgrade, blending terrain and biomes.':
            "Il mondo è pre-1.18: viene mantenuto così com'è; all'apertura Minecraft esegue l'aggiornamento ufficiale con blending di terreno e biomi.",
        'Completed':
            'Completato',
        'Reading the source world':
            'Lettura del mondo sorgente',
        'Java route: explicit conversion to the latest version':
            "Percorso Java: conversione esplicita all'ultima versione",
        'Java route: numeric world upgraded by Minecraft itself when opened':
            "Percorso Java: mondo numerico aggiornato automaticamente da Minecraft all'apertura",
        'Sea level: y {source} in the source world, y {target_sea} in {target}: the converted world is raised by one block (player and spawn included).':
            'Livello del mare: nel mondo di origine è a y {source}, in {target} a y {target_sea}: il mondo convertito viene alzato di un blocco (giocatore e spawn compresi).',
        'Sea level: y {source} in the source world, y {target_sea} in {target}: the converted world is lowered by one block (player and spawn included).':
            'Livello del mare: nel mondo di origine è a y {source}, in {target} a y {target_sea}: il mondo convertito viene abbassato di un blocco (giocatore e spawn compresi).',
        'Superflat world: the game continues the same flat terrain past the edge, no ring needed.':
            'Mondo superpiatto: il gioco continua lo stesso terreno piatto oltre il bordo, nessun anello necessario.',
        '"Customized" world: its generator has settings of its own that WorldBridge does not reproduce, so a step will remain where the converted world ends.':
            'Mondo "personalizzato" (customized): il suo generatore ha impostazioni proprie che WorldBridge non riproduce, dove finisce il mondo convertito resterà un gradino.',
        'Converting {n} chunks':
            'Conversione di {n} chunk',
        'Terrain heights':
            'Altezze del terreno',
        'Terrain heights {i}/{n}':
            'Altezze del terreno {i}/{n}',
        'Mountains up to y {top}: the part above y {knee} is compressed (to {ratio} %) to stay under the y {limit} limit; surface, trees and buildings come down whole.':
            'Montagne fino a y {top}: la parte sopra y {knee} viene compressa (al {ratio} %) per stare sotto il limite di y {limit}; superficie, alberi e costruzioni scendono interi.',
        'Chunk {done}/{total}':
            'Chunk {done}/{total}',
        'Terrain around the converted world ({target})':
            'Terreno intorno al mondo convertito ({target})',
        'Finite world filled: {n} chunks of natural terrain around the converted world, meeting its edge (up to {width} chunks); trees and ores are added by the game.':
            'Mondo finito riempito: {n} chunk di terreno naturale intorno al mondo convertito, raccordati al suo bordo (fino a {width} chunk); alberi e minerali li aggiunge il gioco.',
        "Ring: {n} chunks of the game's terrain (seed {seed}) around the converted world, raised or lowered smoothly to meet its edge, 3 to {width} chunks wide depending on the height difference; {trees} trees like those of the edge, the rest (the biomes' trees, ores, lakes) is added by the game.":
            'Raccordo: {n} chunk di terreno del gioco (seed {seed}) intorno al mondo convertito, alzato o abbassato dolcemente fino al suo bordo, larghi da 3 a {width} chunk secondo il dislivello; {trees} alberi come quelli del bordo, il resto (alberi dei biomi, minerali, laghi) lo aggiunge il gioco.',
        'Converted Nether edge (reading)':
            'Bordo del Nether convertito (lettura)',
        'Converted End edge (reading)':
            "Bordo dell'End convertito (lettura)",
        '{n} chests in rows of side-by-side double chests become trapped chests, one pair in two: the target game joins every chest with any chest next to it and would not draw half of the pairs. Every chest keeps its contents.':
            '{n} casse in file di casse doppie affiancate diventano casse-trappola a coppie alterne: il gioco di destinazione unisce ogni cassa a qualsiasi cassa accanto e non disegnerebbe metà delle coppie. Il contenuto resta in ogni cassa.',
        '{n} chests had no contents (block entity) in the source world or in the translation: they were written empty, so at least they are visible.':
            '{n} casse non avevano il loro contenuto (blocco-entità) nel mondo di origine o nella traduzione: sono state scritte vuote, così almeno si vedono.',
        '{n} chunks of the source world were unreadable (damaged or truncated) and were skipped: Minecraft will generate them again.':
            '{n} chunk del mondo di origine erano illeggibili (danneggiati o troncati) e sono stati saltati: Minecraft li rigenererà.',
        '{n} chunks were left empty by the height limit: everything in them lies outside the target game\'s world (y 0 to 255), mostly below y 0. To keep what lies below y 0 use --depth keep (the world rises by 64 blocks) or a lower Y, e.g. --depth -32 (in the app: Underground of 1.18+ worlds).':
            '{n} chunk sono rimasti vuoti per il limite di altezza: tutto quello che contengono sta fuori dal mondo del gioco di destinazione (da y 0 a 255), per lo più sotto y 0. Per tenere quello che sta sotto y 0 usa --depth keep (il mondo sale di 64 blocchi) o una Y più bassa, ad es. --depth -32 (nell\'app: Sottosuolo dei mondi 1.18+).',
        'Height limit: {tiles} block entities (chests, signs, spawners…) and {entities} entities stood on blocks that were cut (under the kept underground, above y 255 or inside the rock removed from the mountains) and were lost with them.':
            'Limite di altezza: {tiles} blocchi-entità (casse, cartelli, spawner…) e {entities} entità stavano su blocchi tagliati (sotto il sottosuolo tenuto, sopra y 255 o dentro la roccia tolta dalle montagne) e sono andati persi con loro.',
        'Underground (automatic): no blocks found in the sampled chunks, what lies below y 0 is cut (--depth keep keeps it).':
            'Sottosuolo (automatico): nessun blocco trovato nei chunk campionati, quello che sta sotto y 0 viene tagliato (--depth keep lo tiene).',
        'Underground (automatic): the surface of this world is mostly below y 0 (median y {y}): the whole underground is kept and the world rises by 64 blocks.':
            'Sottosuolo (automatico): la superficie di questo mondo sta per lo più sotto y 0 (mediana y {y}): tutto il sottosuolo viene tenuto e il mondo sale di 64 blocchi.',
        'Underground (automatic): the surface of this world is above y 0 (median y {y}): what lies below y 0 is cut (--depth keep keeps it).':
            'Sottosuolo (automatico): la superficie di questo mondo sta sopra y 0 (mediana y {y}): quello che sta sotto y 0 viene tagliato (--depth keep lo tiene).',
        'Mountain compression: {n} block entities (chests, spawners…) were inside the removed rock and were lost.':
            'Compressione delle montagne: {n} blocchi-entità (casse, spawner…) erano dentro la roccia tolta e sono andati persi.',
        '{blocks} blocks, {tiles} block entities (chests, signs, spawners…) and {entities} entities above y {limit} did not fit under the height limit of the target game (the compression could not lower them, or the terrain is cut) and were cut.':
            '{blocks} blocchi, {tiles} blocchi-entità (casse, cartelli, spawner…) e {entities} entità sopra y {limit} non entravano nel limite di altezza del gioco di destinazione (la compressione non è riuscita ad abbassarli, oppure il terreno è tagliato) e sono stati tagliati.',
        'Builds up to y {top} (floating islands, towers): they come down whole, with the ground under them, to stay under the y {limit} limit.':
            'Costruzioni fino a y {top} (isole fluttuanti, torri): scendono intere, con il terreno sotto, per restare sotto il limite y {limit}.',
        'Writing the final files':
            'Scrittura dei file finali',
        'Blending: the chunks are written in the {format} format (pre-Caves & Cliffs); opening the world in {version}, Minecraft blends terrain and biomes with the new terrain and generates the part below y=0.':
            'Blending: i chunk vengono scritti in formato {format} (pre-Caves & Cliffs); aprendo il mondo in {version} Minecraft fonde terreno e biomi con il terreno nuovo e genera la parte sotto y=0.',
        'Translating to {target} (Amulet)':
            'Traduzione in {target} (Amulet)',
        'Finishing (level.dat, modern blocks, entities)':
            'Rifinitura (level.dat, blocchi moderni, entità)',
        '{n} Update Aquatic blocks (LCE) were replaced with 1.12 equivalents: choose a specific (pre-converted) Java version to keep them identical.':
            "{n} blocchi dell'Update Aquatic (LCE) sono stati sostituiti con equivalenti 1.12: scegli una versione Java specifica (pre-convertita) per mantenerli identici.",
        'World trim: reading the time spent in the chunks (InhabitedTime)':
            'World trim: lettura del tempo passato nei chunk (InhabitedTime)',
        'World trim not available: {error}':
            'World trim non disponibile: {error}',
        "A Better than Adventure world converts only to Minecraft Java 26.3 (BTA's blocks become blocks of the latest Java version).":
            "Da un mondo Better than Adventure si converte solo verso Minecraft Java 26.3 (i blocchi di BTA diventano blocchi dell'ultima versione Java).",
        'Better than Adventure converts only to the latest Java version (26.3): choose “latest – best route automatically”.':
            "Da Better than Adventure si converte solo verso l'ultima versione Java (26.3): scegli «ultima – percorso migliore automatico».",
        'Target: Java Edition {version} (1.18.2 format upgraded by Minecraft when opened)  ({path})':
            "Destinazione: Java Edition {version} (formato 1.18.2 aggiornato da Minecraft all'apertura)  ({path})",
        'Converting Better than Adventure → Java 26.3':
            'Conversione Better than Adventure → Java 26.3',
        'Open the world with Minecraft Java 26.3: on first start the game upgrades it (it may ask for a backup) and blends the new terrain with the converted chunks.':
            'Apri il mondo con Minecraft Java 26.3: al primo avvio il gioco lo aggiorna (può chiedere un backup) e raccorda il terreno nuovo ai chunk convertiti (blending).',
        'Blending: pre-1.18 source world, the chunks are written in the {format} format and Minecraft blends them with the new terrain when the world is opened.':
            "Blending: mondo di origine pre-1.18, i chunk vengono scritti in formato {format} e Minecraft li fonde col terreno nuovo all'apertura.",
        'Converting with Amulet to {target}':
            'Conversione con Amulet in {target}',
        'Finishing (level.dat, entities, containers)':
            'Rifinitura (level.dat, entità, contenitori)',
        'Underground: kept from y {bottom}, the world rises by {dy} blocks.':
            'Sottosuolo: tenuto da y {bottom}, il mondo sale di {dy} blocchi.',
        '{n} players were in the regenerated dimension: they go back to the Overworld spawn.':
            "{n} giocatori erano nella dimensione rigenerata: tornano allo spawn dell'Overworld.",
        'Nether ring':
            'Raccordo del Nether',
        'End ring':
            "Raccordo dell'End",
        'rock, lava and caverns':
            'rocce, lava e caverne',
        'end stone islands':
            'isole di end stone',
        'surfaces and biomes, caves and decoration are added by the game':
            'superfici e biomi, grotte e decorazioni li aggiunge il gioco',
        'glowstone, fire, lava springs and fortresses are added by the game':
            'pietra luminosa, fuoco, sorgenti di lava e fortezze li aggiunge il gioco',
        'the decoration (chorus plants, End cities) is added by the game':
            "le decorazioni (piante di chorus, città dell'End) le aggiunge il gioco",
        "{ring}: {n} chunks of the game's terrain (seed {seed}) around the converted world, {width} chunks wide: {what} pass smoothly from those of the converted edge to the game's; {rest}.":
            '{ring}: {n} chunk di terreno del gioco (seed {seed}) intorno al mondo convertito, larghi {width} chunk: {what} passano dolcemente da quelle del bordo convertito a quelle del gioco; {rest}.',
        'Edge of the converted world (reading)':
            'Bordo del mondo convertito (lettura)',
        'Translating the terrain around the world (Amulet)':
            'Traduzione del terreno intorno al mondo (Amulet)',
        "Ring: {n} chunks of the game's terrain (seed {seed}) around the converted world, raised or lowered smoothly to meet its edge, 3 to {width} chunks wide depending on the height difference; caves, trees, ores and lakes are added by the game.":
            'Raccordo: {n} chunk di terreno del gioco (seed {seed}) intorno al mondo convertito, alzato o abbassato dolcemente fino al suo bordo, larghi da 3 a {width} chunk secondo il dislivello; grotte, alberi, minerali e laghi li aggiunge il gioco.',
        '{target}: only the main player ({player}) is transferred; the other selected players are ignored.':
            '{target}: viene trasferito solo il giocatore principale ({player}); gli altri giocatori selezionati sono ignorati.',
        '{n} players were not written: a Java world keeps one player in level.dat and a file for each player linked to a Java account (--player KEY=NICKNAME, “Players” tab).':
            "{n} giocatori non sono stati scritti: un mondo Java tiene un giocatore in level.dat e un file per ogni giocatore collegato a un account Java (--player CHIAVE=NICKNAME, scheda «Giocatori»).",
        'Left out of Pocket Edition 0.8: {names}':
            'Lasciato fuori da Pocket Edition 0.8: {names}',
        'Selection: {n} unselected chunks removed.':
            'Selezione: {n} chunk non selezionati rimossi.',
        'Unknown LCE platform: {platform} (choose from {choices})':
            'Piattaforma LCE sconosciuta: {platform} (scegli tra {choices})',
        '{size} chunks is not a world size {platform} has: use {choices}':
            '{size} chunk non è una dimensione del mondo disponibile per {platform}: usa {choices}',
        '{profile} is not a console version {platform} has: use {choices}':
            '{profile} non è una versione delle console disponibile per {platform}: usa {choices}',
        'The output path is a file, not a folder: {path}':
            'Il percorso di destinazione è un file, non una cartella: {path}',
        'The output folder cannot be inside the source world: {path}':
            'La cartella di destinazione non può trovarsi dentro al mondo di origine: {path}',
        'The source world cannot be inside the output folder: {path}':
            'Il mondo di origine non può trovarsi dentro alla cartella di destinazione: {path}',
    },
    'worldbridge/terrain/policy.py': {
        "No terrain border yet for {target}: where the converted world ends the game will put its own terrain with a step. For an edge without steps choose Java 1.18 or later (the game's blending) or Java Alpha 1.2 – 1.12 (WorldBridge's ring).":
            'Raccordo col terreno non ancora disponibile per {target}: dove finisce il mondo convertito il gioco metterà il suo terreno con un gradino. Per un bordo senza gradini scegli Java 1.18 o successiva (raccordo del gioco) oppure Java Alpha 1.2 – 1.12 (anello di WorldBridge).',
        'Ring turned off: at the edges of the converted world the game will put its own terrain without a transition.':
            'Anello di raccordo disattivato: ai bordi del mondo convertito il gioco metterà il suo terreno senza raccordo.',
        'Game blending turned off: the chunks are written in the new format, so the game does not blend them with the new terrain nor generate the part below y 0.':
            'Blending del gioco disattivato: i chunk sono scritti nel formato nuovo, quindi il gioco non li fonde col terreno nuovo e non genera la parte sotto y 0.',
        'LCE → LCE: the game generates the same terrain as the source world, the edge continues by itself.':
            'LCE → LCE: il gioco genera lo stesso terreno del mondo di origine, il bordo continua da solo.',
        'Pocket Edition 0.x: the world is small (256×256 blocks) and is written whole, with natural terrain meeting the converted world around it: no steps.':
            'Pocket Edition 0.x: il mondo è piccolo (256×256 blocchi) e viene scritto per intero, con terreno naturale raccordato intorno al mondo convertito: nessun gradino.',
        "neoLegacy: around the converted world WorldBridge writes a ring with neoLegacy's generator (same seed, same biomes and terrain as the game) meeting the converted terrain: past the ring the game continues without steps.":
            "neoLegacy: intorno al mondo convertito WorldBridge scrive un anello col generatore di neoLegacy (stesso seed, stessi biomi e terreno del gioco) raccordato al terreno convertito: oltre l'anello il gioco continua senza gradini.",
        'LCE: the map is small ({size}×{size} chunks) and is written whole, with natural terrain meeting the converted world around it: no steps.':
            'LCE: la mappa è piccola ({size}×{size} chunk) e viene scritta per intero, con terreno naturale raccordato intorno al mondo convertito: nessun gradino.',
        'LCE: on large maps a border with the terrain the console generates is not available yet for this version (it is for neoLegacy: Windows64, TU31): a step will remain where the converted world ends. With a 54- or 64-chunk map the world is written whole, without steps.':
            "LCE: per le mappe grandi il raccordo col terreno generato dalla console non è ancora disponibile per questa versione (c'è per neoLegacy: Windows64, TU31): dove finisce il mondo convertito resterà un gradino. Con una mappa da 54 o 64 chunk il mondo viene scritto per intero, senza gradini.",
        'Bedrock blends the new terrain with the converted one by itself.':
            'Bedrock raccorda da solo il terreno nuovo con quello convertito.',
        'Bedrock 1.18+ generates the same terrain as Java 1.18+: the edge continues by itself.':
            'Bedrock 1.18+ genera lo stesso terreno di Java 1.18+: il bordo continua da solo.',
        'Bedrock before 1.18 does not blend terrain and its generator cannot be reproduced: a step will remain where the converted world ends. For an edge without steps choose Bedrock 1.18 or later.':
            'Bedrock prima della 1.18 non raccorda il terreno e il suo generatore non è riproducibile: dove finisce il mondo convertito resterà un gradino. Per un bordo senza gradini scegli Bedrock 1.18 o successiva.',
        'Minecraft blends the new terrain with the converted one by itself.':
            'Minecraft raccorda da solo il terreno nuovo con quello convertito (blending).',
        'Java 1.18+ generates the terrain with the same generator: the edge continues by itself.':
            'Java 1.18+ genera il terreno con lo stesso generatore: il bordo continua da solo.',
    },
    'worldbridge/trim.py': {
        'InhabitedTime < {time} → removed · protective ring {ring} chunks · spawn ±{spawn} chunks':
            'InhabitedTime < {time} → rimosso · anello di protezione {ring} chunk · spawn ±{spawn} chunk',
        'invalid duration: {text} (e.g. 1m, 30s, 2h or a number of ticks)':
            'durata non valida: {text} (es. 1m, 30s, 2h o un numero di tick)',
        'World format not recognised.':
            'Formato del mondo non riconosciuto.',
        'Bedrock Edition does not record the time spent in chunks (InhabitedTime).':
            'Bedrock Edition non registra il tempo passato nei chunk (InhabitedTime).',
        'Pocket Edition 0.x does not record the time spent in chunks.':
            'Pocket Edition 0.x non registra il tempo passato nei chunk.',
        'Better than Adventure (based on Beta 1.7.3) does not record the time spent in chunks.':
            'Better than Adventure (base Beta 1.7.3) non registra il tempo passato nei chunk.',
        'Indev worlds are not divided into chunks.':
            'I mondi Indev non sono divisi in chunk.',
        'Classic worlds are not divided into chunks.':
            'I mondi Classic non sono divisi in chunk.',
        'Extract the archive first: the trim works on a folder.':
            "Estrai prima l'archivio: il trim lavora su una cartella.",
        'InhabitedTime exists since Java 1.6.1: Alpha / Beta / McRegion worlds do not record it.':
            'InhabitedTime esiste da Java 1.6.1: i mondi Alpha / Beta / McRegion non lo registrano.',
        'Trim not available for {world}.':
            'Trim non disponibile per {world}.',
        'This world does not record the time spent in chunks (InhabitedTime always 0): the trim would delete everything.':
            'Questo mondo non registra il tempo passato nei chunk (InhabitedTime sempre 0): il trim cancellerebbe tutto.',
        'Reading InhabitedTime: region {i}/{n}':
            'Lettura InhabitedTime: regione {i}/{n}',
        'Reading InhabitedTime: chunk {i}/{n}':
            'Lettura InhabitedTime: chunk {i}/{n}',
        'The output folder is not empty: {path}':
            'La cartella di destinazione non è vuota: {path}',
        'Copying the world':
            'Copia del mondo',
        'Removing the unused chunks':
            'Rimozione dei chunk inutilizzati',
        'Completed':
            'Completato',
        'kept {kept} of {total} chunks · removed {removed} ({pct}%)':
            'tenuti {kept} chunk su {total} · rimossi {removed} ({pct}%)',
    },
    'worldbridge/lce/world.py': {
        'TU31 – 1.8 blocks (neoLegacy on PC, Bountiful consoles)':
            'TU31 – blocchi 1.8 (neoLegacy su PC, console Bountiful)',
        'TU46 – 1.9 blocks (Elytra Update)':
            'TU46 – blocchi 1.9 (Elytra Update)',
        'TU54+ – 1.12 blocks (World of Color)':
            'TU54+ – blocchi 1.12 (World of Color)',
        '{file} cannot be read: the entities of this dimension are lost ({error}).':
            '{file} non è leggibile: le entità di questa dimensione vanno perse ({error}).',
        '“{name}” is not a Wii U player id: the game loads the player from players/<32 hexadecimal digits>.dat, so it will start at the spawn with an empty inventory. Give the id (the name of your file in players/ of a world already played, or use “From my world…” in the GUI).':
            "«{name}» non è un id giocatore Wii U: il gioco carica il giocatore da players/<32 cifre esadecimali>.dat, quindi partirà dallo spawn con l'inventario vuoto. Indica l'id (il nome del tuo file in players/ di un mondo già giocato, o usa «Dal mio mondo…» nella GUI).",
        'No player id given: the host player is written as players/{file}.dat, a file {platform} does not load, so the player will start at the spawn with an empty inventory. Give your id with --player-id (the name of your file in players/ of a world already played on that console, or use “From my world…” in the GUI).':
            "Nessun id giocatore indicato: il giocatore host è scritto come players/{file}.dat, un file che {platform} non carica, quindi il giocatore partirà dallo spawn con l'inventario vuoto. Indica il tuo id con --player-id (il nome del tuo file in players/ di un mondo già giocato su quella console, o usa «Dal mio mondo…» nella GUI).",
        '“{name}” is not an XUID: the game loads the player from players/<number>.dat, so it will start at the spawn with an empty inventory. Give the number (the name of your file in players/ of a world already played, or use “From my world…” in the GUI).':
            "«{name}» non è un XUID: il gioco carica il giocatore da players/<numero>.dat, quindi partirà dallo spawn con l'inventario vuoto. Indica il numero (il nome del tuo file in players/ di un mondo già giocato, o usa «Dal mio mondo…» nella GUI).",
        '{n} blocks that do not exist in {version} were replaced with equivalents.':
            '{n} blocchi non esistenti in {version} sono stati sostituiti con equivalenti.',
        '{n} items':
            '{n} oggetti',
        '{n} enchantments':
            '{n} incantesimi',
        'the entities {names}':
            'le entità {names}',
        ' and ':
            ' e ',
        '{version} does not have {what} of the source world: removed (the game does not know them); new arrows, boats and potions become their classic versions.':
            '{version} non ha {what} del mondo di origine: tolti (il gioco non li conosce); frecce, barche e pozioni nuove diventano le loro versioni classiche.',
        "{n} chunks outside the LCE world's limits ({dim}, {size}×{size} chunks) were left out.":
            '{n} chunk fuori dai limiti del mondo LCE ({dim}, {size}×{size} chunk) sono stati esclusi.',
        'Overworld':
            'Overworld',
        'Nether':
            'Nether',
        'End':
            'End',
    },
    'worldbridge/lce/compat.py': {
    },
    'worldbridge/chunkedit.py': {
        '{n} chunks deleted':
            '{n} chunk cancellati',
        '{n} chunks with the new biome':
            '{n} chunk col nuovo bioma',
        '{n} chunks left as they were (their format does not have that biome)':
            "{n} chunk lasciati com'erano (il loro formato non ha quel bioma)",
        'no chunk changed':
            'nessun chunk cambiato',
        '. Backup of the changed files: {path}':
            '. Copia di sicurezza dei file cambiati: {path}',
        'World format not recognised.':
            'Formato del mondo non riconosciuto.',
        'Alpha worlds (one file per chunk) cannot be edited here: convert them first.':
            'I mondi Alpha (un file per chunk) non si modificano qui: convertili prima.',
        'Chunk editing not available for {world}.':
            'Modifica dei chunk non disponibile per {world}.',
        'The biome {biome} does not exist in Legacy Console Edition.':
            'Il bioma {biome} non esiste nella Legacy Console Edition.',
        'Save inside an STFS package (Xbox 360): extract it before editing it.':
            'Salvataggio dentro un pacchetto STFS (Xbox 360): estrailo prima di modificarlo.',
    },
    'worldbridge/_bootstrap.py': {
        'Python {version} has no prebuilt packages for every dependency':
            'Python {version} non ha pacchetti precompilati per tutte le dipendenze',
        'Missing dependencies ({names}): installing them in {path} …':
            'Dipendenze mancanti ({names}): le installo in {path} …',
        'installation with pip failed ({error})':
            'installazione con pip non riuscita ({error})',
        'Dependencies still missing: {names}':
            'Dipendenze ancora mancanti: {names}',
        'Cannot install the dependencies: {reason}.':
            'Impossibile installare le dipendenze: {reason}.',
        '{reason}: using ./run.sh (portable Python in the .runtime folder).':
            '{reason}: uso ./run.sh (Python portatile nella cartella .runtime).',
    },
    'worldbridge/amulet_bridge.py': {
        'Terrain heights {i}/{n}':
            'Altezze del terreno {i}/{n}',
        'Translating blocks (Amulet) {i}/{n}':
            'Traduzione blocchi (Amulet) {i}/{n}',
        'Terrain heights':
            'Altezze del terreno',
        'Translating blocks (Amulet)':
            'Traduzione blocchi (Amulet)',
        'Aquatic blocks {i}/{n}':
            'Blocchi Aquatic {i}/{n}',
    },
    'worldbridge/mapview.py': {
        'Main player':
            'Giocatore principale',
        'World format not recognised.':
            'Formato del mondo non riconosciuto.',
        'The archive does not contain a recognised world.':
            "L'archivio non contiene un mondo riconosciuto.",
        'Copying files {done}/{total}':
            'Copia dei file {done}/{total}',
    },
    'worldbridge/java/numeric.py': {
        'Java chunk {cx},{cz} unreadable, skipped: {error}':
            'Chunk Java {cx},{cz} illeggibile, saltato: {error}',
        'Players: {n} playerdata files written.':
            'Giocatori: {n} file playerdata scritti.',
        '{n} blocks that do not exist in the target version were replaced.':
            '{n} blocchi non esistenti nella versione di destinazione sono stati sostituiti.',
        'Content that does not exist in {version}: removed {items} items, {entities} entities and {tiles} block entities.':
            'Contenuti non esistenti in {version}: rimossi {items} oggetti, {entities} entità e {tiles} blocchi-entità.',
        '{n} entities were renamed to the identifiers of {version} (villagers, trader llamas).':
            '{n} entità rinominate con gli identificatori di {version} (abitanti, lama mercante).',
    },
    'worldbridge/bedrock/extra.py': {
        'Height maps not recomputed: {error}':
            'Mappe delle altezze non ricalcolate: {error}',
        '{n} frames':
            '{n} cornici',
        '{n} maps':
            '{n} mappe',
        '{n} item frames could not be placed in Bedrock {version} (on a floor or ceiling before 1.13, or where the block is not air): they are not in the converted world.':
            '{n} cornici non si sono potute collocare in Bedrock {version} (a pavimento o soffitto prima della 1.13, o dove il blocco non è aria): non sono nel mondo convertito.',
        'Bedrock: {tiles} block entities and {entities} entities written{extra}.':
            'Bedrock: {tiles} blocchi-entità e {entities} entità scritti{extra}.',
        'Entities and containers {i}/{n}':
            'Entità e contenitori {i}/{n}',
        'Bedrock: {n} records copied (entities, block entities, players, maps…).':
            'Bedrock: copiati {n} record (entità, blocchi-entità, giocatori, mappe…).',
    },
    'worldbridge/bedrock/pe_old.py': {
        'Pocket Edition 0.8: the player keeps position and health, but not the inventory.':
            "Pocket Edition 0.8: il giocatore mantiene posizione e salute, ma non l'inventario.",
        '{n} blocks missing in Pocket Edition 0.8 were replaced.':
            '{n} blocchi non presenti in Pocket Edition 0.8 sono stati sostituiti.',
        '{n} chunks outside the 256×256 area of Pocket Edition 0.8 were left out (Overworld only, chunks 0..15).':
            "{n} chunk fuori dall'area 256×256 di Pocket Edition 0.8 sono stati esclusi (solo l'Overworld, chunk 0..15).",
    },
    'worldbridge/extra.py': {
        'Entities / containers not transferred: {error}':
            'Entità / contenitori non trasferiti: {error}',
        'Entities / containers not fully transferred: {error}':
            'Entità / contenitori non trasferiti completamente: {error}',
    },
    'worldbridge/relocate.py': {
        'Selected chunks moved: their centre goes to x {x}, z {z} ({dx}, {dz} blocks).':
            'Chunk selezionati spostati: il loro centro va a x {x}, z {z} ({dx}, {dz} blocchi).',
        'Spawn: {x}, {y}, {z}.':
            'Spawn: {x}, {y}, {z}.',
        '{n} players were outside the moved chunks: they start at the new spawn.':
            '{n} giocatori erano fuori dai chunk spostati: partono dal nuovo spawn.',
    },
    'worldbridge/selection.py': {
        'Premium UUID of “{name}” not found (offline?): using the offline UUID.':
            "UUID premium di «{name}» non trovato (offline?): uso l'UUID offline.",
        'Player “{key}” → {name} ({uuid})':
            'Giocatore «{key}» → {name} ({uuid})',
        'Players: {n} playerdata files written.':
            'Giocatori: {n} file playerdata scritti.',
    },
    'worldbridge/terrain/ring.py': {
        "Height differences at the world's edge":
            'Dislivelli al bordo del mondo',
        "Joining the terrain to the world's edge":
            'Raccordo del terreno col bordo del mondo',
        'Terrain around the world {i}/{n}':
            'Terreno intorno al mondo {i}/{n}',
    },
    'worldbridge/detect.py': {
        'World archive (.mcworld / .zip)':
            'Archivio mondo (.mcworld / .zip)',
        'Better than Adventure (Beta 1.7.3 mod, BTA 8.0.1)':
            'Better than Adventure (mod di Beta 1.7.3, BTA 8.0.1)',
        '{file} is a Git LFS pointer (a small text file standing for the real one): fetch the real files with “git lfs pull” or download the world as an archive.':
            '{file} è un puntatore Git LFS (un piccolo file di testo al posto di quello vero): scarica i file veri con «git lfs pull» oppure scarica il mondo come archivio.',
        'level.dat is not a valid NBT file: the world is damaged or incomplete ({error}).':
            'level.dat non è un file NBT valido: il mondo è danneggiato o incompleto ({error}).',
        'New Nintendo 3DS Edition worlds are not supported: their chunks are not kept in a LevelDB database (db/cdb, db/vdb) like those of the other Bedrock worlds.':
            'I mondi di New Nintendo 3DS Edition non sono supportati: i loro chunk non stanno in un database LevelDB (db/cdb, db/vdb) come quelli degli altri mondi Bedrock.',
        'The db folder of this Bedrock world holds no LevelDB database (CURRENT is missing): the world is incomplete.':
            'La cartella db di questo mondo Bedrock non contiene un database LevelDB (manca CURRENT): il mondo è incompleto.',
        'The level.dat of this Bedrock world is not valid: the world is damaged or incomplete.':
            'Il level.dat di questo mondo Bedrock non è valido: il mondo è danneggiato o incompleto.',
        'This Bedrock world has no terrain: the db folder with its chunks is missing (only level.dat and the add-ons were saved, the game generates the terrain when the world is first opened), so there is nothing to convert. Open it once in Minecraft and convert the saved world.':
            "Questo mondo Bedrock non ha terreno: manca la cartella db con i suoi chunk (sono stati salvati solo level.dat e gli add-on, il gioco genera il terreno alla prima apertura del mondo), quindi non c'è niente da convertire. Aprilo una volta in Minecraft e converti il mondo salvato.",
    },
    'worldbridge/bta/world.py': {
        'No level.dat in {path}':
            'Nessun level.dat in {path}',
        'unreadable chunk data':
            'dati del chunk illeggibili',
    },
    'worldbridge/terrain/ring3d.py': {
        'Nether terrain {i}/{n}':
            'Terreno del Nether {i}/{n}',
        'End terrain {i}/{n}':
            "Terreno dell'End {i}/{n}",
        'Nether ring {i}/{n}':
            'Raccordo del Nether {i}/{n}',
        'End ring {i}/{n}':
            "Raccordo dell'End {i}/{n}",
    },
    'worldbridge/java/modern.py': {
        'Java: {tiles} block entities and {entities} entities written.':
            'Java: {tiles} blocchi-entità e {entities} entità scritti.',
    },
    'worldbridge/bedrock/terrain.py': {
        'Height maps {i}':
            'Mappe delle altezze {i}',
    },
    'worldbridge/biomes.py': {
        'unknown biome: {name}':
            'bioma sconosciuto: {name}',
    },
    'worldbridge/bta/convert.py': {
        'block {id}:{meta} ({name}): {error}':
            'blocco {id}:{meta} ({name}): {error}',
        'item {id}: {name} does not exist in 26.3':
            'oggetto {id}: {name} non esiste in 26.3',
        'Unreadable palette file: {error}':
            'File della palette illeggibile: {error}',
        'The palette gives blocks that are not valid in 26.3: {errors}':
            'La palette produce blocchi non validi in 26.3: {errors}',
        'BTA world “{name}” (save version {version})':
            'Mondo BTA «{name}» (versione salvataggio {version})',
        'The world was last saved with an old BTA version ({version}): for the best result open it and save it once in BTA 8.0.1 before converting it.':
            "Il mondo è stato salvato l'ultima volta con una versione vecchia di BTA ({version}): per il risultato migliore aprilo e salvalo una volta in BTA 8.0.1 prima di convertirlo.",
        'The vertical shift (--y-offset) must be between 0 and 128.':
            'Lo spostamento verticale (--y-offset) deve essere tra 0 e 128.',
        'Overworld of type “{type}” (sea at y {sea}): lowered by {shift} blocks, so the sea matches the vanilla one (y 63)':
            'Overworld di tipo «{type}» (mare a y {sea}): abbassato di {shift} blocchi, così il mare coincide con quello vanilla (y 63)',
        'unknown':
            'sconosciuto',
        'Regions {i}/{n}':
            'Regioni {i}/{n}',
        'Regions {i}/{n} · {chunks} chunks':
            'Regioni {i}/{n} · {chunks} chunk',
        'No chunks to convert (empty selection or a world without regions).':
            'Nessun chunk da convertire (selezione vuota o mondo senza regioni).',
        '{dim}: {n} chunks':
            '{dim}: {n} chunk',
        '(becomes The End)':
            '(diventa The End)',
        'Players: {n} playerdata files written.':
            'Giocatori: {n} file playerdata scritti.',
        '{n} unreadable BTA chunks were not converted.':
            '{n} chunk BTA illeggibili non sono stati convertiti.',
        '{n} unknown block types (ids not of BTA 8.0.1) became air.':
            '{n} tipi di blocco sconosciuti (id non di BTA 8.0.1) sono diventati aria.',
        '{n} items without an equivalent slot were left on the ground (they do not despawn).':
            '{n} oggetti senza uno slot equivalente sono stati lasciati a terra (non spariscono).',
        '{n} entities without a vanilla equivalent (projectiles, fireflies, butterflies…) not converted.':
            '{n} entità senza equivalente vanilla (proiettili, lucciole, farfalle…) non convertite.',
        '{n} statues became armour stands.':
            '{n} statue diventate armor stand.',
    },
    'worldbridge/manage.py': {
        'Health':
            'Salute',
        'Hunger':
            'Fame',
        'Experience level':
            'Livello di esperienza',
        'Score':
            'Punteggio',
        'Game mode':
            'Modalità di gioco',
        'Same as the world':
            'Come il mondo',
        'Spectator':
            'Spettatore',
        'Dimension':
            'Dimensione',
        'This world is read-only.':
            'Questo mondo si può solo leggere.',
        'Java Edition (up to 1.8)':
            'Java Edition (fino alla 1.8)',
        'World (level.dat)':
            'Mondo (level.dat)',
        'Generation (seed)':
            'Generazione (seed)',
        'Game rules':
            'Regole di gioco',
        'Weather':
            'Meteo',
        'Clocks':
            'Orologi',
        'Name':
            'Nome',
        'Difficulty':
            'Difficoltà',
        'Peaceful':
            'Pacifica',
        'Easy':
            'Facile',
        'Normal':
            'Normale',
        'Hard':
            'Difficile',
        'Commands (cheats)':
            'Comandi (trucchi)',
        'Rain':
            'Pioggia',
        'Thunderstorm':
            'Temporale',
        'Time of day (ticks)':
            'Ora del giorno (tick)',
        'Rain level':
            'Livello della pioggia',
        'Lightning level':
            'Livello dei fulmini',
        'Local player':
            'Giocatore locale',
        'Single player (in level.dat)':
            'Giocatore in singolo (in level.dat)',
        'Single player ({name})':
            'Giocatore in singolo ({name})',
        'The players cannot be read ({error}): close Minecraft if the world is open in it.':
            'Impossibile leggere i giocatori ({error}): chiudi Minecraft se il mondo è aperto lì.',
        '{player}: unreadable ({error})':
            '{player}: illeggibile ({error})',
        'Hotbar':
            'Barra rapida',
        'Armour':
            'Armatura',
        'Off hand':
            'Mano secondaria',
        'Ender chest':
            'Baule di ender',
        'Unknown item: {name}':
            'Oggetto sconosciuto: {name}',
        'Survival':
            'Sopravvivenza',
        'Creative':
            'Creativa',
        'Adventure':
            'Avventura',
        'Position {axis}':
            'Posizione {axis}',
        '(format {version})':
            '(formato {version})',
        'Player {name}':
            'Giocatore {name}',
        'Rule: {name}':
            'Regola: {name}',
        'This kind of world has no editable documents: {world}':
            'Questo tipo di mondo non ha documenti modificabili: {world}',
    },
    'worldbridge/gui/players.py': {
        "Java: the nickname decides the player's <i>playerdata/&lt;UUID&gt;.dat</i> file. With “Premium” the UUID is looked up online on Mojang's servers (original account); without it, the offline UUID is used (non-premium servers / LAN). The main player is the one who finds the inventory when the world is opened in single player.":
            "Java: il nickname decide il file <i>playerdata/&lt;UUID&gt;.dat</i> del giocatore. Con «Premium» l'UUID viene cercato online sui server Mojang (account originale); senza, viene usato l'UUID offline (server non premium / LAN). Il giocatore principale è quello che si ritrova l'inventario aprendo il mondo in giocatore singolo.",
        "Bedrock: only the main player (the world's local player) is transferred; no nickname is needed.":
            'Bedrock: viene trasferito solo il giocatore principale (il giocatore locale del mondo); il nickname non serve.',
        "Legacy Console Edition: this takes the <b>XUID</b>, not the nickname: the number that names the player's file in <i>players/</i> (on PC neoLegacy gives it to your installation: take it from one of your worlds with “From my world…” in the Conversion tab). With a nickname the game does not find the player, who starts again at the spawn without an inventory.":
            "Legacy Console Edition: qui non va il nickname ma l'<b>XUID</b>, il numero che fa da nome al file del giocatore in <i>players/</i> (su PC neoLegacy lo dà il gioco alla tua installazione: prendilo da un tuo mondo con «Dal mio mondo…» nella scheda Conversione). Con un nickname il gioco non trova il giocatore, che riparte dallo spawn senza inventario.",
        'Pocket Edition 0.x: only the main player is transferred.':
            'Pocket Edition 0.x: viene trasferito solo il giocatore principale.',
        'Choose the players to transfer and link them to a nickname':
            'Scegli i giocatori da trasferire e collegali a un nickname',
        "When off, the world's main player is transferred as usual":
            'Se non attivo, il giocatore principale del mondo viene trasferito come sempre',
        'Transfer':
            'Trasferisci',
        'Main':
            'Principale',
        'Player in the source world':
            'Giocatore nel mondo di origine',
        'Position':
            'Posizione',
        'Target nickname':
            'Nickname di destinazione',
        'Premium':
            'Premium',
        'No players found in the source world: open a world at the top.':
            'Nessun giocatore trovato nel mondo di origine: apri un mondo in alto.',
        'Double-click a player to see them on the map.':
            'Doppio clic su un giocatore per vederlo sulla mappa.',
        'nickname (optional)':
            'nickname (facoltativo)',
        '{n} items':
            '{n} oggetti',
        'Offline UUID: {uuid}':
            'UUID offline: {uuid}',
        'No players in the source world':
            'Nessun giocatore nel mondo di origine',
        'The main player, as in the source world':
            'Il giocatore principale, come nel mondo di origine',
        '{n} of {total} transferred · main: {main}':
            '{n} di {total} trasferiti · principale: {main}',
    },
    'worldbridge/gui/trimui.py': {
        'seconds':
            'secondi',
        'minutes':
            'minuti',
        'hours':
            'ore',
        'World trim settings':
            'Impostazioni del world trim',
        'less than':
            'meno di',
        'Remove chunks used':
            'Rimuovi i chunk usati',
        'chunks':
            'chunk',
        'Also keeps the chunks around every used chunk: it avoids trees and builds cut in half at the edge (the known problem of trims).':
            'Tiene anche i chunk attorno a ogni chunk usato: evita alberi e costruzioni tagliati a metà sul bordo (il problema noto dei trim).',
        'Protective ring':
            'Anello di protezione',
        'radius':
            'raggio',
        'Protect the spawn':
            'Proteggi lo spawn',
        'chunks loaded with /forceload':
            'chunk caricati con /forceload',
        'Always keep':
            'Tieni sempre',
        'chunks with unreadable InhabitedTime':
            'chunk con InhabitedTime illeggibile',
        'colour the chunks by time spent':
            'colora i chunk per tempo di permanenza',
        'Red: below the threshold (would be removed) · yellow → green: more and more used · grey: no data':
            'Rosso: sotto la soglia (verrebbe rimosso) · giallo → verde: sempre più usato · grigio: dato non disponibile',
        'Map':
            'Mappa',
        "Values recommended by the community: MCA Selector's guides suggest <i>InhabitedTime &lt; 1 minute</i> (beyond that it becomes destructive for little extra space); Aternos' Thanos never touches force-loaded chunks nor those without data. The original world is never modified.":
            'Valori consigliati dalla comunità: le guide di MCA Selector suggeriscono <i>InhabitedTime &lt; 1 minuto</i> (oltre diventa distruttivo per poco spazio in più); Thanos di Aternos non tocca mai i chunk forzati né quelli senza dato. Il mondo originale non viene mai modificato.',
        'Restore the recommended values':
            'Ripristina i valori consigliati',
        'cancelled':
            'annullato',
    },
    'worldbridge/gui/mapwidget.py': {
        'Cancel':
            'Annulla',
        'Stops the operation running on the world':
            "Ferma l'operazione in corso sul mondo",
        'The world is being edited: wait for the edit to finish.':
            'Il mondo è in modifica: aspetta che la modifica finisca.',
        'Another operation on the world is running: wait for it to finish.':
            "Un'altra operazione sul mondo è in corso: aspetta che finisca.",
        'Operation cancelled.':
            'Operazione annullata.',
        'Import not possible yet: the map of this dimension is still loading.':
            'Importazione non ancora possibile: la mappa di questa dimensione è ancora in caricamento.',
        '{n} chunks selected from the file':
            '{n} chunk selezionati dal file',
        '{n} left out (they do not exist in this world)':
            '{n} esclusi (non esistono in questo mondo)',
        'In the converted world the selected chunks do not stay at their coordinates: the centre of the selection goes to the centre of the world (0, 0) or to the chosen coordinates. Useful for finite worlds (LCE, Pocket Edition) or to bring a build near the spawn.':
            'Nel mondo convertito i chunk selezionati non restano alle loro coordinate: il centro della selezione va al centro del mondo (0, 0) o alle coordinate scelte. Utile per i mondi finiti (LCE, Pocket Edition) o per portare una costruzione vicino allo spawn.',
        "A regenerated dimension is not converted: the game generates it anew, with its generator and the world's seed, the first time you enter it; the players who were there go back to the spawn.\nIf you convert it instead, WorldBridge writes a ring of the game's terrain (Java Alpha 1.2 – 1.17) around the converted part that joins it smoothly.":
            'Una dimensione rigenerata non viene convertita: il gioco la genera da capo, col suo generatore e il seed del mondo, la prima volta che ci entri; i giocatori che erano lì tornano allo spawn.\nSe invece la converti, intorno alla parte convertita WorldBridge scrive un anello di terreno del gioco (Java Alpha 1.2 – 1.17) che si raccorda dolcemente.',
        "The biome the selected chunks will have in the converted world (colour of grass and water, weather, creatures): the list is the target game's and version's, with its names. Java Alpha / Beta and Pocket Edition 0.x do not store biomes: there they cannot be changed.":
            "Il bioma che i chunk selezionati avranno nel mondo convertito (colore dell'erba e dell'acqua, meteo, creature): l'elenco è quello del gioco e della versione di destinazione, con i suoi nomi. Java Alpha / Beta e Pocket Edition 0.x non memorizzano i biomi: lì non si possono cambiare.",
        'Main player':
            'Giocatore principale',
        'Choose a source world: the map is drawn here.':
            'Seleziona un mondo di origine: la mappa viene disegnata qui.',
        'X {x}  Z {z}   ·   chunk {cx}, {cz}   ·   region r.{rx}.{rz}':
            'X {x}  Z {z}   ·   chunk {cx}, {cz}   ·   regione r.{rx}.{rz}',
        'selected':
            'selezionato',
        'No world open.':
            'Nessun mondo aperto.',
        'Dimension:':
            'Dimensione:',
        'The dimension shown on the map':
            'La dimensione mostrata sulla mappa',
        'Pan':
            'Sposta',
        'Select':
            'Seleziona',
        'Spawn':
            'Spawn',
        'Drag to move the map (also with the middle button or holding Space)':
            'Trascina per spostare la mappa (anche col tasto centrale o tenendo premuto Spazio)',
        'Drag: select · Ctrl + drag or right button: deselect · Shift + click: whole region · click: one chunk':
            'Trascina: seleziona · Ctrl + trascina o tasto destro: deseleziona · Maiusc + clic: intera regione · clic: un chunk',
        'Click on the map: new spawn point':
            'Clic sulla mappa: nuovo punto di spawn',
        '{mode} mode':
            'Modalità {mode}',
        'Selection':
            'Selezione',
        'Select all':
            'Seleziona tutto',
        'Select every chunk of the dimension':
            'Seleziona tutti i chunk della dimensione',
        'Deselect all':
            'Deseleziona tutto',
        'Invert selection':
            'Inverti la selezione',
        'Invert the selection':
            'Inverte la selezione',
        'Import selection…':
            'Importa selezione…',
        'Load a selection (MCA Selector CSV)':
            'Carica una selezione (CSV di MCA Selector)',
        'Export selection…':
            'Esporta selezione…',
        'Save the selection (MCA Selector CSV)':
            'Salva la selezione (CSV di MCA Selector)',
        'Fit':
            'Adatta',
        'Show the whole world (Ctrl+0)':
            'Mostra tutto il mondo (Ctrl+0)',
        'World trim':
            'Trim del mondo',
        'Select only the chunks really used (InhabitedTime ≥ 1 minute, with a protective ring and the spawn): chunks never visited stay out of the conversion, or you save a trimmed copy of the world.':
            'Seleziona solo i chunk davvero usati (InhabitedTime ≥ 1 minuto, con un anello di protezione e lo spawn): i chunk mai visitati restano fuori dalla conversione, oppure salvi una copia ripulita del mondo.',
        'Trim settings':
            'Impostazioni del trim',
        'Trim settings (InhabitedTime threshold, protections, heat map)':
            'Impostazioni del trim (soglia di InhabitedTime, protezioni, mappa di calore)',
        'What to convert':
            'Cosa convertire',
        'The whole world':
            'Tutto il mondo',
        'Selected chunks only':
            'Solo i chunk selezionati',
        'Move the selected chunks':
            'Sposta i selezionati',
        'In the converted world the selected chunks do not stay at their coordinates':
            'Nel mondo convertito i chunk selezionati non restano alle loro coordinate',
        'To the world centre (0, 0)':
            'Al centro del mondo (0, 0)',
        'To the coordinates (blocks):':
            'Alle coordinate (blocchi):',
        'Target {axis} coordinate':
            'Coordinata {axis} di destinazione',
        'The centre of the selection goes there; spawn and players that were on the moved chunks follow them, the others start at the new spawn.':
            'Il centro della selezione va lì; spawn e giocatori che erano sui chunk spostati li seguono, gli altri partono dal nuovo spawn.',
        'New spawn in the converted world':
            'Nuovo spawn nel mondo convertito',
        'Use the point chosen with the “Spawn” mode (or typed here) as the spawn of the converted world':
            'Usa il punto scelto con la modalità «Spawn» (o scritto qui) come spawn del mondo convertito',
        'Restore the original':
            "Ripristina l'originale",
        'Restore the spawn of the source world':
            'Ripristina lo spawn del mondo di origine',
        'Or choose the “Spawn” mode and click on the map.':
            'Oppure scegli la modalità «Spawn» e fai clic sulla mappa.',
        'Nether and End':
            'Nether ed End',
        'Regenerate the Nether from scratch':
            'Rigenera il Nether da capo',
        'Regenerate the End from scratch':
            "Rigenera l'End da capo",
        'The dimension is not converted: the game generates it anew':
            'La dimensione non viene convertita: il gioco la genera da capo',
        'The other dimensions are converted.':
            'Le altre dimensioni vengono convertite.',
        'Biome of the selected chunks':
            'Bioma dei chunk selezionati',
        'Apply':
            'Applica',
        'Give the chosen biome to every selected chunk of the dimension shown':
            'Dà il bioma scelto a tutti i chunk selezionati della dimensione mostrata',
        'Remove':
            'Togli',
        'The selected chunks go back to their original biome':
            'I chunk selezionati tornano al loro bioma originale',
        'Edit the source world':
            'Modifica il mondo di origine',
        'Changes the open world right away, without converting. The changed files are copied first; close the game.':
            'Cambia subito il mondo aperto, senza convertire. Prima viene fatta una copia dei file cambiati; chiudi il gioco.',
        'Delete the selected chunks…':
            'Cancella i selezionati…',
        'Removes the selected chunks from the world: the game generates them again':
            'Toglie dal mondo i chunk selezionati: il gioco li rigenera',
        'Keep only the selected chunks…':
            'Tieni solo i selezionati…',
        'Removes every unselected chunk of the dimension shown from the world':
            'Toglie dal mondo tutti i chunk non selezionati della dimensione mostrata',
        '(the changed files are copied first).':
            '(prima viene fatta una copia dei file cambiati).',
        "The biomes of the source world's game and version":
            'I biomi del gioco e della versione del mondo di origine',
        'Give the biome to the selected chunks…':
            'Dai il bioma ai selezionati…',
        'The selected chunks of the source world take this biome right away (the changed files are copied first).':
            'I chunk selezionati del mondo di origine prendono subito questo bioma (prima viene fatta una copia dei file cambiati).',
        'selected chunks only ({n})':
            'solo i chunk selezionati ({n})',
        'moved to the centre':
            'spostati al centro',
        'moved to X {x}, Z {z}':
            'spostati a X {x}, Z {z}',
        'the whole world':
            'tutto il mondo',
        'new spawn {x}, {y}, {z}':
            'nuovo spawn {x}, {y}, {z}',
        '{n} chunks with a new biome':
            '{n} chunk con un bioma nuovo',
        'Nether and End regenerated from scratch':
            'Nether e End rigenerati da capo',
        '{dim} regenerated from scratch':
            '{dim} rigenerato da capo',
        'No world loaded.':
            'Nessun mondo caricato.',
        'Opening the world…':
            'Apertura del mondo…',
        'Map not available: {error}':
            'Mappa non disponibile: {error}',
        'Preview paused during the conversion':
            'Anteprima in pausa durante la conversione',
        '{dim}  ({n} chunks)':
            '{dim}  ({n} chunk)',
        '{dim}: {done}/{total} chunks':
            '{dim}: {done}/{total} chunk',
        'Import selection':
            'Importa selezione',
        'MCA Selector selection':
            'Selezione MCA Selector',
        'All files':
            'Tutti i file',
        'Import failed: {error}':
            'Importazione non riuscita: {error}',
        'Export selection':
            'Esporta selezione',
        'selection':
            'selezione',
        '(left out)':
            '(esclusa)',
        'Selected – {parts}':
            'Selezionati – {parts}',
        '{world} – the whole world will be converted':
            '{world} – verrà convertito tutto il mondo',
        'Reading the time spent in the chunks (InhabitedTime)…':
            'Lettura del tempo passato nei chunk (InhabitedTime)…',
        'Trim not available: {error}':
            'Trim non disponibile: {error}',
        'Trim not available for this world.':
            'Trim non disponibile per questo mondo.',
        'Trim: {summary}':
            'Trim: {summary}',
        'it would be regenerated entirely':
            'verrebbe rigenerata del tutto',
        '{dim}: {kept} of {total} kept':
            '{dim}: tenuti {kept} di {total}',
        'The kept chunks are highlighted on the map; with the trim settings (next to the button) you change threshold and protections and the selection updates at once.':
            'I chunk tenuti sono evidenziati sulla mappa; con le impostazioni del trim (accanto al tasto) cambi soglia e protezioni e la selezione si aggiorna subito.',
        'The conversion will use only the kept chunks.':
            'La conversione userà solo i chunk tenuti.',
        'You can also save a trimmed copy of the world right away, in the same format.':
            'Puoi anche salvare subito una copia ripulita del mondo, nello stesso formato.',
        'Use for the conversion':
            'Usa per la conversione',
        'Save trimmed world…':
            'Salva mondo ripulito…',
        'Apply to the world':
            'Applica al mondo',
        'Deletes the chunks not kept from the source world right away (the changed files are copied first)':
            'Cancella subito dal mondo di origine i chunk non tenuti (prima viene fatta una copia dei file cambiati)',
        'Undo trim':
            'Annulla trim',
        'Delete {n} unused chunks from the world?':
            'Cancellare dal mondo {n} chunk non usati?',
        'Where to save the trimmed world':
            'Dove salvare il mondo ripulito',
        'Trimmed world saved: {path}':
            'Mondo ripulito salvato: {path}',
        'Trimmed world saved in:\n{path}\n\n{n} chunks removed · {before} → {after}\n\nThe original world was not modified.':
            'Mondo ripulito salvato in:\n{path}\n\n{n} chunk rimossi · {before} → {after}\n\nIl mondo originale non è stato modificato.',
        'Saving the trimmed world failed: {error}':
            'Salvataggio del mondo ripulito non riuscito: {error}',
        'Saving failed:':
            'Salvataggio non riuscito:',
        'Select some chunks on the map first.':
            'Seleziona prima dei chunk sulla mappa.',
        '{n} removed (a biome the target does not have)':
            '{n} tolti (bioma che la destinazione non ha)',
        'biomes of {game}':
            'biomi di {game}',
        'The world itself is modified (not a copy): close the game first. A copy of the changed files goes to a “.wb-backup-…” folder next to the world.':
            'Viene modificato il mondo stesso (non una copia): chiudi prima il gioco. Una copia dei file cambiati va in una cartella «.wb-backup-…» accanto al mondo.',
        'Edit the world':
            'Modifica del mondo',
        'Delete the {n} selected chunks from the world?':
            'Cancellare dal mondo i {n} chunk selezionati?',
        'Keep only the {n} selected chunks in the dimension shown and delete all the others?':
            'Tenere nella dimensione mostrata solo i {n} chunk selezionati e cancellare tutti gli altri?',
        'This world does not store biomes.':
            'Questo mondo non memorizza i biomi.',
        'Give the biome “{biome}” to the {n} selected chunks?':
            'Dare il bioma «{biome}» ai {n} chunk selezionati?',
        'World edited: {summary}':
            'Mondo modificato: {summary}',
        'Done: {summary}.':
            'Fatto: {summary}.',
        'Edit failed: {error}':
            'Modifica non riuscita: {error}',
        'Edit failed:':
            'Modifica non riuscita:',
        'Editing the world…':
            'Modifica del mondo in corso…',
        '(this game does not store biomes)':
            '(questo gioco non memorizza i biomi)',
    },
    'worldbridge/gui/manageui.py': {
        'Where':
            'Dove',
        'This player has no inventory.':
            'Questo giocatore non ha un inventario.',
        'Show the empty slots ({n})':
            'Mostra gli slot vuoti ({n})',
        '{n} entries':
            '{n} voci',
        '{n} elements':
            '{n} elementi',
        'this tag has no value to write':
            'questo tag non ha un valore da scrivere',
        'World to edit:':
            'Mondo da modificare:',
        'The world opened at the top, or another one: folder or save file':
            'Il mondo aperto in alto, oppure un altro: cartella o file di salvataggio',
        'Java, Bedrock, Pocket Edition, LCE; Enter opens the path typed':
            'Java, Bedrock, Pocket Edition, LCE; Invio per aprire il percorso scritto',
        'Open folder…':
            'Apri cartella…',
        'Edit another world (folder)':
            'Modifica un altro mondo (cartella)',
        'Open file…':
            'Apri file…',
        'Edit another world (save file)':
            'Modifica un altro mondo (file di salvataggio)',
        'Use the world opened at the top':
            'Usa il mondo aperto in alto',
        'Go back to the world chosen at the top of the window':
            'Torna al mondo scelto in cima alla finestra',
        'Open a world to see and edit its settings, its players and all its NBT data.':
            'Apri un mondo per vederne e modificarne le impostazioni, i giocatori e tutti i dati NBT.',
        'Quick settings':
            'Impostazioni rapide',
        'Documents':
            'Documenti',
        'Name':
            'Nome',
        'Type':
            'Tipo',
        'Value':
            'Valore',
        'Double-click a value to change it · right-click to add, rename or remove a tag':
            'Doppio clic su un valore per cambiarlo · tasto destro per aggiungere, rinominare o togliere un tag',
        'Reload':
            'Ricarica',
        'Read the world from disk again (unsaved changes are lost)':
            'Rileggi il mondo dal disco (le modifiche non salvate si perdono)',
        '&Save changes':
            '&Salva le modifiche',
        'Write the changes into the world (a *.wb-backup copy first)':
            'Scrivi le modifiche nel mondo (prima una copia di sicurezza *.wb-backup)',
        'World folder':
            'Cartella del mondo',
        'Save file (LCE: saveData.ms, savegame.dat, GAMEDATA…)':
            'Salvataggio (LCE: saveData.ms, savegame.dat, GAMEDATA…)',
        'Cannot open the world: {error}':
            'Non riesco ad aprire il mondo: {error}',
        '<b>read-only</b> (Xbox 360 STFS package)':
            "<b>solo lettura</b> (pacchetto STFS dell'Xbox 360)",
        'Not in the world: writing a value adds it':
            'Non presente nel mondo: scrivendo un valore viene aggiunto',
        'Inventory':
            'Inventario',
        'Slot':
            'Slot',
        'Item':
            'Oggetto',
        'Count':
            'Quantità',
        "Double-click to change the item (e.g. minecraft:diamond) or the count; the item's other data (enchantments, name) are in the tree on the right.":
            "Doppio clic per cambiare oggetto (es. minecraft:diamond) o quantità; gli altri dati dell'oggetto (incantesimi, nome) sono nell'albero a destra.",
        'Invalid value':
            'Valore non valido',
        'Invalid value for “{field}”':
            'Valore non valido per «{field}»',
        'Edit value':
            'Modifica valore',
        'Add tag':
            'Aggiungi tag',
        'Rename…':
            'Rinomina…',
        'Remove':
            'Togli',
        'New tag':
            'Nuovo tag',
        'Name:':
            'Nome:',
        'Name already used':
            'Nome già usato',
        'There is already a tag “{name}”.':
            "C'è già un tag «{name}».",
        'Rename':
            'Rinomina',
        'New name:':
            'Nuovo nome:',
        'Unsaved changes':
            'Modifiche non salvate',
        'The world has unsaved changes. Save them before going on?':
            'Il mondo ha modifiche non salvate. Salvarle prima di continuare?',
        'Saving failed':
            'Salvataggio non riuscito',
        'Saved (backup copy: *.wb-backup)':
            'Salvato (copia di sicurezza: *.wb-backup)',
    },
    'worldbridge/gui/widgets.py': {
        'Show the explanation':
            'Mostra la spiegazione',
        'Help':
            'Aiuto',
        'Close the message':
            'Chiudi il messaggio',
    },
    'worldbridge/gui/app.py': {
        'Legacy Console Edition (consoles + PC port)':
            'Legacy Console Edition (console + PC port)',
        'Pocket Edition 0.1 – 0.8 (old format)':
            'Pocket Edition 0.1 – 0.8 (vecchio formato)',
        'For worlds born before 1.18 (LCE, old Java / Bedrock, Pocket Edition) converted to Java or Bedrock 1.18+: the chunks are written as pre-1.18 chunks, so when the world is opened Minecraft blends them with the new terrain (heights and biomes) and generates the part below y 0.\nUnticked, the chunks are written in the new format: no blending, no terrain below y 0.':
            "Per mondi nati prima della 1.18 (LCE, vecchie Java / Bedrock, Pocket Edition) convertiti in Java o Bedrock 1.18+: i chunk vengono scritti come chunk pre-1.18, così Minecraft all'apertura li fonde col terreno nuovo (altezze e biomi) e genera la parte sotto y 0.\nTogliendo la spunta i chunk sono scritti nel formato nuovo: niente fusione, niente terreno sotto y 0.",
        "For the games that do not blend (Java Alpha 1.2 – 1.17, LCE neoLegacy): WorldBridge writes around the converted world a ring of terrain made by the game's generator (same seed), which passes smoothly from the converted edge to that version's terrain; in the Nether and the End too.\nPocket Edition 0.x and LCE with a 54 / 64-chunk map: the world is finite and is written whole, with natural terrain joining the converted world around it.":
            "Per i giochi che non fanno blending (Java Alpha 1.2 – 1.17, LCE neoLegacy): WorldBridge scrive intorno al mondo convertito un anello di terreno generato col generatore del gioco (stesso seed), che passa dolcemente dal bordo convertito al terreno di quella versione; anche nel Nether e nell'End.\nPocket Edition 0.x e LCE con mappa da 54 / 64 chunk: il mondo è finito e viene scritto per intero, con terreno naturale raccordato intorno al mondo convertito.",
        '1.18+ worlds (y −64 to 319) to games whose world starts at y 0 (Java 1.2 – 1.17, LCE, Bedrock up to 1.17, and older versions).\nAutomatic: a flat or low world (its surface mostly below y 0, like superflat) keeps everything, a normal one is cut.\nCut: what lies below y 0 disappears, the rest stays at its height.\nKeep everything: nothing disappears below, the world rises by 64 blocks (useful if you built below y 0); the mountains that no longer fit are compressed or cut as you choose below.\nFrom a chosen y: below that y it disappears, the rest rises to start from y 0.':
            'Mondi 1.18+ (da y −64 a 319) verso giochi il cui mondo parte da y 0 (Java 1.2 – 1.17, LCE, Bedrock fino alla 1.17, e le versioni più vecchie).\nAutomatico: un mondo piatto o basso (la superficie quasi tutta sotto y 0, come il superpiatto) tiene tutto, uno normale viene tagliato.\nTaglia: quello che sta sotto y 0 sparisce, il resto resta alla sua altezza.\nMantieni tutto: niente sparisce sotto, il mondo sale di 64 blocchi (utile se hai costruito sotto y 0); le montagne che non entrano più vengono compresse o tagliate come scegli qui sotto.\nDa una y scelta: sotto quella y sparisce, il resto sale fino a partire da y 0.',
        "When the terrain does not fit the target game's height: the mountains of 1.18+ worlds (up to y 319, and even more if you keep the underground) to the games 256 blocks high, and to those 128 blocks high (Alpha, Beta, Java 1.0 – 1.1, Pocket Edition 0.x).\nCompress: nothing changes at the bottom; higher up every column loses a band of rock under the surface, so mountains stay mountains (lower) with grass, snow, trees and buildings intact. Bases dug into the mountain come down whole.\nCut: everything above the limit disappears and flat stone plateaus remain.":
            "Quando il terreno non entra nell'altezza del gioco di destinazione: le montagne dei mondi 1.18+ (fino a y 319, e ancora di più se tieni il sottosuolo) verso i giochi alti 256 blocchi, e verso quelli alti 128 (Alpha, Beta, Java 1.0 – 1.1, Pocket Edition 0.x).\nComprimi: in basso non cambia nulla; più su ogni colonna perde una fascia di roccia sotto la superficie, così le montagne restano montagne (più basse) con erba, neve, alberi e costruzioni intatti. Le basi scavate dentro la montagna scendono intere.\nTaglia: tutto quello che sta sopra il limite sparisce e restano tavolati di pietra piatti.",
        'The game loads the main player from players/<XUID>.dat: the XUID is a number the game gives your user, not the nickname. With “From my world…” you take it from a world you have already played.':
            "Il gioco carica il giocatore principale da players/<XUID>.dat: l'XUID è un numero che il gioco dà al tuo utente, non il nickname. Con «Dal mio mondo…» lo prendi da un mondo che hai già giocato.",
        'Format not recognised.':
            'Formato non riconosciuto.',
        'Choose the world folder or the save file (saveData.ms, savegame.dat, GAMEDATA, .bin, level.dat, .mclevel, .mcworld…).':
            'Scegli la cartella del mondo o il file di salvataggio (saveData.ms, savegame.dat, GAMEDATA, .bin, level.dat, .mclevel, .mcworld…).',
        'Name: {name}':
            'Nome: {name}',
        'Chunks – {counts}':
            'Chunk – {counts}',
        'Spawn: {x}, {y}, {z} · Players: {n}':
            'Spawn: {x}, {y}, {z} · Giocatori: {n}',
        'Platform: {platform} · save version {version}':
            'Piattaforma: {platform} · versione salvataggio {version}',
        'Name: {name} · save version {version}':
            'Nome: {name} · versione salvataggio {version}',
        '{dim}: {n} regions':
            '{dim}: {n} regioni',
        'World type: {type} (sea at y {sea}) → Overworld lowered by {shift} blocks · Players: {n}':
            'Tipo di mondo: {type} (mare a y {sea}) → overworld abbassato di {shift} blocchi · Giocatori: {n}',
        'Target: Minecraft Java 26.3 (the only conversion available for Better than Adventure).':
            'Destinazione: Minecraft Java 26.3 (unica conversione disponibile per Better than Adventure).',
        'Version: {version}':
            'Versione: {version}',
        'Partial analysis: {error}':
            'Analisi parziale: {error}',
        'Error: {error}':
            'Errore: {error}',
        'Conversion cancelled.':
            'Conversione annullata.',
        'Conversion':
            'Conversione',
        'Map and chunks':
            'Mappa e chunk',
        'Players':
            'Giocatori',
        'World management':
            'Gestione mondo',
        '&World:':
            '&Mondo:',
        'Drop the world folder or the save file here':
            'Trascina qui la cartella del mondo o il file di salvataggio',
        'Open folder…':
            'Apri cartella…',
        "Open a world's folder (Ctrl+O)":
            'Apri la cartella di un mondo (Ctrl+O)',
        'Open file…':
            'Apri file…',
        'Open a save file: saveData.ms, savegame.dat, GAMEDATA, .mcworld… (Ctrl+Shift+O)':
            'Apri un file di salvataggio: saveData.ms, savegame.dat, GAMEDATA, .mcworld… (Ctrl+Maiusc+O)',
        'About {app}':
            'Informazioni su {app}',
        'Universal Minecraft world converter.':
            'Convertitore universale di mondi Minecraft.',
        'No world open. Java, Bedrock, Legacy Console Edition, Pocket Edition, Classic / Indev and Better than Adventure are recognised automatically.':
            'Nessun mondo aperto. Java, Bedrock, Legacy Console Edition, Pocket Edition, Classic / Indev e Better than Adventure vengono riconosciuti da soli.',
        'Target':
            'Destinazione',
        '&Game:':
            '&Gioco:',
        '(latest)':
            '(ultima)',
        '&Version:':
            '&Versione:',
        'Pocket Edition 0.1 – 0.8 <b>chunks.dat</b> format: a 256 × 256-block world, 128 high, Overworld only. The area is centred on the spawn.':
            "Formato <b>chunks.dat</b> di Pocket Edition 0.1 – 0.8: mondo 256 × 256 blocchi, alto 128, solo Overworld. L'area viene centrata sullo spawn.",
        'Terrain':
            'Terreno',
        'Game &blending':
            '&Blending del gioco',
        'Minecraft Java / Bedrock 1.18+ blends the converted chunks with the new terrain':
            'Minecraft Java / Bedrock 1.18+ fonde i chunk convertiti col terreno nuovo',
        'Transition &ring':
            'Anello di &raccordo',
        'Around the converted world, terrain generated as in the target game':
            'Intorno al mondo convertito, terreno generato come nel gioco di destinazione',
        'Terrain border:':
            'Raccordo col terreno:',
        'Automatic (keep the underground of flat or low worlds)':
            'Automatico (tiene il sottosuolo dei mondi piatti o bassi)',
        'Cut below y 0':
            'Taglia sotto y 0',
        'Keep everything (the world rises by 64 blocks)':
            'Mantieni tutto (il mondo sale di 64 blocchi)',
        'Keep from a chosen y':
            'Mantieni da una y scelta',
        'What happens to what lies below y 0 in 1.18+ worlds':
            'Cosa succede a quello che sta sotto y 0 nei mondi 1.18+',
        '&Underground of 1.18+ worlds:':
            '&Sottosuolo dei mondi 1.18+:',
        'Compress (the surface comes down whole) – recommended':
            'Comprimi (la superficie scende intera) – consigliato',
        "Cut at the world's limit":
            'Taglia al limite del mondo',
        "The terrain that does not fit the target game's height":
            "Il terreno che non entra nell'altezza del gioco di destinazione",
        '&Tall mountains:':
            'Mon&tagne troppo alte:',
        'What is converted':
            'Cosa viene convertito',
        'Choose on the map…':
            'Scegli sulla mappa…',
        'Chunks to convert, moving, spawn, biomes, Nether and End (Map and chunks tab)':
            'Chunk da convertire, spostamento, spawn, biomi, Nether ed End (scheda Mappa e chunk)',
        'World:':
            'Mondo:',
        'Choose the players…':
            'Scegli i giocatori…',
        'Players:':
            'Giocatori:',
        'Result':
            'Risultato',
        'Same as the source world':
            'Come il mondo di origine',
        'World &name:':
            '&Nome del mondo:',
        'Browse…':
            'Sfoglia…',
        'Output &folder:':
            'Cartella di d&estinazione:',
        'The converted world goes into a new folder in here; the source world is never modified.':
            'Il mondo convertito va in una nuova cartella qui dentro; il mondo di origine non viene mai modificato.',
        'Conversion log':
            'Registro della conversione',
        '{version} (latest) – best route automatically  [recommended]':
            '{version} (ultima) – percorso migliore automatico  [consigliato]',
        '{version} – pre-converted blocks':
            '{version} – blocchi pre-convertiti',
        '1.9 → latest – upgraded by Minecraft when opened (DataFixer)':
            "1.9 → ultima – aggiornato da Minecraft all'apertura (DataFixer)",
        '{version} – numeric Anvil format':
            '{version} – formato Anvil numerico',
        '{version} – McRegion format':
            '{version} – formato McRegion',
        '{version} – Alpha format (World1…World5 folder)':
            '{version} – formato Alpha (cartella World1…World5)',
        'Java 26.1+ worlds are written in the classic layout: on first start Minecraft migrates them to the new format by itself (dimensions/, players/).':
            'I mondi Java 26.1+ vengono scritti nel layout classico: al primo avvio Minecraft li migra da sé nel nuovo formato (dimensions/, players/).',
        'Alpha and Beta up to 1.2_02 only see the worlds in the World1 … World5 folders of .minecraft/saves: the world is written into the first free one.':
            'Alpha e Beta fino alla 1.2_02 vedono solo i mondi nelle cartelle World1 … World5 di .minecraft/saves: il mondo viene scritto nella prima libera.',
        'Default: woods chosen by the average colour of the textures':
            'Predefinita: legni scelti per colore medio delle texture',
        ".properties file that chooses which vanilla wood each colour of BTA's painted wood becomes (example: worldbridge/bta/data/palette.example.properties)":
            'File .properties che sceglie in quale legno vanilla diventa ogni colore del legno dipinto di BTA (esempio: worldbridge/bta/data/palette.example.properties)',
        'Wood palette:':
            'Palette dei legni:',
        'Automatic':
            'Automatico',
        "Lowers the Overworld so that BTA's sea matches the vanilla one (y 63): 65 blocks for “extended” worlds, 1 for the classic ones. BTA's underground ends up below y 0, so nothing is lost.":
            "Abbassa l'overworld perché il mare di BTA coincida con quello vanilla (y 63): 65 blocchi per i mondi «extended», 1 per quelli classici. Il sottosuolo BTA finisce sotto y 0, quindi non si perde nulla.",
        'blocks':
            'blocchi',
        'Lower the Overworld:':
            "Abbassa l'overworld:",
        'The world is written in the 1.18.2 format and upgraded by Minecraft 26.3 when opened (official DataFixer), which blends the new terrain with the converted one. The Drift becomes The End.':
            "Il mondo viene scritto in formato 1.18.2 e aggiornato da Minecraft 26.3 all'apertura (DataFixer ufficiale), che fonde il terreno nuovo con quello convertito. Il Drift diventa The End.",
        '&Platform:':
            '&Piattaforma:',
        'Game version:':
            'Versione del gioco:',
        'World &size:':
            '&Dimensione del mondo:',
        'Centre on the spawn':
            'Centra sullo spawn',
        'Chunk at the centre of the converted area':
            "Chunk al centro dell'area convertita",
        'otherwise centre at chunk':
            'altrimenti centro nel chunk',
        'Area:':
            'Area:',
        'From my world…':
            'Dal mio mondo…',
        'Take the XUID from a world you have already played':
            "Prendi l'XUID da un mondo che hai già giocato",
        'Player ID (optional):':
            'ID giocatore (facoltativo):',
        'Choose the BTA palette':
            'Scegli la palette BTA',
        'Palette':
            'Palette',
        'All files':
            'Tutti i file',
        'same as the source LCE world':
            'come il mondo LCE di origine',
        'Automatic ({size})':
            'Automatica ({size})',
        'and the <i>GAMEDATA_*</i> files':
            'e i file <i>GAMEDATA_*</i>',
        'copy the generated folder into <i>Windows64/GameHDD/</i>.':
            'copia la cartella generata in <i>Windows64/GameHDD/</i>.',
        'put {files} in place of those of an existing save of the console.':
            'metti {files} al posto di quelli di un salvataggio esistente della console.',
        'LCE worlds have a finite size: the chunks outside the chosen area are left out. Then {where}':
            "I mondi LCE hanno dimensione finita: i chunk fuori dall'area scelta vengono esclusi. Poi {where}",
        'Choose one of your played worlds (saveData.ms, savegame.dat…)':
            'Scegli un tuo mondo già giocato (saveData.ms, savegame.dat…)',
        'LCE saves':
            'Salvataggi LCE',
        'Player ID':
            'ID giocatore',
        'Cannot read the save:':
            'Non riesco a leggere il salvataggio:',
        'There is no player with an XUID in this world.':
            "In questo mondo non c'è nessun giocatore con un XUID.",
        'Which one are you?':
            'Chi sei tu?',
        'Open the world folder':
            'Apri la cartella del mondo',
        'Open the save file':
            'Apri il file di salvataggio',
        'Minecraft saves':
            'Salvataggi Minecraft',
        'Analysing…':
            'Analisi in corso…',
        'Choose the output folder':
            'Scegli la cartella di destinazione',
        'Ready':
            'Pronto',
        'Every tab except “World management” prepares this conversion.':
            'Tutte le schede tranne «Gestione mondo» preparano questa conversione.',
        'Open the result folder':
            'Apri la cartella del risultato',
        '&Cancel':
            '&Annulla',
        'C&onvert':
            '&Converti',
        'Convert the world with the choices of these tabs (Ctrl+Enter)':
            'Converti il mondo con le scelte di queste schede (Ctrl+Invio)',
        'Open the world to convert first: drop it into the window or use “Open folder…” / “Open file…” at the top.':
            'Apri prima il mondo da convertire: trascinalo nella finestra o usa «Apri cartella…» / «Apri file…» in alto.',
        'You chose “Selected chunks only” but no chunk is selected on the map.':
            'Hai scelto «Solo i chunk selezionati» ma sulla mappa non è selezionato nessun chunk.',
        'Go to the map':
            'Vai alla mappa',
        'Convert the whole world':
            'Converti tutto il mondo',
        "Alpha and Beta up to 1.2_02 only see the worlds in the World1 … World5 folders of .minecraft/saves: copy the folder as it is (the folder's name is the world slot).":
            "Alpha e Beta fino alla 1.2_02 vedono solo i mondi nelle cartelle World1 … World5 di .minecraft/saves: copia la cartella così com'è (il nome della cartella è lo slot del mondo).",
        'Starting…':
            'Avvio…',
        'Cancelling…':
            'Annullamento in corso…',
        '… (see the log)':
            '… (vedi il registro)',
        'Completed':
            'Completato',
        'Conversion completed.':
            'Conversione completata.',
        'Warnings:':
            'Avvisi:',
        '… and {n} more (in the log).':
            '… e altri {n} (nel registro).',
        'Open the folder':
            'Apri la cartella',
        'Stopped':
            'Interrotta',
        'Conversion failed.':
            'Conversione non riuscita.',
        'The details are in the log below.':
            'I dettagli sono nel registro qui sotto.',
        'Language of the interface':
            "Lingua dell'interfaccia",
        'The language can be changed when no conversion or change to the world is running and the world management tab has no unsaved changes.':
            "La lingua si può cambiare quando non c'è una conversione o una modifica del mondo in corso e la scheda «Gestione mondo» non ha modifiche non salvate.",
        'A conversion is running: the world can be changed when it ends.':
            'Una conversione è in corso: il mondo si può cambiare quando finisce.',
        'The world is being edited: it can be changed when the edit ends.':
            'Il mondo è in modifica: si può cambiare quando la modifica finisce.',
        'A change to the source world (edit, trim or copy) is running: convert when it ends.':
            'Una modifica del mondo di origine (modifica, trim o copia) è in corso: converti quando finisce.',
    },
}

IT = {k: v for d in _SECTIONS.values() for k, v in d.items()}
