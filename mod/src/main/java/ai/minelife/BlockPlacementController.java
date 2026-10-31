package ai.minelife;

import com.google.gson.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.block.Blocks;
import net.minecraft.block.CropBlock;
import net.minecraft.item.BlockItem;
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
    private String item,output;
    private Direction face=Direction.UP;
    private boolean construction,door,raiseForSupport,planting;
    private int ticks;
    private boolean leased,clicked;
    private CompletableFuture<JsonObject> before,after;
    BlockPlacementController(MinecraftClient mc,Navigator nav){this.mc=mc;this.navigator=nav;lease=new HotbarLease(mc);}
    private boolean clear(BlockPos p) {return clear(p,true);}
    private boolean clear(BlockPos p,boolean checkSight) {
        if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isAir()
                || (!construction||door)&&!mc.world.getBlockState(p.up()).isAir())return false;
        BlockPos below=construction||planting?support:p.down();Direction side=construction?face:Direction.UP;
        var floor=mc.world.getBlockState(below);
        if((planting?!floor.isOf(Blocks.FARMLAND):!floor.isSideSolidFullSquare(mc.world,below,side))||floor.hasBlockEntity()||navigator.hazardous(below))return false;
        for(Direction d:Direction.Type.HORIZONTAL)if(navigator.hazardous(p.offset(d)))return false;
        if(!mc.world.getOtherEntities(null,door?new Box(p).stretch(0,1,0):new Box(p),e->e.isAlive()).isEmpty())return false;
        if(!checkSight)return true;
        Vec3d aim=planting?new Vec3d(below.getX()+.5,below.getY()+.9374,below.getZ()+.5):Vec3d.ofCenter(below).add(Vec3d.of(side.getVector()).multiply(.499));
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
        output=item;
        if(!Set.of("minecraft:crafting_table","minecraft:furnace").contains(item))return "unsupported_place_item";
        target=p.toImmutable();support=InteractionSupport.pos(request.getAsJsonObject("support"));
        if(!support.up().equals(target)||!clear(target))return "placement_obstructed_or_out_of_reach";
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        before=snapshot();return null;
    }
    JsonArray farmland() {
        JsonArray result=new JsonArray();if(mc.player==null||mc.world==null)return result;
        var origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-3,-1,-3),origin.add(3,1,3))) {
            var below=p.down();if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isAir()||!mc.world.getBlockState(below).isOf(Blocks.FARMLAND))continue;
            var hit=InteractionSupport.hit(mc,below,new Vec3d(below.getX()+.5,below.getY()+.9374,below.getZ()+.5),3.5);
            if(hit==null||hit.getSide()!=Direction.UP)continue;
            result.add(InteractionSupport.pos(p));if(result.size()>=12)break;
        }
        return result;
    }
    String beginPlant(BlockPos p,JsonObject request) {
        cancel();item=request.get("item_id").getAsString();
        if(!Set.of("minecraft:wheat_seeds","minecraft:carrot","minecraft:potato","minecraft:beetroot_seeds").contains(item))return "unsupported_seed";
        var seed=Registries.ITEM.get(Identifier.of(item));
        if(!(seed instanceof BlockItem block))return "seed_has_no_plant_block";
        output=Registries.BLOCK.getId(block.getBlock()).toString();
        if(!output.equals(request.get("crop_id").getAsString()))return "seed_crop_mismatch";
        planting=true;target=p.toImmutable();support=p.down();
        if(!clear(p))return "farmland_not_empty_or_reachable";
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        before=snapshot();return null;
    }
    String beginShelter(BlockPos anchor,int index,String material) {
        cancel();
        if(index<0||index>=ShelterBlueprint.CELLS.size())return "invalid_blueprint_step";
        var spec=ShelterBlueprint.CELLS.get(index);
        if(!spec.accepts(material))return "invalid_construction_material";
        construction=true;door=spec.role().equals("door");item=output=material;
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
            Vec3d aim=planting?new Vec3d(support.getX()+.5,support.getY()+.9374,support.getZ()+.5):Vec3d.ofCenter(support).add(Vec3d.of(face.getVector()).multiply(.499));
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
        if(b.get("block").getAsString().equals(output) && used==1 && (!door||b.get("door_valid").getAsBoolean())
                &&(!planting||b.get("soil").getAsString().equals("minecraft:farmland")&&b.get("crop_age").getAsInt()==0)
                && InteractionSupport.count(a.getAsJsonObject("inventory"),item)-InteractionSupport.count(b.getAsJsonObject("inventory"),item)==1) {
            b.addProperty("before_block",a.get("block").getAsString());b.addProperty("after_block",output);
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
            if(player==null||world==null||player.getWorld()!=world||!world.isChunkLoaded(p))throw new IllegalStateException("world_changed");
            JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);
            ev.addProperty("dimension",dimension.getValue().toString());
            ev.addProperty("block",Registries.BLOCK.getId(world.getBlockState(p).getBlock()).toString());
            ev.addProperty("soil",Registries.BLOCK.getId(world.getBlockState(p.down()).getBlock()).toString());
            var state=world.getBlockState(p);ev.addProperty("crop_age",state.getBlock() instanceof CropBlock crop?crop.getAge(state):-1);
            ev.add("inventory",InteractionSupport.inventory(player.getInventory()));
            boolean validDoor=ShelterSurvey.doorValid(world,p);
            ev.addProperty("door_valid",validDoor);ev.addProperty("door_open",validDoor&&world.getBlockState(p).get(net.minecraft.block.DoorBlock.OPEN));
            ev.addProperty("used",player.getStatHandler().getStat(Stats.USED.getOrCreateStat(material)));future.complete(ev);
        }catch(Exception e){future.completeExceptionally(e);}});
        return future;
    }
    private static JsonObject error(String text){JsonObject j=new JsonObject();j.addProperty("error",text);return j;}
    void cancel(){try{lease.release();}finally{navigator.release();target=support=null;item=output=null;before=after=null;ticks=0;leased=clicked=construction=door=raiseForSupport=planting=false;face=Direction.UP;}}
}
