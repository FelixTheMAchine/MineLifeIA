package ai.minelife;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.server.network.ServerPlayerEntity;

import java.util.concurrent.CompletableFuture;

/** Consumes an existing food stack with native input; main-inventory items use a reversible SWAP. */
final class EatingController {
    private final MinecraftClient mc;
    private int sourceSlot = -1, hotbarSlot = -1, previousSlot = -1, sourceFoodCount, ticks, sampleCooldown, restoreTicks, emptyTicks;
    private String itemId, displacedId;
    private int displacedCount;
    private boolean needsSwap, swapped, restoring;
    private JsonObject consumedEvidence;
    private CompletableFuture<JsonObject> before, after, restoredSnapshot;
    private ClientPlayerEntity owner;
    private ItemStack sourceStack=ItemStack.EMPTY, displacedStack=ItemStack.EMPTY;

    EatingController(MinecraftClient mc) { this.mc = mc; }

    JsonArray offers() {
        JsonArray values = new JsonArray();
        if (mc.player == null) return values;
        for (int i = 0; i < 36; i++) {
            ItemStack stack = mc.player.getInventory().getStack(i);
            var food = stack.get(DataComponentTypes.FOOD);
            if (stack.isEmpty() || food == null || food.nutrition() <= 0 || food.nutrition()>20) continue;
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
        sourceSlot = requested.get("slot").getAsInt();
        if (sourceSlot < 0 || sourceSlot >= 36) return "invalid_food_slot";
        ItemStack stack = mc.player.getInventory().getStack(sourceSlot);
        var component = stack.get(DataComponentTypes.FOOD);
        itemId = requested.get("id").getAsString();
        if (stack.isEmpty() || component == null || component.nutrition() <= 0
                || !FoodConsumptionEvidence.allowed(itemId)
                || !Registries.ITEM.getId(stack.getItem()).toString().equals(itemId)) return "food_changed";
        owner=mc.player;sourceStack=stack.copy();
        previousSlot = mc.player.getInventory().selectedSlot;
        sourceFoodCount = stack.getCount();
        hotbarSlot = sourceSlot < 9 ? sourceSlot : previousSlot;
        before = snapshot(); ticks = 0; sampleCooldown = 0;
        if (sourceSlot >= 9) {
            ItemStack displaced = mc.player.getInventory().getStack(hotbarSlot);
            displacedStack=displaced.copy();
            displacedId = displaced.isEmpty() ? "" : Registries.ITEM.getId(displaced.getItem()).toString();
            displacedCount = displaced.getCount();
            needsSwap = displaced.isEmpty() || !displacedId.equals(itemId) || displaced.get(DataComponentTypes.FOOD) == null;
            if (needsSwap) clickSwap(sourceSlot, hotbarSlot);
        }
        return null;
    }

    JsonObject tick() {
        if (sourceSlot < 0) return error("eat_not_started");
        if (mc.player!=owner) return error("player_changed");
        if (mc.currentScreen != null || mc.player.currentScreenHandler != mc.player.playerScreenHandler) return error("inventory_changed");
        if (++ticks > 220) return error(restoring ? "inventory_restore_timeout" : "eat_timeout");
        if (needsSwap && !swapped && !restoring) {
            if (++restoreTicks > 40) return error("inventory_swap_timeout");
            ItemStack held = mc.player.getInventory().getStack(hotbarSlot);
            if (!held.isEmpty() && Registries.ITEM.getId(held.getItem()).toString().equals(itemId)) swapped = true;
            else return null;
        }
        if (restoring) return tickRestore();
        ItemStack stack = mc.player.getInventory().getStack(hotbarSlot);
        emptyTicks=stack.isEmpty()?emptyTicks+1:0;
        boolean slotChanged = !stack.isEmpty() && !Registries.ITEM.getId(stack.getItem()).toString().equals(itemId);
        if (slotChanged) return error("food_slot_replaced");
        if (before == null || !before.isDone()) return null;
        if (before.isCompletedExceptionally()) return error("server_evidence_unavailable_before_eating");
        mc.player.getInventory().selectedSlot = hotbarSlot;
        if (stack.isEmpty()) {
            mc.options.useKey.setPressed(false); mc.interactionManager.stopUsingItem(mc.player);
        } else mc.options.useKey.setPressed(true);
        if (++sampleCooldown < 5) return null;
        sampleCooldown = 0;
        if (after == null) after = snapshot();
        if (!after.isDone()) return null;
        if (after.isCompletedExceptionally()) return error("server_evidence_unavailable_after_eating");
        JsonObject ev = after.join(), prior = before.join();
        int oldCount = count(prior.getAsJsonObject("inventory"), itemId);
        int newCount = count(ev.getAsJsonObject("inventory"), itemId);
        FoodConsumptionEvidence.Result proof = FoodConsumptionEvidence.classify(
                prior.get("food").getAsInt(), ev.get("food").getAsInt(), oldCount, newCount);
        if (proof == FoodConsumptionEvidence.Result.VERIFIED) {
            mc.options.useKey.setPressed(false); mc.interactionManager.stopUsingItem(mc.player);
            ev.add("inventory_before", prior.get("inventory").deepCopy());
            ev.add("inventory_after", ev.get("inventory").deepCopy());
            ev.addProperty("food_before", prior.get("food").getAsInt()); ev.addProperty("food_after", ev.get("food").getAsInt());
            ev.remove("inventory"); ev.remove("food"); consumedEvidence = ev;
            if (swapped && !alreadyRestored()) { clickSwap(sourceSlot, hotbarSlot); restoring = true; restoreTicks = 0; return null; }
            return consumedEvidence;
        }
        if (proof == FoodConsumptionEvidence.Result.WRONG_AMOUNT) return error("food_consumption_delta_invalid");
        if (proof == FoodConsumptionEvidence.Result.NO_NUTRITION) return error("food_effect_unverified");
        // The client can consume the last item before a queued server sample catches up.
        if (!FoodConsumptionEvidence.awaitingConfirmation(proof,emptyTicks)) return error("food_disappeared_without_server_consumption");
        after = null;
        return null;
    }

    private JsonObject tickRestore() {
        if (alreadyRestored()) {
            if (restoredSnapshot == null) restoredSnapshot = snapshot();
            if (!restoredSnapshot.isDone()) return null;
            if (restoredSnapshot.isCompletedExceptionally()) return error("server_evidence_unavailable_after_restore");
            JsonObject value = restoredSnapshot.join();
            consumedEvidence.add("inventory_after", value.get("inventory").deepCopy());
            return consumedEvidence;
        }
        if (++restoreTicks > 40) return error("inventory_restore_timeout");
        return null;
    }

    private boolean alreadyRestored() {
        ItemStack source = mc.player.getInventory().getStack(sourceSlot);
        ItemStack hotbar = mc.player.getInventory().getStack(hotbarSlot);
        int consumedCount = sourceFoodCount - 1;
        boolean sourceMatchesFood = consumedCount == 0 ? source.isEmpty() :
                ItemStack.areItemsAndComponentsEqual(source,sourceStack) && source.getCount() == consumedCount;
        boolean hotbarMatches = displacedId.isEmpty() ? hotbar.isEmpty() :
                ItemStack.areItemsAndComponentsEqual(hotbar,displacedStack) && hotbar.getCount() == displacedCount;
        return sourceMatchesFood && hotbarMatches;
    }

    private boolean canReverseSwap() {
        if (mc.player == null || mc.player!=owner || sourceSlot < 9 || hotbarSlot < 0
                || mc.player.currentScreenHandler!=mc.player.playerScreenHandler
                || !mc.player.playerScreenHandler.getCursorStack().isEmpty()) return false;
        ItemStack source = mc.player.getInventory().getStack(sourceSlot);
        ItemStack hotbar = mc.player.getInventory().getStack(hotbarSlot);
        boolean sourceIsDisplaced = displacedId.isEmpty() ? source.isEmpty() :
                ItemStack.areItemsAndComponentsEqual(source,displacedStack) && source.getCount() == displacedCount;
        boolean hotbarIsFoodOrEmpty = hotbar.isEmpty() || ItemStack.areItemsAndComponentsEqual(hotbar,sourceStack)
                && (hotbar.getCount()==sourceFoodCount || hotbar.getCount()==sourceFoodCount-1);
        return sourceIsDisplaced && hotbarIsFoodOrEmpty && !(source.isEmpty() && hotbar.isEmpty());
    }

    private void clickSwap(int inventorySlot, int button) {
        int handlerSlot = inventorySlot < 9 ? inventorySlot + 36 : inventorySlot;
        mc.interactionManager.clickSlot(mc.player.playerScreenHandler.syncId, handlerSlot, button, SlotActionType.SWAP, mc.player);
    }

    private CompletableFuture<JsonObject> snapshot() {
        CompletableFuture<JsonObject> result = new CompletableFuture<>();
        var server = mc.getServer(); var uuid = mc.player.getUuid();
        server.execute(() -> {
            try {
                ServerPlayerEntity player = server.getPlayerManager().getPlayer(uuid);
                if (player == null) throw new IllegalStateException("player_missing");
                JsonObject ev = new JsonObject(); ev.addProperty("server_verified", true);
                ev.addProperty("food", player.getHungerManager().getFoodLevel()); ev.addProperty("health", player.getHealth());
                ev.add("inventory", inventory(player)); result.complete(ev);
            } catch (Exception e) { result.completeExceptionally(e); }
        });
        return result;
    }

    private static JsonObject inventory(ServerPlayerEntity player) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < player.getInventory().size(); i++) {
            ItemStack stack = player.getInventory().getStack(i); if (stack.isEmpty()) continue;
            String id = Registries.ITEM.getId(stack.getItem()).toString(); result.addProperty(id, count(result, id) + stack.getCount());
        }
        return result;
    }

    private static int count(JsonObject inventory, String id) { return inventory.has(id) ? inventory.get(id).getAsInt() : 0; }
    private static JsonObject error(String reason) { JsonObject value = new JsonObject(); value.addProperty("error", reason); return value; }

    void cancel() {
        if (mc.options != null) mc.options.useKey.setPressed(false);
        try {
            // clickSlot predicts the SWAP immediately, even if the next controller tick never runs.
            if (needsSwap && canReverseSwap()) clickSwap(sourceSlot, hotbarSlot);
        } finally {
            if (mc.player != null && mc.player==owner && previousSlot >= 0 && previousSlot <= 8) mc.player.getInventory().selectedSlot = previousSlot;
            sourceSlot = hotbarSlot = previousSlot = -1; sourceFoodCount = 0; itemId = displacedId = null; displacedCount = 0;
            ticks = sampleCooldown = restoreTicks = emptyTicks = 0; needsSwap = swapped = restoring = false;
            consumedEvidence = null; before = after = restoredSnapshot = null;
            try {
                if (mc.interactionManager != null && mc.player != null && mc.player==owner) mc.interactionManager.stopUsingItem(mc.player);
            } finally { owner=null;sourceStack=displacedStack=ItemStack.EMPTY; }
        }
    }
}
