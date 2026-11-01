package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.*;
import net.minecraft.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.block.entity.FurnaceBlockEntity;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.ingame.FurnaceScreen;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.recipe.SmeltingRecipe;
import net.minecraft.registry.Registries;
import net.minecraft.screen.FurnaceScreenHandler;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.*;
import net.minecraft.util.math.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Native furnace GUI. One input/fuel per load; inspection and retrieval are separate commands. */
final class FurnaceController {
    private enum Phase { WALK, OPEN, BASELINE, INPUT, FUEL, TAKE }
    private final MinecraftClient mc;
    private final Navigator nav;
    private ClientPlayerEntity owner;
    private FurnaceScreenHandler handler;
    private BlockPos station;
    private JsonObject job,recipe;
    private String action;
    private Phase phase;
    private int ticks,phaseTicks,cursorSource=-1;
    private CompletableFuture<JsonObject> before,after;
    FurnaceController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;}
    static boolean allowedOutput(String id){return Set.of("minecraft:baked_potato","minecraft:cooked_beef","minecraft:cooked_porkchop",
            "minecraft:cooked_chicken","minecraft:cooked_mutton","minecraft:cooked_rabbit","minecraft:cooked_cod","minecraft:cooked_salmon","minecraft:iron_ingot").contains(id);}
    static boolean allowedFuel(String id){return id.equals("minecraft:coal")||id.equals("minecraft:charcoal")||ShelterBlueprint.material(id,"_planks");}
    JsonArray offers() {
        var list=new JsonArray();if(mc.player==null||mc.world==null||job!=null||mc.currentScreen!=null)return list;
        var inventory=InteractionSupport.inventory(mc.player.getInventory());var fuels=AbstractFurnaceBlockEntity.createFuelTimeMap();
        for(var entry:mc.world.getRecipeManager().values().stream().sorted(Comparator.comparing(e->e.id().toString())).toList()) {
            if(!(entry.value() instanceof SmeltingRecipe cooking)||!entry.id().getNamespace().equals("minecraft")||!mc.player.getRecipeBook().contains(entry))continue;
            var out=cooking.getResult(mc.world.getRegistryManager());String output=Registries.ITEM.getId(out.getItem()).toString();
            if(!allowedOutput(output)||out.getCount()!=1||cooking.getCookingTime()>200||cooking.getCookingTime()<1)continue;
            String input=null;
            for(int i=0;i<36;i++){var stack=mc.player.getInventory().getStack(i);if(!stack.isEmpty()&&cooking.getIngredients().get(0).test(stack)){input=Registries.ITEM.getId(stack.getItem()).toString();break;}}
            if(input==null||!input.startsWith("minecraft:"))continue;
            final int duration=cooking.getCookingTime();
            var choices=inventory.keySet().stream().filter(id->allowedFuel(id)&&fuels.getOrDefault(Registries.ITEM.get(Identifier.of(id)),0)>=duration)
                    .sorted(Comparator.<String>comparingInt(id->fuels.getOrDefault(Registries.ITEM.get(Identifier.of(id)),0)).thenComparing(id->id)).limit(4).toList();
            if(choices.isEmpty())choices=Collections.singletonList(null);
            for(String fuel:choices) {
            JsonObject r=new JsonObject();r.addProperty("id",entry.id().toString());r.addProperty("input_id",input);r.addProperty("output_id",output);
            r.addProperty("cook_ticks",duration);r.addProperty("fuel_id",fuel);r.addProperty("fuel_ticks",fuel==null?0:fuels.get(Registries.ITEM.get(Identifier.of(fuel))));
            list.add(r);if(list.size()>=16)return list;
            }
        }
        return list;
    }
    JsonArray stations() {
        var list=new JsonArray();if(mc.player==null||mc.world==null)return list;var origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-10,-2,-10),origin.add(10,2,10))) {
            if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isOf(Blocks.FURNACE)||InteractionSupport.hit(mc,p,Vec3d.ofCenter(p),12)==null)continue;
            var j=InteractionSupport.pos(p);j.addProperty("id","minecraft:furnace");j.addProperty("log",false);
            j.addProperty("lit",mc.world.getBlockState(p).get(AbstractFurnaceBlock.LIT));list.add(j);if(list.size()>=8)break;
        }
        return list;
    }
    boolean ownsScreen(){return owner!=null&&mc.player==owner&&job!=null&&phase!=Phase.WALK&&mc.currentScreen instanceof FurnaceScreen
            &&mc.player.currentScreenHandler instanceof FurnaceScreenHandler&&(handler==null||handler==mc.player.currentScreenHandler);}
    String begin(String requestedAction,BlockPos p,JsonObject request) {
        cancel();UUID.fromString(request.get("job_id").getAsString());
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        if(!mc.player.currentScreenHandler.getCursorStack().isEmpty())return "cursor_not_empty";
        if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isOf(Blocks.FURNACE)||InteractionSupport.hit(mc,p,Vec3d.ofCenter(p),12)==null)return "furnace_not_observed";
        JsonObject r=request.getAsJsonObject("recipe");
        var entry=mc.world.getRecipeManager().get(Identifier.of(r.get("id").getAsString())).orElse(null);
        if(entry==null||!(entry.value() instanceof SmeltingRecipe cooking)||!entry.id().getNamespace().equals("minecraft"))return "smelting_recipe_missing";
        var output=cooking.getResult(mc.world.getRegistryManager());
        var input=Registries.ITEM.get(Identifier.of(r.get("input_id").getAsString()));
        String fuel=r.get("fuel_id").isJsonNull()?null:r.get("fuel_id").getAsString();
        if(!allowedOutput(r.get("output_id").getAsString())||output.getCount()!=1
                ||!Registries.ITEM.getId(output.getItem()).toString().equals(r.get("output_id").getAsString())
                ||!cooking.getIngredients().get(0).test(new ItemStack(input))||cooking.getCookingTime()!=r.get("cook_ticks").getAsInt()
                ||fuel!=null&&(!allowedFuel(fuel)||AbstractFurnaceBlockEntity.createFuelTimeMap().getOrDefault(Registries.ITEM.get(Identifier.of(fuel)),0)<cooking.getCookingTime()))return "invalid_smelting_plan";
        action=requestedAction;station=p.toImmutable();job=request.deepCopy();recipe=r.deepCopy();owner=mc.player;phase=Phase.WALK;
        if(!nav.plan(station,false))return "no_safe_furnace_path";return null;
    }
    JsonObject tick() {
        if(job==null)return error("furnace_not_started");
        if(owner!=mc.player)return error("player_changed");
        if(++ticks>300)return error("furnace_action_timeout");phaseTicks++;
        if(phase==Phase.WALK) {
            if(mc.currentScreen!=null)return error("external_screen");int state=nav.tick();
            if(state<0)return error("furnace_path_obstructed");if(state==0)return null;
            var hit=InteractionSupport.hit(mc,station,Vec3d.ofCenter(station),3.5);
            if(hit==null||!mc.world.getBlockState(station).isOf(Blocks.FURNACE))return error("furnace_changed");
            InteractionSupport.look(mc,Vec3d.ofCenter(station));phase=Phase.OPEN;phaseTicks=0;
            if(!mc.interactionManager.interactBlock(owner,Hand.MAIN_HAND,hit).isAccepted())return error("furnace_open_rejected");return null;
        }
        if(phase==Phase.OPEN) {
            if(!ownsScreen())return phaseTicks>40?error("furnace_screen_not_opened"):null;
            handler=(FurnaceScreenHandler)owner.currentScreenHandler;
            if(!handler.getCursorStack().isEmpty())return error("cursor_not_empty");
            before=snapshot();phase=Phase.BASELINE;return null;
        }
        if(!ownsScreen()||!handler.getCursorStack().isEmpty())return error("furnace_interface_changed");
        if(!before.isDone())return null;if(before.isCompletedExceptionally())return error("furnace_baseline_unavailable");
        JsonObject a=before.join();
        if(!a.get("station_opened").getAsBoolean())return error("server_furnace_not_opened");
        if(phase==Phase.BASELINE) {
            if(action.equals("furnace_inspect"))return evidence(a,a);
            if(action.equals("furnace_load")) {
                boolean residual=recipe.get("fuel_id").isJsonNull();
                if(!empty(a))return error("furnace_not_empty");
                if(residual?(!a.get("lit").getAsBoolean()||a.get("burn_remaining").getAsInt()<recipe.get("cook_ticks").getAsInt()+40):a.get("lit").getAsBoolean())return error("furnace_heat_changed");
                if(!hasSpace())return error("inventory_full");
                for(String key:List.of("input_id","fuel_id"))if(!recipe.get(key).isJsonNull()&&InteractionSupport.count(a.getAsJsonObject("inventory"),recipe.get(key).getAsString())<1)return error("furnace_material_missing");
                String failure=moveOne(recipe.get("input_id").getAsString(),0);if(failure!=null)return error(failure);
                phase=Phase.INPUT;phaseTicks=0;return null;
            }
            boolean recover=job.has("recover")&&job.get("recover").getAsBoolean();
            if(!compatible(a)||recover&&a.get("lit").getAsBoolean())return error("furnace_contents_conflict");
            int slot=recover?(count(a,0)>0?0:count(a,1)>0?1:-1):2;
            if(slot<0||count(a,slot)!=1||!hasSpace())return error("furnace_result_unavailable_or_full");
            if(!slotMatches(a,slot))return error("furnace_slot_changed");
            job.addProperty("take_slot",slot);
            mc.interactionManager.clickSlot(handler.syncId,slot,0,SlotActionType.QUICK_MOVE,owner);
            phase=Phase.TAKE;phaseTicks=0;return null;
        }
        if(phaseTicks<3)return null;
        if(after==null)after=snapshot();if(!after.isDone())return null;if(after.isCompletedExceptionally())return error("furnace_result_unavailable");
        JsonObject b=after.join();if(!b.get("station_opened").getAsBoolean())return error("server_interface_changed");
        if(phase==Phase.INPUT) {
            if(recipe.get("fuel_id").isJsonNull()) {
                if(compatible(b)&&count(b,0)+count(b,2)==1&&delta(a,b,recipe.get("input_id").getAsString())==-1)return evidence(a,b);
                after=null;return null;
            }
            if(count(b,0)==1&&id(b,0).equals(recipe.get("input_id").getAsString())&&count(b,1)==0&&count(b,2)==0
                    &&delta(a,b,recipe.get("input_id").getAsString())==-1) {
                String failure=moveOne(recipe.get("fuel_id").getAsString(),1);if(failure!=null)return error(failure);
                phase=Phase.FUEL;phaseTicks=0;after=null;return null;
            }
        }else if(phase==Phase.FUEL) {
            if(compatible(b)&&count(b,0)+count(b,2)==1&&delta(a,b,recipe.get("input_id").getAsString())==-1
                    &&delta(a,b,recipe.get("fuel_id").getAsString())==-1)return evidence(a,b);
        }else if(phase==Phase.TAKE) {
            int slot=job.get("take_slot").getAsInt();
            if(count(b,slot)==0&&delta(a,b,id(a,slot))==1)return evidence(a,b);
        }
        after=null;return null;
    }
    private boolean hasSpace(){for(int i=0;i<36;i++)if(owner.getInventory().getStack(i).isEmpty())return true;return false;}
    private String moveOne(String item,int destination) {
        if(handler.getSlot(destination).hasStack()||!handler.getCursorStack().isEmpty())return "furnace_destination_busy";
        int source=-1;for(int i=3;i<handler.slots.size();i++)if(!handler.getSlot(i).getStack().isEmpty()
                &&Registries.ITEM.getId(handler.getSlot(i).getStack().getItem()).toString().equals(item)){source=i;break;}
        if(source<0)return "furnace_ingredient_missing";
        // Three ordinary clicks form one transfer, all in this tick. Never click outside the GUI.
        cursorSource=source;
        mc.interactionManager.clickSlot(handler.syncId,source,0,SlotActionType.PICKUP,owner);
        mc.interactionManager.clickSlot(handler.syncId,destination,1,SlotActionType.PICKUP,owner);
        if(!handler.getCursorStack().isEmpty())mc.interactionManager.clickSlot(handler.syncId,source,0,SlotActionType.PICKUP,owner);
        if(!handler.getCursorStack().isEmpty())return "cursor_transfer_interrupted";
        cursorSource=-1;return null;
    }
    private boolean slotMatches(JsonObject snapshot,int slot) {
        return count(snapshot,slot)==1&&!(slot==1&&recipe.get("fuel_id").isJsonNull())
                &&id(snapshot,slot).equals(slot==0?recipe.get("input_id").getAsString():slot==1?recipe.get("fuel_id").getAsString():recipe.get("output_id").getAsString());
    }
    private boolean compatible(JsonObject s){for(int i=0;i<3;i++)if(count(s,i)!=0&&!slotMatches(s,i))return false;return count(s,0)+count(s,2)<=1;}
    private static boolean empty(JsonObject s){return count(s,0)+count(s,1)+count(s,2)==0;}
    private static int count(JsonObject s,int slot){return s.getAsJsonArray("slots").get(slot).getAsJsonObject().get("count").getAsInt();}
    private static String id(JsonObject s,int slot){return s.getAsJsonArray("slots").get(slot).getAsJsonObject().get("id").getAsString();}
    private static int delta(JsonObject a,JsonObject b,String item){return InteractionSupport.count(b.getAsJsonObject("inventory"),item)-InteractionSupport.count(a.getAsJsonObject("inventory"),item);}
    private JsonObject evidence(JsonObject a,JsonObject b){var ev=new JsonObject();ev.addProperty("server_verified",true);ev.add("job_id",job.get("job_id"));ev.add("recipe",recipe);ev.add("before",a);ev.add("after",b);if(job.has("take_slot"))ev.add("take_slot",job.get("take_slot"));return ev;}
    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=owner.getUuid();var dim=mc.world.getRegistryKey();
        var p=station.toImmutable();int sync=handler.syncId;
        server.execute(()->{try {
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dim);
            if(player==null||world==null||player.getWorld()!=world||!world.isChunkLoaded(p)||!(world.getBlockEntity(p) instanceof FurnaceBlockEntity furnace))throw new IllegalStateException("furnace_missing");
            var j=new JsonObject();j.add("station",InteractionSupport.pos(p));j.addProperty("dimension",dim.getValue().toString());
            j.addProperty("station_opened",player.currentScreenHandler instanceof FurnaceScreenHandler&&player.currentScreenHandler.syncId==sync
                    &&player.currentScreenHandler.getSlot(0).inventory==furnace&&player.currentScreenHandler.canUse(player));
            j.addProperty("lit",world.getBlockState(p).get(AbstractFurnaceBlock.LIT));j.add("inventory",InteractionSupport.inventory(player.getInventory()));
            // Read the real block entity through its public serialization API; no
            // reflection, access widening, timer writes, or simulated tick progress.
            var nbt=furnace.createNbt(world.getRegistryManager());
            j.addProperty("burn_remaining",Math.max(0,(int)nbt.getShort("BurnTime")));
            j.addProperty("cook_progress",Math.max(0,(int)nbt.getShort("CookTime")));
            var slots=new JsonArray();for(int i=0;i<3;i++){var stack=furnace.getStack(i);var cell=new JsonObject();cell.addProperty("id",Registries.ITEM.getId(stack.getItem()).toString());cell.addProperty("count",stack.getCount());slots.add(cell);}j.add("slots",slots);future.complete(j);
        }catch(Exception e){future.completeExceptionally(e);}});return future;
    }
    private static JsonObject error(String text){var j=new JsonObject();j.addProperty("error",text);return j;}
    void cancel() {
        try {
            if(owner!=null&&mc.player==owner&&handler!=null&&owner.currentScreenHandler==handler&&cursorSource>=3
                    &&!handler.getCursorStack().isEmpty()&&!handler.getSlot(cursorSource).hasStack())
                mc.interactionManager.clickSlot(handler.syncId,cursorSource,0,SlotActionType.PICKUP,owner);
        }finally {
            try{if(ownsScreen())owner.closeHandledScreen();}
            finally{nav.release();owner=null;handler=null;station=null;job=recipe=null;action=null;phase=null;before=after=null;ticks=phaseTicks=0;cursorSource=-1;}
        }
    }
}
