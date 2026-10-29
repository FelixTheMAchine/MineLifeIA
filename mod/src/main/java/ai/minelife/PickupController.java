package ai.minelife;

import com.google.gson.JsonObject;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.ItemEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.util.math.BlockPos;

import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/** Walks to a sensed drop and accepts success only when inventory and server entity both agree. */
final class PickupController {
    private final MinecraftClient mc;
    private final Navigator navigator;
    private UUID entityId;
    private String itemId;
    private int initialCount, ticks, sampleCooldown;
    private CompletableFuture<JsonObject> before, after;

    PickupController(MinecraftClient mc, Navigator navigator) { this.mc=mc; this.navigator=navigator; }

    String begin(JsonObject item, BlockPos target) {
        cancel();
        try { entityId=UUID.fromString(item.get("entity_id").getAsString()); }
        catch (RuntimeException e) { return "invalid_item_entity"; }
        itemId=item.get("item_id").getAsString(); initialCount=item.get("count").getAsInt();
        var entity=mc.world.getEntitiesByClass(ItemEntity.class,mc.player.getBoundingBox().expand(20),e->e.getUuid().equals(entityId))
                .stream().findFirst().orElse(null);
        if (!(entity instanceof ItemEntity drop) || drop.getStack().isEmpty()
                || !Registries.ITEM.getId(drop.getStack().getItem()).toString().equals(itemId)) return "item_entity_changed";
        if (!canAccept(drop.getStack())) return "inventory_full";
        before=snapshot();
        if (!navigator.plan(target,true)) return "no_safe_path";
        return null;
    }

    JsonObject tick(BlockPos target) {
        if (entityId==null) return error("pickup_not_started");
        if (++ticks>360) return error("pickup_timeout");
        if (before==null || !before.isDone()) return null;
        if (before.isCompletedExceptionally()) return error("server_evidence_unavailable_before_pickup");
        if (!before.join().get("entity_present").getAsBoolean()) return error("item_missing_before_pickup");
        int path=navigator.tick();
        if (path<0) return error("path_obstructed");
        if (++sampleCooldown<5) return null;
        sampleCooldown=0;
        if (after==null) after=snapshot();
        if (!after.isDone()) return null;
        if (after.isCompletedExceptionally()) return error("server_evidence_unavailable_after_pickup");
        JsonObject prior=before.join(), current=after.join();
        int oldCount=count(prior.getAsJsonObject("inventory"),itemId);
        int newCount=count(current.getAsJsonObject("inventory"),itemId);
        int serverCountBefore=prior.get("entity_count").getAsInt();
        boolean entityReduced=!current.get("entity_present").getAsBoolean()
                || current.get("entity_count").getAsInt()<serverCountBefore;
        if (newCount>oldCount && entityReduced) {
            current.add("inventory_before",prior.get("inventory").deepCopy());
            current.add("inventory_after",current.get("inventory").deepCopy());
            current.addProperty("item_id",itemId);current.addProperty("item_delta",newCount-oldCount);
            current.addProperty("entity_id",entityId.toString());current.addProperty("entity_count_before",serverCountBefore);
            current.addProperty("entity_count_after",current.get("entity_count").getAsInt());
            current.addProperty("entity_present_after",current.get("entity_present").getAsBoolean());
            current.addProperty("entity_present_before",prior.get("entity_present").getAsBoolean());
            current.remove("inventory");current.remove("entity_present");current.remove("entity_count");
            return current;
        }
        if (!current.get("entity_present").getAsBoolean()) return error("item_disappeared_without_inventory_increase");
        if (path>0 && ticks>160) return error("item_not_collected");
        after=null;
        return null;
    }

    private CompletableFuture<JsonObject> snapshot() {
        CompletableFuture<JsonObject> result=new CompletableFuture<>();
        var server=mc.getServer();var uuid=mc.player.getUuid();var dimension=mc.world.getRegistryKey();UUID item=entityId;
        String capturedItemId=itemId;
        server.execute(()->{
            try {
                ServerPlayerEntity player=server.getPlayerManager().getPlayer(uuid);
                var world=server.getWorld(dimension);
                if(player==null||world==null)throw new IllegalStateException("player_or_world_missing");
                JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);
                ev.add("inventory",inventory(player));
                var found=world.getEntity(item);
                ev.addProperty("entity_present",found instanceof ItemEntity drop && !drop.getStack().isEmpty()
                        && Registries.ITEM.getId(drop.getStack().getItem()).toString().equals(capturedItemId));
                int count=found instanceof ItemEntity drop && Registries.ITEM.getId(drop.getStack().getItem()).toString().equals(capturedItemId)
                        ?drop.getStack().getCount():0;
                ev.addProperty("entity_count",count);result.complete(ev);
            }catch(Exception e){result.completeExceptionally(e);}
        });
        return result;
    }

    private boolean canAccept(ItemStack incoming) {
        for(int i=0;i<36;i++){
            ItemStack current=mc.player.getInventory().getStack(i);
            if(current.isEmpty() || ItemStack.areItemsAndComponentsEqual(current,incoming)&&current.getCount()<current.getMaxCount())return true;
        }
        return false;
    }

    private static JsonObject inventory(ServerPlayerEntity player){
        JsonObject out=new JsonObject();
        for(int i=0;i<player.getInventory().size();i++){
            ItemStack stack=player.getInventory().getStack(i);if(stack.isEmpty())continue;
            String id=Registries.ITEM.getId(stack.getItem()).toString();out.addProperty(id,count(out,id)+stack.getCount());
        }
        return out;
    }
    private static int count(JsonObject inventory,String id){return inventory.has(id)?inventory.get(id).getAsInt():0;}
    private static JsonObject error(String reason){JsonObject value=new JsonObject();value.addProperty("error",reason);return value;}
    void cancel(){navigator.release();entityId=null;itemId=null;initialCount=ticks=sampleCooldown=0;before=after=null;}
}
