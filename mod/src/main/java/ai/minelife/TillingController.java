package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.Blocks;
import net.minecraft.block.FarmlandBlock;
import net.minecraft.client.MinecraftClient;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.ItemStack;
import net.minecraft.item.HoeItem;
import net.minecraft.registry.Registries;
import net.minecraft.registry.tag.FluidTags;
import net.minecraft.stat.Stats;
import net.minecraft.util.Hand;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.*;
import net.minecraft.world.RaycastContext;
import java.util.concurrent.CompletableFuture;

/** One native hoe interaction on exposed dirt, with observed existing water and server evidence. */
final class TillingController {
    private final MinecraftClient mc;
    private final Navigator nav;
    private final HotbarLease lease;
    private BlockPos target,water;
    private JsonObject offer;
    private boolean leased,clicked;
    private int ticks;
    private CompletableFuture<JsonObject> before,after;
    TillingController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;lease=new HotbarLease(mc);}
    private static boolean plainHoe(ItemStack stack) {
        return stack.getItem() instanceof HoeItem&&!stack.hasEnchantments()&&!stack.contains(DataComponentTypes.UNBREAKABLE);
    }

    private boolean safe(BlockPos p) {
        if(!mc.player.isOnGround()||!mc.world.isChunkLoaded(p)||!mc.world.isChunkLoaded(p.up())
                ||!mc.world.getBlockState(p.up()).isAir()||new Box(p).intersects(mc.player.getBoundingBox()))return false;
        var state=mc.world.getBlockState(p);
        if(!(state.isOf(Blocks.DIRT)||state.isOf(Blocks.GRASS_BLOCK))||state.hasBlockEntity()
                ||!mc.world.getBlockState(p.down()).isSideSolidFullSquare(mc.world,p.down(),Direction.UP))return false;
        for(var d:Direction.values())if(!mc.world.isChunkLoaded(p.offset(d))||nav.hazardous(p.offset(d)))return false;
        if(!mc.world.getOtherEntities(mc.player,new Box(p.up()),e->e.isAlive()).isEmpty())return false;
        var hit=InteractionSupport.hit(mc,p,new Vec3d(p.getX()+.5,p.getY()+.999,p.getZ()+.5),3.5);
        return hit!=null&&hit.getSide()==Direction.UP;
    }
    private boolean observedWater(BlockPos p) {
        if(!mc.world.isChunkLoaded(p)||!mc.world.getFluidState(p).isIn(FluidTags.WATER))return false;
        var hit=mc.world.raycast(new RaycastContext(mc.player.getEyePos(),Vec3d.ofCenter(p),
                RaycastContext.ShapeType.OUTLINE,RaycastContext.FluidHandling.ANY,mc.player));
        return hit.getType()==HitResult.Type.BLOCK&&hit.getBlockPos().equals(p);
    }
    private BlockPos waterNear(BlockPos soil) {
        for(var p:BlockPos.iterate(soil.add(-4,0,-4),soil.add(4,1,4)))if(observedWater(p))return p.toImmutable();
        return null;
    }
    private JsonObject describe(BlockPos p) {
        if(!safe(p))return null;
        BlockPos source=waterNear(p);if(source==null)return null;
        for(int i=0;i<36;i++) {
            var stack=mc.player.getInventory().getStack(i);
            if(!plainHoe(stack)||stack.getMaxDamage()-stack.getDamage()<3)continue;
            JsonObject result=InteractionSupport.pos(p);
            result.addProperty("id",Registries.BLOCK.getId(mc.world.getBlockState(p).getBlock()).toString());
            result.addProperty("tool_id",Registries.ITEM.getId(stack.getItem()).toString());result.addProperty("tool_slot",i);
            result.addProperty("tool_damage",stack.getDamage());result.addProperty("tool_max_damage",stack.getMaxDamage());
            result.add("water",InteractionSupport.pos(source));return result;
        }
        return null;
    }
    JsonArray offers() {
        JsonArray result=new JsonArray();if(mc.player==null||mc.world==null||target!=null||mc.currentScreen!=null)return result;
        var origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-3,-1,-3),origin.add(3,0,3))) {
            var j=describe(p);if(j!=null)result.add(j);if(result.size()>=12)break;
        }
        return result;
    }
    /** Empty existing farmland includes measured moisture, not an assertion of growth. */
    JsonArray farmland() {
        JsonArray result=new JsonArray();if(mc.player==null||mc.world==null)return result;
        var origin=mc.player.getBlockPos();
        for(var p:BlockPos.iterate(origin.add(-3,-1,-3),origin.add(3,1,3))) {
            var soil=p.down();var state=mc.world.getBlockState(soil);
            if(!mc.world.isChunkLoaded(p)||!mc.world.getBlockState(p).isAir()||!state.isOf(Blocks.FARMLAND))continue;
            var hit=InteractionSupport.hit(mc,soil,new Vec3d(soil.getX()+.5,soil.getY()+.9374,soil.getZ()+.5),3.5);
            if(hit==null||hit.getSide()!=Direction.UP)continue;
            var j=InteractionSupport.pos(p);j.addProperty("moisture",state.get(FarmlandBlock.MOISTURE));
            var source=waterNear(soil);if(source!=null)j.add("water",InteractionSupport.pos(source));
            result.add(j);if(result.size()>=12)break;
        }
        return result;
    }
    String begin(BlockPos p,JsonObject request) {
        cancel();if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        JsonObject actual=describe(p);if(actual==null)return "tilling_site_unsafe_or_no_observed_water";
        for(var e:request.entrySet())if(!actual.has(e.getKey())||!actual.get(e.getKey()).equals(e.getValue()))return "tilling_offer_changed";
        offer=actual;target=p.toImmutable();water=InteractionSupport.pos(actual.getAsJsonObject("water"));return null;
    }
    JsonObject tick() {
        if(target==null)return error("tilling_not_started");
        if(++ticks>100)return error("tilling_unconfirmed");
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return error("inventory_changed");
        if(!leased) {
            var stack=mc.player.getInventory().getStack(offer.get("tool_slot").getAsInt());
            if(!plainHoe(stack)||stack.getDamage()!=offer.get("tool_damage").getAsInt()
                    ||stack.getMaxDamage()-stack.getDamage()<3)return error("hoe_changed");
            String failure=lease.acquireTool(offer.get("tool_id").getAsString(),offer.get("tool_slot").getAsInt());
            if(failure!=null)return error(failure);leased=true;return null;
        }
        if(before==null) {
            if(!lease.ready())return null;
            mc.getNetworkHandler().sendPacket(new net.minecraft.network.packet.c2s.play.UpdateSelectedSlotC2SPacket(mc.player.getInventory().selectedSlot));
            before=snapshot();return null;
        }
        if(!before.isDone())return null;if(before.isCompletedExceptionally())return error("server_before_unavailable");
        JsonObject a=before.join();
        if(!a.get("block").equals(offer.get("id"))||!a.get("water_observed").getAsBoolean()
                ||a.get("damage").getAsInt()!=offer.get("tool_damage").getAsInt())return error("server_tilling_baseline_changed");
        if(!clicked) {
            if(!safe(target)||!observedWater(water))return error("tilling_site_changed");
            var aim=new Vec3d(target.getX()+.5,target.getY()+.999,target.getZ()+.5);
            var hit=InteractionSupport.hit(mc,target,aim,3.5);if(hit==null||hit.getSide()!=Direction.UP)return error("tilling_raycast_miss");
            InteractionSupport.look(mc,aim);
            if(!mc.interactionManager.interactBlock(mc.player,Hand.MAIN_HAND,hit).isAccepted())return error("tilling_rejected");
            mc.player.swingHand(Hand.MAIN_HAND);clicked=true;return null;
        }
        if(after==null)after=snapshot();if(!after.isDone())return null;if(after.isCompletedExceptionally())return error("server_after_unavailable");
        JsonObject b=after.join();int used=b.get("used").getAsInt()-a.get("used").getAsInt();
        if(b.get("block").getAsString().equals("minecraft:farmland")&&used==1&&b.get("damage").getAsInt()==a.get("damage").getAsInt()+1
                &&b.get("water_observed").getAsBoolean()&&a.get("inventory").equals(b.get("inventory"))) {
            b.add("before_block",a.get("block"));b.add("after_block",b.get("block"));b.add("inventory_before",a.get("inventory"));
            b.add("inventory_after",b.get("inventory"));b.addProperty("used_delta",used);b.add("water",InteractionSupport.pos(water));
            b.add("tool_id",offer.get("tool_id"));b.add("tool_damage_before",a.get("damage"));b.add("tool_damage_after",b.get("damage"));return b;
        }
        after=null;return null;
    }
    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=mc.player.getUuid();
        var dimension=mc.world.getRegistryKey();var p=target.toImmutable();var w=water.toImmutable();
        String item=offer.get("tool_id").getAsString();
        server.execute(()->{try {
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dimension);
            if(player==null||world==null||player.getWorld()!=world||!world.isChunkLoaded(p)||!world.isChunkLoaded(w))throw new IllegalStateException("world_changed");
            var tool=player.getMainHandStack();if(!plainHoe(tool)||!Registries.ITEM.getId(tool.getItem()).toString().equals(item))throw new IllegalStateException("hoe_changed");
            JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);ev.addProperty("dimension",dimension.getValue().toString());
            var state=world.getBlockState(p);ev.addProperty("block",Registries.BLOCK.getId(state.getBlock()).toString());
            ev.addProperty("moisture",state.isOf(Blocks.FARMLAND)?state.get(FarmlandBlock.MOISTURE):-1);
            ev.addProperty("water_observed",world.getFluidState(w).isIn(FluidTags.WATER));ev.addProperty("damage",tool.getDamage());
            ev.addProperty("tool_plain",true);
            ev.addProperty("used",player.getStatHandler().getStat(Stats.USED.getOrCreateStat(tool.getItem())));
            ev.add("inventory",InteractionSupport.inventory(player.getInventory()));future.complete(ev);
        }catch(Exception e){future.completeExceptionally(e);}});return future;
    }
    private static JsonObject error(String text){JsonObject j=new JsonObject();j.addProperty("error",text);return j;}
    void cancel(){try{lease.release();}finally{nav.release();target=water=null;offer=null;before=after=null;leased=clicked=false;ticks=0;}}
}
