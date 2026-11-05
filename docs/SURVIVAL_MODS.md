# Survival mods: phase 0.4 research

This note records source inspection and a reproducible artifact lock for the isolated phase 0.4 validation. It does not claim gameplay testing or establish that the mods have been installed or run together. Exact artifact metadata and recomputed hashes are in [survival-mods.lock.json](survival-mods.lock.json).

## Target and preparation boundaries

- Target: Minecraft 1.21.1, Fabric Loader 0.20.1, Java 21. Both mod JARs declare minimum Fabric Loader 0.19.5, so 0.20.1 meets their declared floor.
- Cached inputs are kept in `data/phase04-research/`.
- The planned isolated validation directory is `data/validation/phase04/`.
- Preparing that isolated directory is a separate step from installing mods. This research made no launcher, save, or main modpack changes and did not install any mod.
- Runtime JARs are authoritative Modrinth files; their metadata JSON and cached bytes were used to check SHA-512/SHA-1 and sizes. Sources JARs are locked separately for source inspection and are not runtime dependencies.

## Mod metadata and declared compatibility

Dehydration `1.4.2+1.21.1` (`dehydration`, project `qWDh3G0p`, version `Ls1nAcYc`) declares Fabric, Minecraft 1.21.1, and client-and-server environment. Required metadata: Java `>=21`, Minecraft `>=1.21.1`, Fabric API `>=0.116.17+1.21.1`, Fabric Loader `>=0.19.5`, and `cloth-config2 >=15.0.140`. It suggests EnvironmentZ. Source repository: [Globox1997/Dehydration](https://github.com/Globox1997/Dehydration), branch `1.21`.

EnvironmentZ `2.2.0+1.21.1` (`environmentz`, project `TggYmc6t`, version `l7EZhw1K`) declares Fabric, Minecraft 1.21.1, and client-and-server environment. Required metadata: Java `>=21`, Minecraft `>=1.21.1`, Fabric API `>=0.116.17+1.21.1`, Fabric Loader `>=0.19.5`, `cloth-config2 >=15.0.140`, and `satin >=2.0.0`. It suggests Dehydration. Source repository: [Globox1997/EnvironmentZ](https://github.com/Globox1997/EnvironmentZ), branch `1.21`.

The selected Fabric API `0.116.17+1.21.1` declares Minecraft `>=1.21- <1.21.2-`, Java `>=21`, and Loader `>=0.15.11`; it provides the metadata alias `fabric` and bundles component JARs under `META-INF/jars/`. Cloth Config `15.0.140+fabric` has mod ID `cloth-config`, provides `cloth-config2`, and contains `META-INF/jars/basic-math-0.6.1.jar`. Satin `2.0.0` has environment `client_only`; EnvironmentZ nevertheless declares it as a dependency without a side qualifier. That side interaction must be resolved during isolated loader validation, not assumed from the metadata.

Both mod JARs declare the same lower bounds for the principal game/API requirements. The lock does not claim these ranges alone prove joint runtime compatibility.

## Inspected APIs

### Dehydration

The source JAR exposes `net.dehydration.access.ThirstManagerAccess#getThirstManager(): ThirstManager`. The manager exposes `getThirstLevel(): int`, `isNotFull(): boolean`, `hasThirst(): boolean`, `setThirstLevel(int)`, `add(int)`, `addDehydration(float)`, and `setThirst(boolean)`. The current level initializes to 20; `add(int)` caps its upper end at 20. The source does not expose a maximum-level getter, and `setThirstLevel(int)` itself does not clamp. Thus 0–20 describes the ordinary gameplay scale observed in this source, not a validated invariant for every mutation path.

`DehydrationAPI#calculateDrinkThirst(ItemStack, PlayerEntity): int` calculates an item's hydration/quench contribution. It is not a getter for the player's current hydration. `HydrationTemplate#getHydration(): int` likewise represents an item's configured hydration amount. No safe-water query or maximum-hydration API was found in the inspected source.

`PlayerEntityMixin` updates thirst only when running server-side. `ServerPlayerEntityMixin` sends thirst-level packets to clients; the client packet receiver writes received values into its local manager. Treat server state as authoritative and client values as the most recently synchronized mirror.

### EnvironmentZ

The public facade `net.environmentz.api.EnvironmentzApi` provides:

- `getTemperatureManager(PlayerEntity): TemperatureManager`
- `getTemperature(PlayerEntity): int` (current player body-temperature value)
- `getWetness(PlayerEntity): int` (wetness intensity)
- `isHeatAffected(PlayerEntity): boolean` and `isColdAffected(PlayerEntity): boolean`
- `isFreezing(PlayerEntity): boolean` (current value `<= BodyTemperature.maxCold()`)
- `isOverheating(PlayerEntity): boolean` (current value `>= BodyTemperature.maxHot()`)
- `getBodyTemperatureThresholds(): BodyTemperature`
- Server-player mutators `setTemperature(ServerPlayerEntity, int)`, `setEnvironmentAffection(ServerPlayerEntity, boolean, boolean)`, `setResistance(ServerPlayerEntity, int, int)`, and `setProtection(ServerPlayerEntity, int, int)`.

`TemperatureManager` additionally exposes `getPlayerTemperature(): int`, `getPlayerWetIntensityValue(): int`, `getPlayerHeatProtectionAmount(): int`, `getPlayerColdProtectionAmount(): int`, `getPlayerHeatResistance(): int`, `getPlayerColdResistance(): int`, and `getThermometerTemperature(): int`. The thermometer value is a separate breakdown/measurement value; it is not the player's body temperature. No standalone current ambient-biome-temperature or exposure getter was found. The public surface exposes body temperature, wetness, and whether hot/cold environment effects apply.

Temperature is an internal integer scale in the inspected implementation. Do not interpret its values as Celsius. Datapack records configure body thresholds (`max_very_cold`, `max_cold`, `min_cold`, `normal`, `min_hot`, `max_hot`, `max_very_hot`), wetness limits, and biome temperature tiers; body threshold and wetness fields are integer-coded and configurable. The older descriptive text's Celsius phrasing does not establish the Java API's numeric unit. Environment temperature computation/ticking and authoritative synchronization run server-side; packets mirror temperature/wetness and configuration values to the client.

## Joint compatibility and unverified behavior

EnvironmentZ contains direct Dehydration compatibility code: it checks whether Dehydration is loaded, reads `ThirstManager#getThirstLevel()`, and can call `addDehydration(float)` in its hot-environment/sweat logic. Dehydration metadata suggests EnvironmentZ, and EnvironmentZ metadata suggests Dehydration. This is evidence of declared and code-level, one-way integration in the inspected version pair. It is not evidence of joint gameplay validation, installation success, safe-water semantics, or any in-game result.

No TechReborn research is included in this phase note.
