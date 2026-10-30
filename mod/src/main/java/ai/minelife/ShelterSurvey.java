package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.DoorBlock;
import net.minecraft.block.enums.DoubleBlockHalf;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.registry.Registries;
import net.minecraft.util.math.*;
import net.minecraft.world.World;

/** Read-only inspection of the known project's cells, never a world editor. */
final class ShelterSurvey {
    static boolean floor(World world,BlockPos anchor) {
        for(var p:BlockPos.iterate(anchor.add(-1,-1,-1),anchor.add(1,-1,2))) {
            if(!world.isChunkLoaded(p))return false;
            var state=world.getBlockState(p);
            if(!state.isSideSolidFullSquare(world,p,Direction.UP) || state.hasBlockEntity() || !world.getFluidState(p).isEmpty()
                    || dangerous(world,p))return false;
        }
        return true;
    }
    static boolean dangerous(World world,BlockPos p) {
        for(var q:BlockPos.iterate(p.add(-1,0,-1),p.add(1,1,1))) {
            String id=Registries.BLOCK.getId(world.getBlockState(q).getBlock()).toString();
            if(id.contains("lava")||id.contains("fire")||id.contains("magma")||id.contains("cactus")||id.contains("powder_snow"))return true;
        }
        return false;
    }
    static boolean doorValid(World world,BlockPos p) {
        var a=world.getBlockState(p);var b=world.getBlockState(p.up());
        String id=Registries.BLOCK.getId(a.getBlock()).toString();
        return ShelterBlueprint.material(id,"_door") && a.getBlock() instanceof DoorBlock && b.isOf(a.getBlock())
                && a.get(DoorBlock.HALF)==DoubleBlockHalf.LOWER && b.get(DoorBlock.HALF)==DoubleBlockHalf.UPPER
                && a.get(DoorBlock.FACING)==Direction.SOUTH && b.get(DoorBlock.FACING)==Direction.SOUTH
                && a.get(DoorBlock.HINGE)==b.get(DoorBlock.HINGE) && a.get(DoorBlock.OPEN)==b.get(DoorBlock.OPEN)
                && !a.get(DoorBlock.POWERED) && !b.get(DoorBlock.POWERED);
    }
    static boolean near(PlayerEntity player,BlockPos pos){return player.getPos().squaredDistanceTo(Vec3d.ofBottomCenter(pos))<.36;}
    static JsonObject inspect(World world,PlayerEntity player,BlockPos anchor) {
        for(var p:BlockPos.iterate(anchor.add(-2,-1,-2),anchor.add(2,3,3)))
            if(!world.isChunkLoaded(p))throw new IllegalStateException("shelter_chunk_unloaded");
        var ev=new JsonObject();var cells=new JsonArray();boolean complete=true;
        for(int i=0;i<ShelterBlueprint.CELLS.size();i++) {
            var cell=ShelterBlueprint.CELLS.get(i);var p=cell.target(anchor);
            String id=Registries.BLOCK.getId(world.getBlockState(p).getBlock()).toString();
            var row=new JsonObject();row.addProperty("step",i);row.add("pos",InteractionSupport.pos(p));row.addProperty("id",id);cells.add(row);
            complete &= cell.accepts(id);
        }
        var door=anchor.south();boolean valid=doorValid(world,door);
        boolean open=valid&&world.getBlockState(door).get(DoorBlock.OPEN);
        boolean interior=world.getBlockState(anchor).isAir() && world.getBlockState(anchor.up()).isAir()
                && world.getOtherEntities(player,new Box(anchor).stretch(0,1,0),e->e.isAlive() && !(e instanceof net.minecraft.entity.ItemEntity)).isEmpty();
        boolean ground=floor(world,anchor);
        complete &= valid&&interior&&ground;
        ev.addProperty("server_verified",true);ev.add("cells",cells);ev.addProperty("floor_solid",ground);
        ev.addProperty("interior_clear",interior);ev.addProperty("door_valid",valid);ev.addProperty("door_open",open);
        ev.addProperty("entrance_clear",world.getBlockState(door).isAir()&&world.getBlockState(door.up()).isAir());
        ev.addProperty("complete",complete);ev.addProperty("inside",near(player,anchor));ev.addProperty("outside",near(player,anchor.south(2)));
        var pos=new JsonObject();pos.addProperty("x",player.getX());pos.addProperty("y",player.getY());pos.addProperty("z",player.getZ());ev.add("position",pos);
        return ev;
    }
}
