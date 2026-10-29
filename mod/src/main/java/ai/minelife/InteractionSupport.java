package ai.minelife;

import com.google.gson.JsonObject;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.registry.Registries;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.RaycastContext;
import java.util.*;

final class InteractionSupport {
    static JsonObject pos(BlockPos p) {
        JsonObject j=new JsonObject(); j.addProperty("x",p.getX());j.addProperty("y",p.getY());j.addProperty("z",p.getZ());return j;
    }
    static BlockPos pos(JsonObject j) { return new BlockPos(j.get("x").getAsInt(),j.get("y").getAsInt(),j.get("z").getAsInt()); }
    static int count(JsonObject j,String id) { return j.has(id)?j.get(id).getAsInt():0; }
    static JsonObject inventory(PlayerInventory inv) {
        JsonObject j=new JsonObject();
        for(int i=0;i<36;i++) {
            var stack=inv.getStack(i);if(stack.isEmpty())continue;
            String id=Registries.ITEM.getId(stack.getItem()).toString();j.addProperty(id,count(j,id)+stack.getCount());
        }
        return j;
    }
    static BlockHitResult hit(MinecraftClient mc,BlockPos p,Vec3d aim,double reach) {
        if(mc.player.getEyePos().squaredDistanceTo(aim)>reach*reach)return null;
        var hit=mc.world.raycast(new RaycastContext(mc.player.getEyePos(),aim,RaycastContext.ShapeType.OUTLINE,RaycastContext.FluidHandling.NONE,mc.player));
        return hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(p)?hit:null;
    }
    static void look(MinecraftClient mc,Vec3d aim) {
        var d=aim.subtract(mc.player.getEyePos());
        mc.player.setYaw((float)Math.toDegrees(Math.atan2(-d.x,d.z)));
        mc.player.setPitch((float)-Math.toDegrees(Math.atan2(d.y,Math.sqrt(d.x*d.x+d.z*d.z))));
    }
    static List<BlockPos> tables(MinecraftClient mc) {
        if(mc.player==null||mc.world==null)return List.of();
        var start=mc.player.getBlockPos();List<BlockPos> result=new ArrayList<>();
        for(var p:BlockPos.iterate(start.add(-10,-2,-10),start.add(10,2,10))) {
            if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isOf(Blocks.CRAFTING_TABLE))continue;
            if(hit(mc,p,Vec3d.ofCenter(p),12)!=null)result.add(p.toImmutable());
        }
        result.sort(Comparator.comparingDouble(p->p.getSquaredDistance(start)));
        return result.stream().limit(8).toList();
    }
}
