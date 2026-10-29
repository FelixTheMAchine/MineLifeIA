package ai.minelife;

import com.google.gson.*;
import it.unimi.dsi.fastutil.ints.IntArrayList;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.client.gui.screen.ingame.CraftingScreen;
import net.minecraft.recipe.*;
import net.minecraft.registry.Registries;
import net.minecraft.screen.*;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.stat.Stats;
import net.minecraft.util.*;
import net.minecraft.util.math.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Single-batch native recipe-book crafting, with owned GUI, real ingredient allocation and server proof. */
final class CraftingController {
    private enum Phase { NAVIGATE, OPEN, BASELINE, FILL, CONFIRM }
    private final MinecraftClient mc;
    private final Navigator navigator;
    private JsonObject offer;
    private RecipeEntry<?> recipe;
    private ScreenHandler handler;
    private BlockPos station;
    private CompletableFuture<JsonObject> before,after;
    private Phase phase;
    private int waitTicks;
    private boolean touchedGrid;
    private ClientPlayerEntity owner;

    CraftingController(MinecraftClient mc,Navigator navigator){this.mc=mc;this.navigator=navigator;}
    boolean ownsScreen() {
        return mc.player!=null && mc.player==owner && offer!=null && station!=null && phase!=Phase.NAVIGATE
                && mc.currentScreen instanceof CraftingScreen
                && mc.player.currentScreenHandler instanceof CraftingScreenHandler
                && (handler==null||handler==mc.player.currentScreenHandler);
    }

    private boolean allowed(String id) {
        return id.startsWith("minecraft:") && (id.endsWith("_planks") ||
                Set.of("minecraft:stick","minecraft:crafting_table","minecraft:bread","minecraft:torch",
                        "minecraft:furnace","minecraft:chest","minecraft:wooden_pickaxe","minecraft:wooden_axe",
                        "minecraft:wooden_shovel","minecraft:wooden_hoe","minecraft:stone_pickaxe",
                        "minecraft:stone_axe","minecraft:stone_shovel","minecraft:stone_hoe").contains(id));
    }

    private JsonObject describe(RecipeEntry<?> entry,BlockPos table) {
        if(!entry.id().getNamespace().equals("minecraft")||!mc.player.getRecipeBook().contains(entry)
                ||!(entry.value() instanceof CraftingRecipe craft)||!craft.fits(3,3))return null;
        var out=craft.getResult(mc.world.getRegistryManager());
        String output=Registries.ITEM.getId(out.getItem()).toString();
        if(!allowed(output))return null;
        int grid=craft.fits(2,2)?2:3;
        if(grid==3&&table==null)return null;
        RecipeMatcher matcher=new RecipeMatcher();
        for(int i=0;i<36;i++)matcher.addUnenchantedInput(mc.player.getInventory().getStack(i));
        var ids=new IntArrayList();
        if(!matcher.match(craft,ids))return null;
        JsonObject inputs=new JsonObject();
        for(int raw:ids){
            var stack=RecipeMatcher.getStackFromId(raw);if(stack.isEmpty())continue;
            String id=Registries.ITEM.getId(stack.getItem()).toString();
            inputs.addProperty(id,InteractionSupport.count(inputs,id)+1);
        }
        if(inputs.size()==0)return null;
        String first=inputs.keySet().iterator().next();
        JsonObject r=new JsonObject();r.addProperty("id",entry.id().toString());
        r.addProperty("input_id",first);r.addProperty("input_count",inputs.get(first).getAsInt());
        r.add("inputs",inputs);r.addProperty("output_id",output);r.addProperty("output_count",out.getCount());
        r.addProperty("grid",grid);r.add("station",grid==3?InteractionSupport.pos(table):JsonNull.INSTANCE);
        return r;
    }

    JsonArray offers() {
        JsonArray result=new JsonArray();
        if(mc.player==null||mc.world==null||offer!=null||mc.currentScreen!=null)return result;
        var tables=InteractionSupport.tables(mc);BlockPos table=tables.isEmpty()?null:tables.get(0);
        for(var entry:mc.world.getRecipeManager().values().stream().sorted(Comparator.comparing(e->e.id().toString())).toList()){
            var r=describe(entry,table);if(r!=null)result.add(r);
            if(result.size()>=32)break;
        }
        return result;
    }

