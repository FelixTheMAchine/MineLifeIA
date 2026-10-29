package ai.minelife;

import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import net.minecraft.client.MinecraftClient;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.server.network.ServerPlayerEntity;

import java.util.concurrent.CompletableFuture;

/** Uses an existing hotbar food item through the normal client use-item input. */
final class EatingController {
    private final MinecraftClient mc;
    private int slot = -1, previousSlot = -1, ticks, sampleCooldown;
    private String itemId;
    private CompletableFuture<JsonObject> before, after;

    EatingController(MinecraftClient mc) { this.mc = mc; }

    JsonArray offers() {
        JsonArray values = new JsonArray();
        if (mc.player == null) return values;
        for (int i = 0; i < 9; i++) {
            ItemStack stack = mc.player.getInventory().getStack(i);
            var food = stack.get(DataComponentTypes.FOOD);
            if (stack.isEmpty() || food == null || food.nutrition() <= 0) continue;
            JsonObject offer = new JsonObject();
            offer.addProperty("id", Registries.ITEM.getId(stack.getItem()).toString());
            offer.addProperty("slot", i); offer.addProperty("count", stack.getCount());
            offer.addProperty("nutrition", food.nutrition()); values.add(offer);
        }
        return values;
    }

    String begin(JsonObject requested) {
        cancel();
        if (mc.currentScreen != null || mc.player.currentScreenHandler != mc.player.playerScreenHandler) return "inventory_busy";
        if (mc.player.getHungerManager().getFoodLevel() >= 20) return "not_hungry";
        int requestedSlot = requested.get("slot").getAsInt();
        if (requestedSlot < 0 || requestedSlot > 8) return "invalid_food_slot";
        ItemStack stack = mc.player.getInventory().getStack(requestedSlot);
        var component = stack.get(DataComponentTypes.FOOD);
        if (stack.isEmpty() || component == null || component.nutrition() <= 0
                || !Registries.ITEM.getId(stack.getItem()).toString().equals(requested.get("id").getAsString())) return "food_changed";
        slot = requestedSlot; itemId = requested.get("id").getAsString(); previousSlot = mc.player.getInventory().selectedSlot;
        before = snapshot(itemId); ticks = 0; sampleCooldown = 0;
        mc.player.getInventory().selectedSlot = slot;
        mc.options.useKey.setPressed(true);
        return null;
    }

    JsonObject tick() {
        if (slot < 0) return error("eat_not_started");
        if (mc.currentScreen != null || mc.player.currentScreenHandler != mc.player.playerScreenHandler) return error("inventory_changed");
        ItemStack stack = mc.player.getInventory().getStack(slot);
        if (stack.isEmpty() || !Registries.ITEM.getId(stack.getItem()).toString().equals(itemId)) return error("food_changed");
        if (++ticks > 180) return error("eat_timeout");
        mc.player.getInventory().selectedSlot = slot;
        mc.options.useKey.setPressed(true);
        if (before == null || !before.isDone()) return null;
        if (before.isCompletedExceptionally()) return error("server_evidence_unavailable");
        if (++sampleCooldown < 5) return null;
        sampleCooldown = 0;
        if (after == null) after = snapshot(itemId);
        if (!after.isDone()) return null;
        if (after.isCompletedExceptionally()) { after = null; return null; }
        JsonObject ev = after.join();
        JsonObject prior = before.join();
        int oldCount = count(prior, itemId), newCount = count(ev, itemId);
        if (newCount < oldCount) {
            mc.options.useKey.setPressed(false);
            mc.interactionManager.stopUsingItem(mc.player);
            if (ev.get("food").getAsInt() <= prior.get("food").getAsInt() || oldCount - newCount != 1)
                return error("food_effect_unverified");
            ev.add("inventory_before", prior.get("inventory").deepCopy());
            ev.add("inventory_after", ev.get("inventory").deepCopy());
            ev.addProperty("food_before", prior.get("food").getAsInt());
            ev.addProperty("food_after", ev.get("food").getAsInt());
            ev.remove("inventory"); ev.remove("food");
            return ev;
        }
        after = null;
        return null;
    }

    private CompletableFuture<JsonObject> snapshot(String id) {
        CompletableFuture<JsonObject> result = new CompletableFuture<>();
        var server = mc.getServer(); var uuid = mc.player.getUuid();
        server.execute(() -> {
            try {
                ServerPlayerEntity player = server.getPlayerManager().getPlayer(uuid);
                if (player == null) throw new IllegalStateException("player_missing");
                JsonObject ev = new JsonObject(); ev.addProperty("server_verified", true);
                ev.addProperty("food", player.getHungerManager().getFoodLevel()); ev.addProperty("health", player.getHealth());
                ev.add("inventory", inventory(player));
                result.complete(ev);
            } catch (Exception e) { result.completeExceptionally(e); }
        });
        return result;
    }

    private static JsonObject inventory(ServerPlayerEntity player) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < player.getInventory().size(); i++) {
            ItemStack stack = player.getInventory().getStack(i); if (stack.isEmpty()) continue;
            String id = Registries.ITEM.getId(stack.getItem()).toString();
            result.addProperty(id, count(result, id) + stack.getCount());
        }
        return result;
    }

    private static int count(JsonObject inventory, String id) { return inventory.has(id) ? inventory.get(id).getAsInt() : 0; }
    private static JsonObject error(String reason) { JsonObject value = new JsonObject(); value.addProperty("error", reason); return value; }

    void cancel() {
        if (mc.options != null) mc.options.useKey.setPressed(false);
        if (mc.player != null && previousSlot >= 0 && previousSlot <= 8) mc.player.getInventory().selectedSlot = previousSlot;
        if (mc.interactionManager != null && mc.player != null) mc.interactionManager.stopUsingItem(mc.player);
        slot = -1; previousSlot = -1; itemId = null; ticks = 0; sampleCooldown = 0; before = null; after = null;
    }
}
