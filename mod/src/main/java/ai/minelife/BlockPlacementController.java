package ai.minelife;

import com.google.gson.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import net.minecraft.stat.Stats;
import net.minecraft.util.Hand;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.*;
import java.util.Set;
import java.util.concurrent.CompletableFuture;

/** Places one existing workstation on a visible, empty, supported cell. No server mutation. */
final class BlockPlacementController {
    private final MinecraftClient mc;
    private final Navigator navigator;
    private final HotbarLease lease;
    private BlockPos target,support;
    private String item;
    private Direction face=Direction.UP;
    private boolean construction,door,raiseForSupport;
    private int ticks;
    private boolean leased,clicked;
    private CompletableFuture<JsonObject> before,after;
    BlockPlacementController(MinecraftClient mc,Navigator nav){this.mc=mc;this.navigator=nav;lease=new HotbarLease(mc);}
    private boolean clear(BlockPos p) {return clear(p,true);}
    private boolean clear(BlockPos p,boolean checkSight) {
        if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isAir()
                || (!construction||door)&&!mc.world.getBlockState(p.up()).isAir())return false;
        BlockPos below=construction?support:p.down();Direction side=construction?face:Direction.UP;
        var floor=mc.world.getBlockState(below);
        if(!floor.isSideSolidFullSquare(mc.world,below,side)||floor.hasBlockEntity()||navigator.hazardous(below))return false;
        for(Direction d:Direction.Type.HORIZONTAL)if(navigator.hazardous(p.offset(d)))return false;
        if(!mc.world.getOtherEntities(null,door?new Box(p).stretch(0,1,0):new Box(p),e->e.isAlive()).isEmpty())return false;
        if(!checkSight)return true;
        Vec3d aim=Vec3d.ofCenter(below).add(Vec3d.of(side.getVector()).multiply(.499));
        var hit=InteractionSupport.hit(mc,below,aim,3.5);
        return hit!=null && hit.getSide()==side;
    }
    JsonArray spots() {
        JsonArray result=new JsonArray();
        if(mc.player==null||mc.world==null||construction)return result;
        BlockPos origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-3,0,-3),origin.add(3,0,3))) {
            if(!clear(p))continue;
            JsonObject j=InteractionSupport.pos(p);j.add("support",InteractionSupport.pos(p.down()));result.add(j);
            if(result.size()>=12)break;
        }
        return result;
    }
    String begin(BlockPos p,JsonObject request) {
        cancel();
        item=request.get("item_id").getAsString();
        if(!Set.of("minecraft:crafting_table","minecraft:furnace").contains(item))return "unsupported_place_item";
        target=p.toImmutable();support=InteractionSupport.pos(request.getAsJsonObject("support"));
        if(!support.up().equals(target)||!clear(target))return "placement_obstructed_or_out_of_reach";
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        before=snapshot();return null;
    }
    String beginShelter(BlockPos anchor,int index,String material) {
        cancel();
        if(index<0||index>=ShelterBlueprint.CELLS.size())return "invalid_blueprint_step";
        var spec=ShelterBlueprint.CELLS.get(index);
        if(!spec.accepts(material))return "invalid_construction_material";
        construction=true;door=spec.role().equals("door");item=material;
        target=spec.target(anchor);support=spec.support(anchor);face=spec.face();
        raiseForSupport=face==Direction.UP && mc.player.getEyeY()<=support.getY()+1.08;
        if(!clear(target,!raiseForSupport))return "construction_cell_not_reachable_or_empty";
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        before=snapshot();return null;
    }
    JsonObject tick() {
        if(target==null)return error("place_not_started");
        if(++ticks>100)return error("placement_unconfirmed");
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return error("inventory_changed");
        if(!before.isDone())return null;
        if(before.isCompletedExceptionally())return error("server_before_unavailable");
        if(!before.join().get("block").getAsString().equals("minecraft:air"))return error("target_not_empty_on_server");
        if(!leased){String failure=lease.acquire(item);if(failure!=null)return error(failure);leased=true;return null;}
        if(!clicked) {
            if(!lease.ready())return null;
            if(raiseForSupport && mc.player.getEyeY()<=support.getY()+1.08) {
                mc.options.jumpKey.setPressed(mc.player.isOnGround());return null;
            }
            mc.options.jumpKey.setPressed(false);
            if(!clear(target))return error("placement_changed");
            Vec3d aim=Vec3d.ofCenter(support).add(Vec3d.of(face.getVector()).multiply(.499));
            var hit=InteractionSupport.hit(mc,support,aim,3.5);
            if(hit==null||hit.getSide()!=face)return error("placement_raycast_miss");
            InteractionSupport.look(mc,aim);
            if(door)mc.player.setYaw(Direction.SOUTH.asRotation());
            var result=mc.interactionManager.interactBlock(mc.player,Hand.MAIN_HAND,hit);
            if(!result.isAccepted())return error("placement_rejected");
            mc.player.swingHand(Hand.MAIN_HAND);clicked=true;return null;
        }
        if(after==null)after=snapshot();
        if(!after.isDone())return null;
        if(after.isCompletedExceptionally())return error("server_after_unavailable");
        JsonObject a=before.join(),b=after.join();
        int used=b.get("used").getAsInt()-a.get("used").getAsInt();
        if(b.get("block").getAsString().equals(item) && used==1 && (!door||b.get("door_valid").getAsBoolean())
                && InteractionSupport.count(a.getAsJsonObject("inventory"),item)-InteractionSupport.count(b.getAsJsonObject("inventory"),item)==1) {
            b.addProperty("before_block",a.get("block").getAsString());b.addProperty("after_block",item);
            b.add("inventory_before",a.get("inventory"));b.add("inventory_after",b.get("inventory"));
            b.addProperty("used_delta",used);b.add("support",InteractionSupport.pos(support));b.addProperty("face",face.asString());return b;
        }
        after=null;return null;
    }
    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=mc.player.getUuid();
        var dimension=mc.world.getRegistryKey();var p=target.toImmutable();var material=Registries.ITEM.get(Identifier.of(item));
        server.execute(()->{try {
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dimension);
            if(player==null||world==null)throw new IllegalStateException("world_missing");
            JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);
            ev.addProperty("block",Registries.BLOCK.getId(world.getBlockState(p).getBlock()).toString());
            ev.add("inventory",InteractionSupport.inventory(player.getInventory()));
            boolean validDoor=ShelterSurvey.doorValid(world,p);
            ev.addProperty("door_valid",validDoor);ev.addProperty("door_open",validDoor&&world.getBlockState(p).get(net.minecraft.block.DoorBlock.OPEN));
            ev.addProperty("used",player.getStatHandler().getStat(Stats.USED.getOrCreateStat(material)));future.complete(ev);
        }catch(Exception e){future.completeExceptionally(e);}});
        return future;
    }
    private static JsonObject error(String text){JsonObject j=new JsonObject();j.addProperty("error",text);return j;}
    void cancel(){try{lease.release();}finally{navigator.release();target=support=null;item=null;before=after=null;ticks=0;leased=clicked=construction=door=raiseForSupport=false;face=Direction.UP;}}
}
