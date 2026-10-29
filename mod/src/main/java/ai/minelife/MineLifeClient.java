package ai.minelife;

import com.google.gson.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.rendering.v1.HudRenderCallback;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.block.Block;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.registry.tag.BlockTags;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.stat.Stats;
import net.minecraft.text.Text;
import net.minecraft.util.Hand;
import net.minecraft.util.WorldSavePath;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.*;
import net.minecraft.world.GameMode;
import net.minecraft.world.RaycastContext;
import org.lwjgl.glfw.GLFW;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

public final class MineLifeClient implements ClientModInitializer {
    private static final Logger LOG = LoggerFactory.getLogger("minelife_ai");
    private static final Gson JSON = new Gson();
    private final MinecraftClient mc = MinecraftClient.getInstance();
    private final HttpClient http = HttpClient.newBuilder()
    .version(HttpClient.Version.HTTP_1_1)
    .connectTimeout(Duration.ofMillis(800))
    .build();
    private final List<JsonObject> results = new ArrayList<>();
    private final Set<String> seenCommands = new LinkedHashSet<>();
    private KeyBinding toggle, pause, emergency;
    private Navigator navigator;
    private String token, session, world, dimension;
    private boolean active, armed;
    private final ControlGate gate = new ControlGate();
    private boolean handshaken, handshakeRequest;
    private int failures;
    private long nextPoll, sensorTick = -100;
    private JsonArray cachedBlocks = new JsonArray(), cachedFrontiers = new JsonArray(), cachedRecipes = new JsonArray();
    private CraftingController crafting;
    private String status = "Desativada · F8";
    private long seq, ticks, lastReply, lastPoll;
    private CompletableFuture<HttpResponse<String>> request;
    private JsonObject command;
    private long commandStart;
    private BlockPos target;
    private Block originalBlock;
    private boolean attacked;
    private int airTicks;
    private CompletableFuture<JsonObject> baseline, after;

    @Override public void onInitializeClient() {
        navigator = new Navigator(mc);
        crafting = new CraftingController(mc);
        toggle = key("Ativar/desativar MineLife AI", GLFW.GLFW_KEY_F8);
        pause = key("Pausar/retomar MineLife AI", GLFW.GLFW_KEY_F9);
        emergency = key("Emergencia MineLife AI", GLFW.GLFW_KEY_F10);
        try {
            Path config = FabricLoader.getInstance().getConfigDir().resolve("minelife-ai.json");
            token = JsonParser.parseString(Files.readString(config)).getAsJsonObject().get("token").getAsString();
            if (token.length() < 32) throw new IllegalArgumentException("token curto");
        } catch (Exception e) { token = null; status = "Instale a configuracao local"; LOG.warn("MineLife: configuracao local ausente/invalida."); }
        ClientTickEvents.END_CLIENT_TICK.register(client -> tick());
        HudRenderCallback.EVENT.register((draw, counter) -> {
            if (mc.player != null) draw.drawTextWithShadow(mc.textRenderer, "MineLife AI: " + status, 8, 8, active ? 0x88ff99 : 0xffcc77);
        });
    }

    private KeyBinding key(String name, int code) {
        return KeyBindingHelper.registerKeyBinding(new KeyBinding(name, InputUtil.Type.KEYSYM, code, "MineLife AI"));
    }

