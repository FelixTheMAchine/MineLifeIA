package ai.minelife;

import com.google.gson.JsonObject;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Box;
import net.minecraft.util.math.Vec3d;
import java.util.UUID;

/** Geometry and server snapshot regressions; no client, world or gameplay. */
public final class PickupNavigationTest {
    private static int checks;
    private static void check(boolean condition,String why){checks++;if(!condition)throw new AssertionError(why);}

    public static void main(String[] args) {
        BlockPos target=new BlockPos(2,64,0);
        Vec3d adjacent=new Vec3d(1.5,64,.5);
        Box player=new Box(1.2,64,.2,1.8,65.8,.8);
        Box drop=new Box(2.865,64,.375,3.115,64.25,.625);
        check(!player.expand(1,0,1).intersects(drop),"adjacent cell may be outside vanilla pickup range");
        check(!Navigator.waypointReached(adjacent,target),"pickup must keep walking to the exact cell");

        // Every accepted horizontal endpoint can reach a drop at either edge of its cell.
        for(double dx:new double[]{-.239,0,.239})for(double dz:new double[]{-.239,0,.239}) {
            Vec3d endpoint=new Vec3d(2.5+dx,64,.5+dz);
            check(Navigator.waypointReached(endpoint,target),"center endpoint rejected");
            Box arrived=new Box(endpoint.x-.3,64,endpoint.z-.3,endpoint.x+.3,65.8,endpoint.z+.3).expand(1,0,1);
            for(double x:new double[]{2.001,2.999})for(double z:new double[]{.001,.999}) {
                check(arrived.intersects(new Box(x-.125,64,z-.125,x+.125,64.25,z+.125)),
                      "accepted endpoint cannot collect a cell-edge drop");
            }
        }
        check(!Navigator.waypointReached(new Vec3d(2.01,64,.01),target),"off-center same-cell start needs a waypoint");
        check(!Navigator.waypointReached(new Vec3d(2.5,65,.5),target),"wrong elevation is not arrival");

        Box sweep=Navigator.pickupSweep(player,adjacent,target);
        check(sweep.intersects(new Box(1.9,64,0,2,66,1)),"swept collision must include intervening panel");
        check(!sweep.intersects(new Box(1.9,64,1.1,2,66,1.2)),"clear side obstacle should not block route");
        check(sweep.minY==player.minY&&sweep.maxY==player.maxY,"horizontal approach changes no height");

        UUID entity=UUID.randomUUID();
        String item="minecraft:cobblestone";
        JsonObject partial=PickupController.evaluateSnapshot(snapshot(item,63,8),snapshot(item,64,7),item,entity,true);
        check(!partial.has("error"),"partial pickup must be confirmed even when it fills inventory");
        check(partial.get("item_delta").getAsInt()==1,"partial pickup needs the observed inventory delta");
        check(partial.get("entity_count_after").getAsInt()==7,"remaining drop must stay in the evidence");
        check(partial.get("entity_present_after").getAsBoolean(),"partial pickup must not invent disappearance");
        check(partial.get("entity_id").getAsString().equals(entity.toString()),"pickup evidence must retain entity correlation");
        JsonObject full=PickupController.evaluateSnapshot(snapshot(item,64,8),snapshot(item,64,8),item,entity,true);
        check(full.get("error").getAsString().equals("inventory_full"),"full inventory without pickup must fail");
        JsonObject invalid=PickupController.evaluateSnapshot(snapshot(item,62,8),snapshot(item,64,7),item,entity,true);
        check(invalid.get("error").getAsString().equals("inventory_full"),"inventory gain beyond drop reduction cannot become success");
        check(PickupController.evaluateSnapshot(snapshot(item,63,8),snapshot(item,63,8),item,entity,false)==null,
              "available capacity without evidence must keep waiting");

        JsonObject collectedBeforeObstruction=PickupController.evaluateSnapshot(
                snapshot(item,0,1),snapshot(item,1,0),item,entity,false,"path_obstructed");
        check(!collectedBeforeObstruction.has("error"),"a blocked waypoint must not erase a server-confirmed pickup");
        check(collectedBeforeObstruction.get("item_delta").getAsInt()==1,"obstruction cannot replace inventory evidence");
        JsonObject blocked=PickupController.evaluateSnapshot(
                snapshot(item,0,1),snapshot(item,0,1),item,entity,false,"path_obstructed");
        check(blocked.get("error").getAsString().equals("path_obstructed"),"obstruction without pickup must fail");
        JsonObject disappeared=PickupController.evaluateSnapshot(
                snapshot(item,0,1),snapshot(item,0,0),item,entity,false,"path_obstructed");
        check(disappeared.get("error").getAsString().equals("item_disappeared_without_inventory_increase"),
              "disappearance during obstruction is not collection");
        JsonObject noPath=PickupController.evaluateSnapshot(
                snapshot(item,0,1),snapshot(item,0,1),item,entity,false,"no_safe_path");
        check(noPath.get("error").getAsString().equals("no_safe_path"),"failed replan must retain its error after sampling");
        System.out.println("Pickup navigation and snapshots: "+checks+" assertions passed; not gameplay.");
    }

    private static JsonObject snapshot(String item,int inventoryCount,int entityCount) {
        JsonObject inventory=new JsonObject();inventory.addProperty(item,inventoryCount);
        JsonObject snapshot=new JsonObject();snapshot.add("inventory",inventory);
        snapshot.addProperty("server_verified",true);snapshot.addProperty("entity_changed",false);
        snapshot.addProperty("entity_present",entityCount>0);snapshot.addProperty("entity_count",entityCount);
        return snapshot;
    }
}
