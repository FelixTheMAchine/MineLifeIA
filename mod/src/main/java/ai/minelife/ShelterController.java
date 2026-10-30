package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.DoorBlock;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.util.Hand;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.*;
import net.minecraft.world.RaycastContext;
import net.minecraft.world.World;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Local project actions. Every block/door interaction uses the normal client interaction manager. */
final class ShelterController {
    private enum Phase { CHECK, TO_DOOR, OPEN, MOVE, PLACE, CLOSE, CONFIRM }
    private final MinecraftClient mc;
    private final Navigator nav;
    private final BlockPlacementController placement;
    private ClientPlayerEntity owner;
    private BlockPos anchor;
    private JsonObject request;
    private String action;
    private Phase phase;
    private int ticks,step;
    private boolean doorRequested;
    private CompletableFuture<JsonObject> sample;

    ShelterController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;placement=new BlockPlacementController(mc,nav);}
    JsonArray sites() {
        var result=new JsonArray();
        if(mc.world==null||mc.player==null||mc.world.getRegistryKey()!=World.OVERWORLD||request!=null)return result;
        BlockPos origin=mc.player.getBlockPos();
        for(int[] offset:new int[][]{{0,0},{3,0},{-3,0},{0,3},{0,-3}}) {
            BlockPos p=origin.add(offset[0],0,offset[1]);
            if(!emptySite(p))continue;
            result.add(InteractionSupport.pos(p));if(result.size()==4)break;
        }
        return result;
    }
    private boolean emptySite(BlockPos p) {
        if(!ShelterSurvey.floor(mc.world,p)||!nav.walkable(p.south(2)))return false;
        for(var q:BlockPos.iterate(p.add(-1,0,-1),p.add(1,2,1))) {
            if(!mc.world.isChunkLoaded(q)||!mc.world.getBlockState(q).isAir())return false;
            var sight=mc.world.raycast(new RaycastContext(mc.player.getEyePos(),Vec3d.ofCenter(q),RaycastContext.ShapeType.OUTLINE,RaycastContext.FluidHandling.NONE,mc.player));
            if(sight.getType()!=HitResult.Type.MISS)return false;
        }
        return mc.world.getOtherEntities(mc.player,new Box(p.getX()-1,p.getY(),p.getZ()-1,p.getX()+2,p.getY()+3,p.getZ()+2),e->e.isAlive()).isEmpty();
    }
    String begin(String mode,JsonObject data) {
        cancel();
        if(!Set.of("build_shelter","inspect_shelter","enter_shelter","leave_shelter").contains(mode))return "shelter_action_unknown";
        if(!data.get("blueprint").getAsString().equals(ShelterBlueprint.ID))return "unknown_blueprint";
        UUID.fromString(data.get("project").getAsString());
        anchor=InteractionSupport.pos(data.getAsJsonObject("anchor"));
        if(mc.world.getRegistryKey()!=World.OVERWORLD || mc.player.squaredDistanceTo(Vec3d.ofCenter(anchor))>15*15)return "shelter_outside_local_range";
        if(mode.equals("build_shelter")) {
            if(Math.floorMod(mc.world.getTimeOfDay(),24000)>=12000)return "construction_requires_daylight";
            step=data.get("step").getAsInt();
            if(step<0||step>=ShelterBlueprint.CELLS.size()||!ShelterBlueprint.CELLS.get(step).accepts(data.get("item_id").getAsString()))return "invalid_blueprint_material";
        }
        owner=mc.player;request=data.deepCopy();action=mode;phase=Phase.CHECK;sample=snapshot();return null;
    }
    JsonObject tick() {
        if(request==null||mc.player!=owner)return error("shelter_player_changed");
        if(++ticks>350)return error("shelter_action_timeout");
        if(mc.currentScreen!=null)return error("shelter_interrupted_by_screen");
        if(phase==Phase.CHECK) {
            if(!sample.isDone())return null;
            if(sample.isCompletedExceptionally())return error("shelter_inspection_unavailable");
            JsonObject value=sample.join();
            if(action.equals("inspect_shelter"))return decorate(value);
            if(!value.get("floor_solid").getAsBoolean()||!value.get("interior_clear").getAsBoolean())return error("shelter_interior_or_floor_blocked");
            if(action.equals("enter_shelter")&&!value.get("complete").getAsBoolean())return error("shelter_incomplete");
            if(action.equals("leave_shelter")&&value.get("entrance_clear").getAsBoolean()) {
                if(!nav.plan(destination(),false,true))return error("incomplete_shelter_exit_blocked");
                phase=Phase.MOVE;return null;
            }
            if(action.equals("build_shelter")) {
                if(!mc.player.isOnGround())return null;
                for(int i=0;i<step;i++)if(!ShelterBlueprint.CELLS.get(i).accepts(value.getAsJsonArray("cells").get(i).getAsJsonObject().get("id").getAsString()))return error("construction_prerequisite_missing");
                if(ShelterSurvey.near(mc.player,anchor))return startPlacement();
                if(value.get("door_valid").getAsBoolean()&&!value.get("door_open").getAsBoolean())return routeToDoor();
                if(!nav.plan(anchor,false,true))return error("no_safe_path_to_build_site");
                phase=Phase.MOVE;return null;
            }
            if(ShelterSurvey.near(mc.player,destination())) {phase=Phase.CLOSE;return null;}
            if(action.equals("leave_shelter")) {phase=Phase.OPEN;return null;}
            return routeToDoor();
        }
        if(phase==Phase.TO_DOOR) {
            int result=nav.tick();if(result<0)return error("no_safe_path_to_shelter_door");
            if(result>0)phase=Phase.OPEN;return null;
        }
        if(phase==Phase.OPEN) {
            String failure=setDoor(true);if(failure!=null)return error(failure);
            if(!mc.world.getBlockState(anchor.south()).get(DoorBlock.OPEN))return null;
            doorRequested=false;
            if(!nav.plan(destination(),false,true))return error("door_route_obstructed");
            phase=Phase.MOVE;return null;
        }
        if(phase==Phase.MOVE) {
            int result=nav.tick();if(result<0)return error("shelter_route_changed");
            if(result==0)return null;
            if(action.equals("build_shelter"))return startPlacement();
            phase=Phase.CLOSE;return null;
        }
        if(phase==Phase.PLACE) {
            JsonObject outcome=placement.tick();return outcome==null?null:outcome.has("error")?outcome:decorate(outcome);
        }
        if(phase==Phase.CLOSE) {
            if(action.equals("leave_shelter")&&mc.world.getBlockState(anchor.south()).isAir()&&mc.world.getBlockState(anchor.south().up()).isAir()) {
                sample=snapshot();phase=Phase.CONFIRM;return null;
            }
            String failure=setDoor(false);if(failure!=null)return error(failure);
            if(mc.world.getBlockState(anchor.south()).get(DoorBlock.OPEN))return null;
            sample=snapshot();phase=Phase.CONFIRM;return null;
        }
        if(phase==Phase.CONFIRM) {
            if(!sample.isDone())return null;
            if(sample.isCompletedExceptionally())return error("shelter_confirmation_unavailable");
            var value=sample.join();
            boolean viable=value.get("complete").getAsBoolean() || action.equals("leave_shelter")
                    && value.get("floor_solid").getAsBoolean()&&value.get("interior_clear").getAsBoolean()
                    && (value.get("door_valid").getAsBoolean()||value.get("entrance_clear").getAsBoolean());
            if(viable&&!value.get("door_open").getAsBoolean()
                    && value.get(action.equals("enter_shelter")?"inside":"outside").getAsBoolean())return decorate(value);
            sample=snapshot();return null;
        }
        return null;
    }
    private BlockPos destination(){return action.equals("leave_shelter")?anchor.south(2):anchor;}
    private JsonObject routeToDoor() {
        if(!nav.plan(anchor.south(2),false,true))return error("no_safe_path_to_shelter");
        phase=Phase.TO_DOOR;return null;
    }
    private JsonObject startPlacement() {
        if(!mc.player.isOnGround())return null;
        String error=placement.beginShelter(anchor,step,request.get("item_id").getAsString());
        if(error!=null)return error(error);
        phase=Phase.PLACE;return null;
    }
    private String setDoor(boolean open) {
        BlockPos door=anchor.south();
        if(!ShelterSurvey.doorValid(mc.world,door))return "shelter_door_changed";
        var state=mc.world.getBlockState(door);
        if(state.get(DoorBlock.OPEN)==open)return null;
        if(doorRequested)return null;
        Vec3d aim=state.getOutlineShape(mc.world,door).getBoundingBox().getCenter().add(door.getX(),door.getY(),door.getZ());
        var hit=InteractionSupport.hit(mc,door,aim,3.5);
        if(hit==null)return "shelter_door_out_of_reach";
        nav.release();InteractionSupport.look(mc,aim);
        if(!mc.interactionManager.interactBlock(mc.player,Hand.MAIN_HAND,hit).isAccepted())return "door_interaction_rejected";
        doorRequested=true;return null;
    }
    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=mc.player.getUuid();var dimension=mc.world.getRegistryKey();var site=anchor.toImmutable();
        server.execute(()->{try {
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dimension);
            if(player==null||world==null||player.getWorld()!=world)throw new IllegalStateException("shelter_world_changed");
            future.complete(ShelterSurvey.inspect(world,player,site));
        }catch(Exception e){future.completeExceptionally(e);}});return future;
    }
    private JsonObject decorate(JsonObject value) {
        value.add("project",request.get("project"));value.addProperty("blueprint",ShelterBlueprint.ID);
        value.add("anchor",request.get("anchor"));if(action.equals("build_shelter"))value.addProperty("step",step);return value;
    }
    private static JsonObject error(String reason){var value=new JsonObject();value.addProperty("error",reason);return value;}
    void cancel(){try{placement.cancel();}finally{nav.release();owner=null;request=null;anchor=null;action=null;phase=null;sample=null;ticks=step=0;doorRequested=false;}}
}
