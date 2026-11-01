package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.Blocks;
import net.minecraft.block.ChestBlock;
import net.minecraft.block.enums.ChestType;
import net.minecraft.block.entity.ChestBlockEntity;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.ingame.GenericContainerScreen;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.screen.GenericContainerScreenHandler;
import net.minecraft.screen.ScreenHandlerType;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.Hand;
import net.minecraft.util.math.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Single vanilla chest, exact one-unit PICKUP transfers, server-thread evidence. */
final class StorageController {
    private enum Phase { WALK, OPEN, BASELINE, VERIFY }
    private final MinecraftClient mc;
    private final Navigator nav;
    private ClientPlayerEntity owner;
    private GenericContainerScreenHandler handler;
    private BlockPos station;
    private JsonObject job,expected;
    private String action;
    private Phase phase;
    private int ticks,phaseTicks,cursorSource=-1;
    private boolean safeToClose;
    private CompletableFuture<JsonObject> before,after;
    StorageController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;}
    private boolean single(BlockPos p){return mc.world!=null&&mc.world.isChunkLoaded(p)&&mc.world.getBlockState(p).isOf(Blocks.CHEST)
            &&mc.world.getBlockState(p).get(ChestBlock.CHEST_TYPE)==ChestType.SINGLE;}
    JsonArray stations(){
        var list=new JsonArray();if(mc.player==null||mc.world==null)return list;
        var origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-10,-2,-10),origin.add(10,2,10))){
            if(!single(p)||InteractionSupport.hit(mc,p,Vec3d.ofCenter(p),12)==null)continue;
            var j=InteractionSupport.pos(p);list.add(j);
            if(list.size()>=8)break;
        }
        return list;
    }
    boolean ownsScreen(){return owner!=null&&mc.player==owner&&job!=null&&phase!=Phase.WALK
            &&mc.currentScreen instanceof GenericContainerScreen&&owner.currentScreenHandler instanceof GenericContainerScreenHandler h
            &&h.getType()==ScreenHandlerType.GENERIC_9X3&&(handler==null||h==handler);}
    String begin(String requestedAction,BlockPos p,JsonObject request){
        cancel();
        if(mc.player==null||mc.world==null||mc.getServer()==null)return "storage_singleplayer_required";
        if(!Set.of("storage_inspect","storage_deposit","storage_withdraw").contains(requestedAction))return "storage_action_invalid";
        UUID.fromString(request.get("job_id").getAsString());
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        if(!mc.player.currentScreenHandler.getCursorStack().isEmpty())return "cursor_not_empty";
        if(!single(p)||InteractionSupport.hit(mc,p,Vec3d.ofCenter(p),12)==null)return "single_chest_not_observed";
        if(!requestedAction.equals("storage_inspect")&&(!request.has("baseline")||!request.has("source_slot")||!request.has("destination_slot")||!request.has("item_id")))return "storage_baseline_missing";
        owner=mc.player;station=p.toImmutable();action=requestedAction;job=request.deepCopy();phase=Phase.WALK;
        if(!nav.plan(station,false)){cancel();return "no_safe_storage_path";}return null;
    }
    JsonObject tick(){
        if(job==null)return error("storage_not_started");
        if(mc.player!=owner||mc.world==null)return error("storage_player_changed");
        if(++ticks>300)return error("storage_timeout");phaseTicks++;
        if(!single(station))return error("storage_chest_changed");
        if(phase==Phase.WALK){
            if(mc.currentScreen!=null)return error("external_screen");
            int state=nav.tick();if(state<0)return error("storage_path_obstructed");if(state==0)return null;
            var hit=InteractionSupport.hit(mc,station,Vec3d.ofCenter(station),3.5);if(hit==null)return error("storage_not_reachable");
            InteractionSupport.look(mc,Vec3d.ofCenter(station));phase=Phase.OPEN;phaseTicks=0;
            if(!mc.interactionManager.interactBlock(owner,Hand.MAIN_HAND,hit).isAccepted())return error("storage_open_rejected");return null;
        }
        if(phase==Phase.OPEN){
            if(!ownsScreen())return phaseTicks>40?error("storage_screen_not_opened"):null;
            handler=(GenericContainerScreenHandler)owner.currentScreenHandler;
            if(!handler.getCursorStack().isEmpty())return error("cursor_not_empty");
            before=snapshot();phase=Phase.BASELINE;return null;
        }
        if(!ownsScreen())return error("storage_interface_changed");
        if(!before.isDone())return null;if(before.isCompletedExceptionally())return error("storage_baseline_unavailable");
        var a=before.join();if(!opened(a))return error("server_storage_not_opened");
        // No click has occurred yet, so the authoritative empty cursor also permits
        // closing after a rejected stale baseline or an incompatible destination.
        if(phase==Phase.BASELINE)safeToClose=true;
        if(phase==Phase.BASELINE){
            if(action.equals("storage_inspect")){safeToClose=true;return evidence(a,a);}
            if(!content(a).equals(content(job.getAsJsonObject("baseline"))))return error("storage_baseline_changed");
            // Both server and local view must agree before issuing ordinary GUI clicks.
            if(!a.equals(localSnapshot()))return error("storage_client_not_synced");
            int source=job.get("source_slot").getAsInt(),destination=job.get("destination_slot").getAsInt();
            if(!(action.equals("storage_deposit")?source>=27&&source<63&&destination>=0&&destination<27:
                    source>=0&&source<27&&destination>=27&&destination<63))return error("storage_invalid_direction");
            var from=handler.getSlot(source).getStack();var to=handler.getSlot(destination).getStack();
            String id=job.get("item_id").getAsString();
            if(from.isEmpty()||!allowed(id)||!Registries.ITEM.getId(from.getItem()).toString().equals(id)
                    ||!standard(from)||!standard(to)||!to.isEmpty()&&(!ItemStack.areItemsAndComponentsEqual(from,to)||to.getCount()>=to.getMaxCount())
                    ||!handler.getSlot(source).canTakeItems(owner)||!handler.getSlot(destination).canInsert(from))return error("storage_incompatible_stacks");
            expected=prediction(a,source,destination,id);
            safeToClose=false;
            cursorSource=source;
            mc.interactionManager.clickSlot(handler.syncId,source,0,SlotActionType.PICKUP,owner);
            mc.interactionManager.clickSlot(handler.syncId,destination,1,SlotActionType.PICKUP,owner);
            if(!handler.getCursorStack().isEmpty())mc.interactionManager.clickSlot(handler.syncId,source,0,SlotActionType.PICKUP,owner);
            if(!handler.getCursorStack().isEmpty())return error("storage_cursor_interrupted");
            phase=Phase.VERIFY;phaseTicks=0;return null;
        }
        if(!handler.getCursorStack().isEmpty())return error("storage_cursor_interrupted");
        if(phaseTicks<3)return null;
        if(after==null)after=snapshot();if(!after.isDone())return null;
        if(after.isCompletedExceptionally())return error("storage_result_unavailable");
        var b=after.join();if(!opened(b))return error("storage_server_interface_changed");
        if(expected.equals(b)){safeToClose=true;cursorSource=-1;return evidence(a,b);}
        after=null;return null;
    }
    private static boolean allowed(String id){
        if(Set.of("minecraft:bread","minecraft:baked_potato","minecraft:carrot","minecraft:potato","minecraft:beetroot",
                "minecraft:cooked_beef","minecraft:cooked_porkchop","minecraft:cooked_chicken","minecraft:cooked_mutton",
                "minecraft:cooked_rabbit","minecraft:cooked_cod","minecraft:cooked_salmon",
                "minecraft:wheat_seeds","minecraft:beetroot_seeds","minecraft:wheat").contains(id))return true;
        if(Set.of("minecraft:cobblestone","minecraft:stone","minecraft:dirt","minecraft:sand","minecraft:gravel","minecraft:glass",
                "minecraft:coal","minecraft:charcoal","minecraft:raw_iron","minecraft:iron_ingot","minecraft:stick","minecraft:torch",
                "minecraft:crafting_table","minecraft:furnace","minecraft:chest").contains(id))return true;
        for(String wood:List.of("oak","spruce","birch","jungle","acacia","dark_oak","mangrove","cherry","bamboo","crimson","warped"))
            for(String suffix:List.of("_planks","_door","_log","_stem"))if(id.equals("minecraft:"+wood+suffix))return true;
        return false;
    }
    private static boolean standard(ItemStack stack){return stack.isEmpty()||stack.getComponents().equals(new ItemStack(stack.getItem()).getComponents());}
    private JsonObject stack(ItemStack stack){
        var c=new JsonObject();c.addProperty("id",stack.isEmpty()?"minecraft:air":Registries.ITEM.getId(stack.getItem()).toString());
        c.addProperty("count",stack.getCount());c.addProperty("standard",standard(stack));
        c.addProperty("components",stack.isEmpty()?"":stack.copyWithCount(1).encode(mc.world.getRegistryManager()).toString());return c;
    }
    private static JsonObject content(JsonObject j){var result=j.deepCopy();result.remove("sync_id");return result;}
    private static boolean opened(JsonObject s){return s.get("station_opened").getAsBoolean()&&s.get("cursor_empty").getAsBoolean();}
    private JsonObject base(){var j=new JsonObject();j.add("station",InteractionSupport.pos(station));
        j.addProperty("dimension",mc.world.getRegistryKey().getValue().toString());j.addProperty("sync_id",handler.syncId);return j;}
    private JsonObject localSnapshot(){
        var j=base();j.addProperty("station_opened",ownsScreen());j.addProperty("cursor_empty",handler.getCursorStack().isEmpty());
        j.add("inventory",InteractionSupport.inventory(owner.getInventory()));var player=new JsonArray();var chest=new JsonArray();
        for(int i=0;i<36;i++)player.add(stack(owner.getInventory().getStack(i)));
        for(int i=0;i<27;i++)chest.add(stack(handler.getSlot(i).getStack()));
        j.add("player_slots",player);j.add("slots",chest);return j;
    }
    private CompletableFuture<JsonObject> snapshot(){
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=owner.getUuid();var dim=mc.world.getRegistryKey();
        var p=station.toImmutable();int sync=handler.syncId;var base=base();
        server.execute(()->{try{
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dim);
            if(player==null||world==null||player.getWorld()!=world||!world.isChunkLoaded(p)||!world.getBlockState(p).isOf(Blocks.CHEST)
                    ||world.getBlockState(p).get(ChestBlock.CHEST_TYPE)!=ChestType.SINGLE||!(world.getBlockEntity(p) instanceof ChestBlockEntity chest))throw new IllegalStateException("single_chest_missing");
            var j=base.deepCopy();
            boolean linked=player.currentScreenHandler instanceof GenericContainerScreenHandler h&&h.getType()==ScreenHandlerType.GENERIC_9X3
                    &&h.syncId==sync&&h.getInventory()==chest&&h.getSlot(0).inventory==chest&&h.canUse(player);
            j.addProperty("station_opened",linked);j.addProperty("cursor_empty",player.currentScreenHandler.getCursorStack().isEmpty());
            j.add("inventory",InteractionSupport.inventory(player.getInventory()));var cells=new JsonArray();var inventory=new JsonArray();
            for(int i=0;i<27;i++)cells.add(stack(chest.getStack(i)));for(int i=0;i<36;i++)inventory.add(stack(player.getInventory().getStack(i)));
            j.add("slots",cells);j.add("player_slots",inventory);future.complete(j);
        }catch(Exception e){future.completeExceptionally(e);}});return future;
    }
    private static JsonObject cell(JsonObject j,int slot){return slot<27?j.getAsJsonArray("slots").get(slot).getAsJsonObject():
            j.getAsJsonArray("player_slots").get(slot>=54?slot-54:slot-18).getAsJsonObject();}
    private JsonObject prediction(JsonObject a,int source,int destination,String id){
        var result=a.deepCopy();var from=cell(result,source);var to=cell(result,destination);var original=cell(a,source);
        int count=from.get("count").getAsInt()-1;from.addProperty("count",count);
        if(count==0){from.addProperty("id","minecraft:air");from.addProperty("components","");from.addProperty("standard",true);}
        if(to.get("count").getAsInt()==0){to.addProperty("id",id);to.add("components",original.get("components"));to.addProperty("standard",true);}
        to.addProperty("count",to.get("count").getAsInt()+1);
        var inv=result.getAsJsonObject("inventory");int n=InteractionSupport.count(inv,id)+(action.equals("storage_deposit")?-1:1);
        if(n==0)inv.remove(id);else inv.addProperty(id,n);return result;
    }
    private JsonObject evidence(JsonObject a,JsonObject b){var ev=new JsonObject();ev.addProperty("server_verified",true);ev.add("job_id",job.get("job_id"));ev.add("before",a);ev.add("after",b);return ev;}
    private static JsonObject error(String message){var j=new JsonObject();j.addProperty("error",message);return j;}
    void cancel(){
        try{
            if(owner!=null&&mc.player==owner&&handler!=null&&owner.currentScreenHandler==handler&&cursorSource>=0&&!handler.getCursorStack().isEmpty()){
                var slot=handler.getSlot(cursorSource);var cursor=handler.getCursorStack();var original=slot.getStack();
                if(slot.canInsert(cursor)&&(original.isEmpty()||ItemStack.areItemsAndComponentsEqual(original,cursor)&&original.getCount()+cursor.getCount()<=original.getMaxCount()))
                    mc.interactionManager.clickSlot(handler.syncId,cursorSource,0,SlotActionType.PICKUP,owner);
            }
        }finally{
            // Local cursor emptiness can precede a server rejection. Only an authoritative final
            // snapshot permits automatic close; an uncertain transfer leaves the GUI for recovery.
            try{if(safeToClose&&ownsScreen()&&owner.currentScreenHandler.getCursorStack().isEmpty())owner.closeHandledScreen();}
            finally{nav.release();owner=null;handler=null;station=null;job=expected=null;action=null;phase=null;before=after=null;ticks=phaseTicks=0;cursorSource=-1;safeToClose=false;}
        }
    }
}