    String begin(JsonObject requested) {
        cancel();
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        if(!mc.player.currentScreenHandler.getCursorStack().isEmpty())return "cursor_not_empty";
        for(int i=0;i<=4;i++)if(mc.player.playerScreenHandler.getSlot(i).hasStack())return "crafting_grid_not_empty";
        boolean space=false;for(int i=0;i<36;i++)if(mc.player.getInventory().getStack(i).isEmpty())space=true;
        if(!space)return "inventory_full";
        recipe=mc.world.getRecipeManager().get(Identifier.of(requested.get("id").getAsString())).orElse(null);
        if(recipe==null)return "recipe_missing";
        int grid=requested.has("grid")?requested.get("grid").getAsInt():2;
        BlockPos table=grid==3 && requested.has("station") && !requested.get("station").isJsonNull()
                ?InteractionSupport.pos(requested.getAsJsonObject("station")):null;
        if(grid==3 && (table==null || !mc.world.isChunkLoaded(table) || !mc.world.getBlockState(table).isOf(Blocks.CRAFTING_TABLE)
                || InteractionSupport.hit(mc,table,Vec3d.ofCenter(table),12)==null))return "table_not_observed";
        var actual=describe(recipe,table);
        if(actual==null||actual.get("grid").getAsInt()!=grid)return "recipe_not_available";
        JsonObject expectedInputs=new JsonObject();
        if(requested.has("inputs")&&requested.getAsJsonObject("inputs").size()>0)expectedInputs=requested.getAsJsonObject("inputs");
        else expectedInputs.addProperty(requested.get("input_id").getAsString(),requested.get("input_count").getAsInt());
        if(!actual.getAsJsonObject("inputs").equals(expectedInputs)
                ||!actual.get("output_id").equals(requested.get("output_id"))
                ||!actual.get("output_count").equals(requested.get("output_count")))return "recipe_changed";
        offer=actual;station=table;waitTicks=0;owner=mc.player;
        if(grid==3){
            phase=Phase.NAVIGATE;
            if(!navigator.plan(station,false))return "no_safe_path_to_table";
        }else{
            handler=mc.player.playerScreenHandler;before=snapshot();phase=Phase.BASELINE;
        }
        return null;
    }