    private void tick() {
        ticks++;
        if (mc.player == null || mc.world == null || mc.getServer() == null) {
            if (world != null) { stop("Mundo desconectado", true); resetSession(); world = null; }
            return;
        }
        String currentDimension = mc.world.getRegistryKey().getValue().toString();
        if (world == null || !currentDimension.equals(dimension)) {
            stop("F8 para autorizar", true); resetSession();
            try {
                Path path = mc.getServer().getSavePath(WorldSavePath.ROOT).toRealPath();
                String identity = path + "|" + Files.readAttributes(path, BasicFileAttributes.class).creationTime().toMillis()
                        + "|" + mc.getServer().getOverworld().getSeed();
                world = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(identity.getBytes(StandardCharsets.UTF_8)));
                dimension = currentDimension;
            } catch (Exception e) { status = "Nao foi possivel identificar o mundo"; return; }
        }
        if (emergency.wasPressed()) {
            handleKey(10);
            while(toggle.wasPressed()) { }
            while(pause.wasPressed()) { }
        } else {
            while (toggle.wasPressed()) handleKey(8);
            while (pause.wasPressed()) handleKey(9);
        }
        if (request != null && request.isDone()) receive();
        long now = System.nanoTime();
        if (active && (gate.heartbeatExpired(now,lastReply) || dangerous() || (mc.currentScreen != null && !crafting.ownsScreen()) || !mc.isWindowFocused())) {
            stop("Pausa de seguranca · F8", true);
        }
        if (active && command != null) {
            try { executeCommand(); }
            catch (Exception e) { stop("Falha na acao · F8", true); LOG.warn("MineLife: acao interrompida sem evidencia conclusiva."); }
        }
        if (token != null && request == null && now >= nextPoll && now - lastPoll >= 250_000_000L) poll();
    }

    private void handleKey(int key) {
        gate.active = active; gate.armed = armed;
        gate.key(key, key != 10 && canStart());
        if (!gate.active) {
            String state = gate.state;
            stop(state.equals("EMERGENCY_STOP") ? "Emergencia · F8" : "Pausada/desativada", !gate.armed);
            gate.state = state;
        } else { active = true; armed = true; status = "Observando"; }
    }

    private boolean canStart() {
        if (token == null || !handshaken || gate.heartbeatExpired(System.nanoTime(),lastReply)) { status = "Backend desconectado"; return false; }
        if (mc.interactionManager == null || mc.interactionManager.getCurrentGameMode() != GameMode.SURVIVAL) {
            status = "Requer Survival"; return false;
        }
        if (dangerous() || mc.currentScreen != null) { status = "Condicao insegura"; return false; }
        return true;
    }

    private boolean dangerous() {
        return mc.player == null || !mc.player.isAlive() || mc.player.getHealth() <= 8 || mc.player.getHungerManager().getFoodLevel() <= 6
            || mc.player.isOnFire() || mc.player.isTouchingWater() || mc.player.isInLava() || mc.player.fallDistance > 2
            || !mc.world.getEntitiesByClass(HostileEntity.class, mc.player.getBoundingBox().expand(5), e -> e.isAlive()).isEmpty()
            || mc.interactionManager.getCurrentGameMode() != GameMode.SURVIVAL;
    }

    private void resetSession() {
        if (request != null) request.cancel(true);
        request = null; session = UUID.randomUUID().toString(); seq = 0; results.clear(); seenCommands.clear(); lastReply = 0;
        handshaken = false; sensorTick = -100; nextPoll = 0;
    }

    private void stop(String why, boolean disarm) {
        if (command != null) finish("cancelled", "control_interrupted", new JsonObject());
        if (active || armed) {
            navigator.release();
            mc.options.attackKey.setPressed(false); mc.options.useKey.setPressed(false);
            if (mc.interactionManager != null) { mc.interactionManager.cancelBlockBreaking(); if (mc.player != null) mc.interactionManager.stopUsingItem(mc.player); }
            if (mc.player != null) { mc.player.setSprinting(false); mc.player.input.movementForward = 0; mc.player.input.movementSideways = 0; mc.player.input.jumping = false; }
        }
        active = false; if (disarm) armed = false; status = why;
        gate.stop("PAUSED", disarm);
        if (crafting != null) crafting.cancel();
    }

    private void poll() {
        lastPoll = System.nanoTime();
        if (!handshaken) {
            handshakeRequest = true;
            HttpRequest req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8765/bridge/handshake"))
                .version(HttpClient.Version.HTTP_1_1).timeout(Duration.ofMillis(1800))
                .header("Authorization", "Bearer " + token).GET().build();
            request = http.sendAsync(req, HttpResponse.BodyHandlers.ofString());
            return;
        }
        handshakeRequest = false;
        JsonObject body = observation();
        HttpRequest req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8765/bridge/step"))
            .version(HttpClient.Version.HTTP_1_1).timeout(Duration.ofMillis(1800)).header("Content-Type", "application/json")
            .header("Authorization", "Bearer " + token).POST(HttpRequest.BodyPublishers.ofString(JSON.toJson(body))).build();
        request = http.sendAsync(req, HttpResponse.BodyHandlers.ofString());
    }

    private void receive() {
        try {
            HttpResponse<String> response = request.join(); request = null;
            if (response.statusCode() != 200 || response.body().length() > 65536) throw new IllegalStateException("HTTP_"+response.statusCode());
            JsonObject reply = JsonParser.parseString(response.body()).getAsJsonObject();
            if (handshakeRequest) {
                if (reply.get("protocol").getAsInt()!=1 || !reply.get("transport").getAsString().equals("HTTP/1.1")) throw new IllegalStateException("protocol_mismatch");
                handshaken = true; lastReply = System.nanoTime(); failures = 0; return;
            }
            if (!reply.get("session").getAsString().equals(session) || reply.get("seq").getAsLong() != seq) throw new IllegalStateException("stale_reply");
            lastReply = System.nanoTime();
            failures = 0;
            for (JsonElement ack : reply.getAsJsonArray("ack")) results.removeIf(r -> r.get("id").getAsString().equals(ack.getAsString()));
            if (reply.has("control_epoch") && reply.get("control_epoch").getAsLong()!=gate.epoch) return;
            if (!reply.get("control").isJsonNull()) {
                switch (reply.get("control").getAsString()) {
                    case "stop" -> stop("Parada pelo painel · F8", true);
                    case "pause" -> stop("Pausada · F9", false);
                    case "start", "resume" -> { if (armed && canStart()) { gate.enable(); active = true; status = "Observando"; } }
                }
            }
            if (active && command == null && !reply.get("command").isJsonNull()) begin(reply.getAsJsonObject("command"));
            if (active && command == null && reply.has("state")) status = reply.get("state").getAsString();
        } catch (Exception e) {
            request = null;
            stop("Backend desconectado · F8", true);
            // A nova sessão impede que comandos antigos sejam reutilizados após reconexão.
            session = UUID.randomUUID().toString(); seq = 0; seenCommands.clear(); results.clear(); lastReply = 0;
            handshaken = false; gate.state = "DISCONNECTED";
            failures++;
            nextPoll = System.nanoTime() + Math.min(4000, 500L * failures) * 1_000_000L;
            if (failures == 1 || failures % 10 == 0) LOG.warn("MineLife bridge failure {}: {}", failures, e.getClass().getSimpleName() + ":" + (e instanceof IllegalStateException ? e.getMessage() : "network_or_message_error"));
        }
    }

    private JsonObject observation() {
        JsonObject o = new JsonObject();
        o.addProperty("protocol", 1); o.addProperty("session", session); o.addProperty("world", world);
        o.addProperty("dimension", dimension); o.addProperty("seq", ++seq);
        o.addProperty("day", Math.max(1, mc.world.getTimeOfDay() / 24000 + 1));
        o.addProperty("time", Math.floorMod(mc.world.getTimeOfDay(), 24000));
        o.addProperty("active", active); o.addProperty("armed", armed);
        o.addProperty("control_state", gate.state); o.addProperty("control_epoch", gate.epoch);
        o.add("capabilities", JSON.toJsonTree(List.of("approach","break","collect","observe","explore","craft")));
        o.addProperty("biome", mc.world.getBiome(mc.player.getBlockPos()).getKey().map(k -> k.getValue().toString()).orElse("unknown"));
        o.add("entities", new JsonArray());
        JsonObject player = new JsonObject();
        player.addProperty("x", mc.player.getX()); player.addProperty("y", mc.player.getY()); player.addProperty("z", mc.player.getZ());
        player.addProperty("health", mc.player.getHealth()); player.addProperty("food", mc.player.getHungerManager().getFoodLevel());
        player.addProperty("danger", dangerous()); player.add("inventory", inventory(mc.player.getInventory())); o.add("player", player);
        if (ticks-sensorTick >= 20) { scanSensors(); sensorTick = ticks; }
        o.add("recipes", cachedRecipes);
        o.add("blocks", cachedBlocks); o.add("frontiers", cachedFrontiers); o.add("results", JSON.toJsonTree(results));
        o.add("running", command == null ? JsonNull.INSTANCE : command.get("id"));
        return o;
    }

    private void scanSensors() {
        cachedRecipes = crafting.offers();
        JsonArray blocks = new JsonArray();
        // Scan local limitado; troncos naturais com folhas próximas, até 64 candidatos.
        BlockPos origin = mc.player.getBlockPos();
        int count = 0;
        for (BlockPos p : BlockPos.iterate(origin.add(-12, -3, -12), origin.add(12, 6, 12))) {
            if (!mc.world.isChunkLoaded(p)) continue;
            var state = mc.world.getBlockState(p);
            if (!state.isIn(BlockTags.LOGS)) continue;
            var sight=mc.world.raycast(new RaycastContext(mc.player.getEyePos(),Vec3d.ofCenter(p),RaycastContext.ShapeType.OUTLINE,RaycastContext.FluidHandling.NONE,mc.player));
            if(sight.getType()!=HitResult.Type.BLOCK || !sight.getBlockPos().equals(p)) continue;
            String id = Registries.BLOCK.getId(state.getBlock()).toString();
            if (!id.endsWith("_log") || id.contains("stripped")) continue;
            boolean leaves = false;
            for (BlockPos leaf : BlockPos.iterate(p.add(-2, 0, -2), p.add(2, 6, 2))) {
                if (mc.world.getBlockState(leaf).isIn(BlockTags.LEAVES)) { leaves = true; break; }
            }
            if (!leaves) continue;
            JsonObject b = position(p); b.addProperty("id", id); b.addProperty("log", true); blocks.add(b);
            if (++count >= 64) break;
        }
        Set<String> observed = new HashSet<>();
        for (BlockPos p : BlockPos.iterate(origin.add(-3,-1,-3),origin.add(3,2,3))) {
            var block = mc.world.getBlockState(p);
            String id = Registries.BLOCK.getId(block.getBlock()).toString();
            if (block.isAir() || block.isIn(BlockTags.LOGS) || observed.contains(id) || !navigator.visibleFrom(mc.player.getEyePos(),p)) continue;
            observed.add(id); JsonObject b = position(p); b.addProperty("id",id); b.addProperty("log",false); blocks.add(b);
            if (observed.size()>=16) break;
        }
        cachedBlocks = blocks;
        cachedFrontiers = new JsonArray();
        if (active && command == null && mc.currentScreen==null) for (BlockPos p : navigator.frontiers()) {
            JsonObject f=position(p); f.addProperty("safe",true); f.addProperty("path_length",Math.max(1,mc.player.getBlockPos().getManhattanDistance(p))); cachedFrontiers.add(f);
        }
    }

    private void begin(JsonObject c) {
        String id = c.get("id").getAsString(); UUID.fromString(id);
        if (seenCommands.contains(id)) return;
        seenCommands.add(id);
        if (seenCommands.size() > 4096) seenCommands.remove(seenCommands.iterator().next());
        String action = c.get("action").getAsString();
        if (!Set.of("approach", "break", "collect", "explore", "observe", "craft").contains(action)) return;
        JsonObject p = c.getAsJsonObject("target");
        target = new BlockPos(p.get("x").getAsInt(), p.get("y").getAsInt(), p.get("z").getAsInt());
        command = c.deepCopy(); commandStart = System.nanoTime(); attacked = false; airTicks = 0; after = null; baseline = null;
        if (target.getSquaredDistance(mc.player.getBlockPos()) > 20 * 20) { finish("failed", "out_of_local_range", new JsonObject()); return; }
        originalBlock = Registries.BLOCK.get(net.minecraft.util.Identifier.of(p.get("id").getAsString()));
        if (action.equals("craft")) {
            navigator.release();
            String error = crafting.begin(c.getAsJsonObject("recipe"));
            if (error != null) finish("failed",error,new JsonObject());
            else status = "Crafting 2x2";
            return;
        }
        if (action.equals("observe")) { after=authoritative(); return; }
        if (action.equals("explore")) {
            status="Explorando fronteira";
            if (!navigator.plan(target,false,true)) finish("failed","no_safe_path",new JsonObject());
            return;
        }
        status = switch (action) { case "approach" -> "Aproximando do tronco"; case "break" -> "Investigando tronco"; default -> "Verificando coleta"; };
        if (action.equals("break")) baseline = authoritative();
        else if (!navigator.plan(target, action.equals("collect"))) finish("failed", "no_safe_path", new JsonObject());
    }

    private void executeCommand() {
        int timeout = Math.min(20000, Math.max(500, command.get("timeout_ms").getAsInt()));
        if (System.nanoTime() - commandStart > timeout * 1_000_000L) { finish("failed", "timeout", new JsonObject()); return; }
        String action = command.get("action").getAsString();
        if (action.equals("craft")) {
            JsonObject outcome=crafting.tick();
            if (outcome != null) finish(outcome.has("error")?"failed":"success",outcome.has("error")?outcome.get("error").getAsString():"server_confirmed_craft",outcome);
            return;
        }
        if (action.equals("observe")) {
            if (!navigator.visibleFrom(mc.player.getEyePos(),target)) {finish("failed","not_visible",new JsonObject());return;}
            if (after.isDone()) finish("success","server_observation",after.join());
            return;
        }
        if (action.equals("explore")) {
            int state=navigator.tick();
            if (state<0) {finish("failed","path_obstructed",new JsonObject());return;}
            if (state>0) {
                if (after==null) after=authoritative();
                if(after.isDone()) finish("success","server_position",after.join());
            }
            return;
        }
        if (action.equals("approach")) {
            int state = navigator.tick();
            if (state < 0) finish("failed", "path_obstructed", new JsonObject());
            else if (state > 0) {
                JsonObject ev = new JsonObject(); ev.addProperty("in_reach", navigator.visibleFrom(mc.player.getEyePos(), target));
                finish(ev.get("in_reach").getAsBoolean() ? "success" : "failed", "approach_finished", ev);
            }
            return;
        }
        if (action.equals("collect")) {
            int state = navigator.tick();
            if (state < 0) { finish("failed", "path_obstructed", new JsonObject()); return; }
            if (state > 0) {
                if (++airTicks < 20) return;
                if (after == null) after = authoritative();
                if (after.isDone()) {
                    JsonObject ev = after.join();
                    int count = ev.getAsJsonObject("inventory_after").has(blockId()) ? ev.getAsJsonObject("inventory_after").get(blockId()).getAsInt() : 0;
                    if (count > command.get("baseline").getAsInt()) finish("success", "inventory_increase", ev);
                    else { after = null; airTicks = 10; }
                }
            }
            return;
        }
        navigator.release();
        if (!baseline.isDone()) return;
        if (baseline.isCompletedExceptionally()) { finish("failed", "server_evidence_unavailable", new JsonObject()); return; }
        if (!baseline.join().get("after_block").getAsString().equals(blockId())) { finish("failed", "target_changed", new JsonObject()); return; }
        if (mc.world.getBlockState(target).isAir()) {
            mc.options.attackKey.setPressed(false);
            mc.interactionManager.cancelBlockBreaking();
            if (++airTicks < 10) return;
            if (after == null) after = authoritative();
            if (!after.isDone()) return;
            JsonObject ev = after.join();
            ev.addProperty("before_block", baseline.join().get("after_block").getAsString());
            ev.add("inventory_before", baseline.join().get("inventory_after"));
            ev.addProperty("mined_delta", ev.get("mined").getAsInt() - baseline.join().get("mined").getAsInt());
            boolean verified = ev.get("after_block").getAsString().equals("minecraft:air") && ev.get("mined_delta").getAsInt() > 0;
            if (verified) finish("success", "server_confirmed_break", ev);
            else { after = null; airTicks = 0; }
            return;
        }
        if (!mc.world.getBlockState(target).isOf(originalBlock) || !navigator.visibleFrom(mc.player.getEyePos(), target)) {
            finish("failed", "target_not_visible_or_reachable", new JsonObject()); return;
        }
        Vec3d delta = Vec3d.ofCenter(target).subtract(mc.player.getEyePos());
        mc.player.setYaw((float)Math.toDegrees(Math.atan2(-delta.x, delta.z)));
        mc.player.setPitch((float)-Math.toDegrees(Math.atan2(delta.y, Math.sqrt(delta.x * delta.x + delta.z * delta.z))));
        BlockHitResult hit = mc.world.raycast(new RaycastContext(mc.player.getEyePos(), Vec3d.ofCenter(target),
                RaycastContext.ShapeType.OUTLINE, RaycastContext.FluidHandling.NONE, mc.player));
        if (hit.getType() != HitResult.Type.BLOCK || !hit.getBlockPos().equals(target)) { finish("failed", "raycast_miss", new JsonObject()); return; }
        // O loop normal do cliente atualiza a quebra enquanto attackKey permanece pressionada.
        // Não duplique updateBlockBreakingProgress: isso aceleraria artificialmente a mineração.
        mc.crosshairTarget = hit;
        mc.options.attackKey.setPressed(true);
        if (!attacked) { mc.interactionManager.attackBlock(target, hit.getSide()); attacked = true; mc.player.swingHand(Hand.MAIN_HAND); }
    }

    private String blockId() { return Registries.BLOCK.getId(originalBlock).toString(); }

    private CompletableFuture<JsonObject> authoritative() {
        CompletableFuture<JsonObject> result = new CompletableFuture<>();
        var server = mc.getServer(); var dimensionKey = mc.world.getRegistryKey();
        UUID playerId = mc.player.getUuid(); BlockPos captured = target.toImmutable(); Block capturedBlock = originalBlock;
        server.execute(() -> {
            try {
                ServerPlayerEntity player = server.getPlayerManager().getPlayer(playerId);
                var serverWorld = server.getWorld(dimensionKey);
                if (player == null || serverWorld == null) throw new IllegalStateException("no_player");
                JsonObject ev = new JsonObject(); ev.addProperty("server_verified", true);
                JsonObject pos=new JsonObject(); pos.addProperty("x",player.getX());pos.addProperty("y",player.getY());pos.addProperty("z",player.getZ());
                ev.add("position",pos); ev.addProperty("dimension",player.getWorld().getRegistryKey().getValue().toString());
                ev.addProperty("after_block", Registries.BLOCK.getId(serverWorld.getBlockState(captured).getBlock()).toString());
                ev.add("inventory_after", inventory(player.getInventory()));
                ev.addProperty("mined", player.getStatHandler().getStat(Stats.MINED.getOrCreateStat(capturedBlock)));
                result.complete(ev);
            } catch (Exception e) { result.completeExceptionally(e); }
        });
        return result;
    }

    private static JsonObject inventory(net.minecraft.entity.player.PlayerInventory inv) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < inv.size(); i++) {
            ItemStack stack = inv.getStack(i); if (stack.isEmpty()) continue;
            String id = Registries.ITEM.getId(stack.getItem()).toString();
            result.addProperty(id, stack.getCount() + (result.has(id) ? result.get(id).getAsInt() : 0));
        }
        return result;
    }

    private static JsonObject position(BlockPos p) {
        JsonObject o = new JsonObject(); o.addProperty("x", p.getX()); o.addProperty("y", p.getY()); o.addProperty("z", p.getZ()); return o;
    }

    private void finish(String outcome, String reason, JsonObject evidence) {
        if (command == null) return;
        navigator.release();
        mc.options.attackKey.setPressed(false);
        mc.options.useKey.setPressed(false);
        if (mc.interactionManager != null) mc.interactionManager.cancelBlockBreaking();
        crafting.cancel();
        evidence.add("target", position(target));
        JsonObject r = new JsonObject(); r.add("id", command.get("id")); r.addProperty("status", outcome);
        r.addProperty("reason", reason); r.add("evidence", evidence); results.add(r);
        LOG.info("MineLife action={} status={} reason={}", command.get("action").getAsString(), outcome, reason);
        command = null; sensorTick = -100; status = active ? "Observando" : status;
        if (results.size() > 60) stop("Fila cheia · F8", true);
    }
}