    JsonObject tick() {
        if(offer==null)return error("craft_not_started");
        if(mc.player!=owner)return error("player_changed");
        if(++waitTicks>300)return error("craft_timeout");
        if(phase==Phase.NAVIGATE){
            if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return error("inventory_changed");
            int state=navigator.tick();
            if(state<0)return error("path_obstructed_to_table");
            if(state==0)return null;
            if(!mc.world.getBlockState(station).isOf(Blocks.CRAFTING_TABLE))return error("table_changed");
            var hit=InteractionSupport.hit(mc,station,Vec3d.ofCenter(station),3.5);
            if(hit==null)return error("table_out_of_reach");
            InteractionSupport.look(mc,Vec3d.ofCenter(station));
            phase=Phase.OPEN;waitTicks=0;
            if(!mc.interactionManager.interactBlock(mc.player,Hand.MAIN_HAND,hit).isAccepted())return error("table_interaction_rejected");
            return null;
        }
        if(phase==Phase.OPEN){
            if(!ownsScreen()){
                if(waitTicks>40)return error("table_screen_not_opened");
                return null;
            }
            handler=mc.player.currentScreenHandler;
            if(!handler.getCursorStack().isEmpty())return error("cursor_not_empty");
            for(int i=0;i<=9;i++)if(handler.getSlot(i).hasStack())return error("crafting_grid_not_empty");
            before=snapshot();phase=Phase.BASELINE;return null;
        }
        if(handler!=mc.player.currentScreenHandler || (station==null?mc.currentScreen!=null:!ownsScreen()))return error("inventory_changed");
        if(phase==Phase.BASELINE && before.isDone()){
            if(before.isCompletedExceptionally())return error("server_before_unavailable");
            if(station!=null&&!before.join().get("station_opened").getAsBoolean())return error("server_table_not_opened");
            mc.interactionManager.clickRecipe(handler.syncId,recipe,false);
            touchedGrid=true;phase=Phase.FILL;waitTicks=0;
        }else if(phase==Phase.FILL){
            var out=handler.getSlot(0).getStack();
            if(!out.isEmpty() && Registries.ITEM.getId(out.getItem()).toString().equals(offer.get("output_id").getAsString())){
                if(out.getCount()!=offer.get("output_count").getAsInt())return error("recipe_output_changed");
                JsonObject ingredients=new JsonObject();
                for(int i=1;i<=(station==null?4:9);i++){
                    var stack=handler.getSlot(i).getStack();if(stack.isEmpty())continue;
                    String id=Registries.ITEM.getId(stack.getItem()).toString();
                    ingredients.addProperty(id,InteractionSupport.count(ingredients,id)+stack.getCount());
                }
                if(!ingredients.equals(offer.get("inputs")))return error("recipe_allocation_changed");
                mc.interactionManager.clickSlot(handler.syncId,0,0,SlotActionType.QUICK_MOVE,mc.player);
                phase=Phase.CONFIRM;waitTicks=0;
            }
        }else if(phase==Phase.CONFIRM && waitTicks>=5){
            if(after==null)after=snapshot();
            if(!after.isDone())return null;
            if(after.isCompletedExceptionally())return error("server_after_unavailable");
            var value=after.join();var prior=before.join();
            int delta=value.get("crafted").getAsInt()-prior.get("crafted").getAsInt();
            boolean consumed=true;
            for(var e:offer.getAsJsonObject("inputs").entrySet())
                consumed &= InteractionSupport.count(prior.getAsJsonObject("inventory_after"),e.getKey())
                        -InteractionSupport.count(value.getAsJsonObject("inventory_after"),e.getKey())==e.getValue().getAsInt();
            String output=offer.get("output_id").getAsString();
            if(delta==offer.get("output_count").getAsInt() && consumed
                    && InteractionSupport.count(value.getAsJsonObject("inventory_after"),output)
                    -InteractionSupport.count(prior.getAsJsonObject("inventory_after"),output)==delta){
                value.add("inventory_before",prior.get("inventory_after"));
                value.addProperty("crafted_delta",delta);value.add("recipe",offer.get("id"));
                value.add("grid",offer.get("grid"));value.add("station",offer.get("station"));
                value.addProperty("station_opened",station==null||prior.get("station_opened").getAsBoolean());
                return value;
            }
            if(delta>offer.get("output_count").getAsInt())return error("unexpected_craft_quantity");
            after=null;
        }
        return null;
    }

    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=mc.player.getUuid();
        var output=Registries.ITEM.get(Identifier.of(offer.get("output_id").getAsString()));
        var dimension=mc.world.getRegistryKey();BlockPos table=station;int sync=handler.syncId;
        server.execute(()->{try{
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dimension);
            if(player==null||world==null)throw new IllegalStateException("player_missing");
            JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);
            ev.add("inventory_after",InteractionSupport.inventory(player.getInventory()));
            ev.addProperty("crafted",player.getStatHandler().getStat(Stats.CRAFTED.getOrCreateStat(output)));
            ev.addProperty("station_opened",table==null || world.getBlockState(table).isOf(Blocks.CRAFTING_TABLE)
                    && player.currentScreenHandler instanceof CraftingScreenHandler && player.currentScreenHandler.syncId==sync
                    && player.currentScreenHandler.canUse(player));
            future.complete(ev);
        }catch(Exception e){future.completeExceptionally(e);}});
        return future;
    }
    private static JsonObject error(String reason){JsonObject j=new JsonObject();j.addProperty("error",reason);return j;}
    void cancel() {
        try {
            if(mc.player!=null && mc.player==owner && ((handler!=null && mc.player.currentScreenHandler==handler && (station!=null||touchedGrid))
                    || ownsScreen())) mc.player.closeHandledScreen();
        }finally{
            navigator.release();offer=null;recipe=null;handler=null;station=null;before=after=null;phase=null;waitTicks=0;touchedGrid=false;owner=null;
        }
    }
}
