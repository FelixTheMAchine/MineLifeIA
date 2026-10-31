package ai.minelife;

import com.google.gson.*;
import net.minecraft.block.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.registry.tag.BlockTags;
import net.minecraft.stat.Stats;
import net.minecraft.util.Hand;
import net.minecraft.util.math.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Native, one-block surface mining. Never writes world state or advances breaking twice per tick. */
final class MiningController {
    private final MinecraftClient mc;
    private final Navigator nav;
    private final HotbarLease lease;
    private final ToolManager tools;
    private JsonObject offer;
    private BlockPos target;
    private Block original;
    private boolean leased,attacked;
    private int ticks,airTicks;
    private CompletableFuture<JsonObject> before,after;
    MiningController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;lease=new HotbarLease(mc);tools=new ToolManager(mc);}

    static boolean allowed(BlockState state) {
        return state.isOf(Blocks.STONE)||state.isOf(Blocks.COBBLESTONE)||state.isOf(Blocks.COAL_ORE)
                ||state.isOf(Blocks.DIRT)||state.isOf(Blocks.GRASS_BLOCK)||state.isOf(Blocks.SAND)||state.isOf(Blocks.RED_SAND)
                ||state.isOf(Blocks.IRON_ORE)||state.isIn(BlockTags.LOGS)
                && Registries.BLOCK.getId(state.getBlock()).toString().matches("minecraft:(oak|birch|spruce|jungle|acacia|dark_oak|mangrove|cherry)_log");
    }
    private boolean safe(BlockPos p) {
        if(!mc.world.isChunkLoaded(p)||p.getY()<mc.player.getBlockY()||p.getY()>mc.player.getBlockY()+1
                ||new Box(p).intersects(mc.player.getBoundingBox())||!mc.player.isOnGround())return false;
        var state=mc.world.getBlockState(p);
        if(!allowed(state)||state.hasBlockEntity()||!mc.world.getBlockState(p.down()).isSideSolidFullSquare(mc.world,p.down(),Direction.UP))return false;
        // Only an exposed surface block. Never undercut a roof or start a tunnel.
        if(!state.isIn(BlockTags.LOGS)&&!mc.world.getBlockState(p.up()).isAir())return false;
        if(state.isIn(BlockTags.LOGS)) {
            boolean leaves=false;
            for(var leaf:BlockPos.iterate(p.add(-2,0,-2),p.add(2,6,2)))
                if(mc.world.isChunkLoaded(leaf)&&mc.world.getBlockState(leaf).isIn(BlockTags.LEAVES)){leaves=true;break;}
            if(!leaves)return false;
        }
        for(Direction d:Direction.values()) {
            var n=p.offset(d);if(!mc.world.isChunkLoaded(n))return false;
            var b=mc.world.getBlockState(n);
            if(!b.getFluidState().isEmpty()||nav.hazardous(n)||b.getBlock() instanceof FallingBlock
                    ||b.hasBlockEntity()||b.getBlock() instanceof DoorBlock||b.getBlock() instanceof BedBlock
                    ||b.isOf(Blocks.CRAFTING_TABLE))return false;
        }
        return true;
    }
    private JsonObject describe(BlockPos p) {
        if(!safe(p)||InteractionSupport.hit(mc,p,Vec3d.ofCenter(p),10)==null)return null;
        var state=mc.world.getBlockState(p);var selected=tools.choose(state);if(selected==null)return null;
        JsonObject j=InteractionSupport.pos(p);
        j.addProperty("id",Registries.BLOCK.getId(state.getBlock()).toString());
        for(var e:selected.entrySet())j.add(e.getKey(),e.getValue());return j;
    }
    JsonArray offers() {
        JsonArray list=new JsonArray();if(mc.player==null||mc.world==null||offer!=null||mc.currentScreen!=null)return list;
        var origin=mc.player.getBlockPos();List<JsonObject> candidates=new ArrayList<>();
        for(var p:BlockPos.iterate(origin.add(-8,0,-8),origin.add(8,1,8))) {
            var j=describe(p);if(j!=null)candidates.add(j);
        }
        candidates.sort(Comparator.comparingDouble(j->InteractionSupport.pos(j).getSquaredDistance(origin)));
        candidates.stream().limit(16).forEach(list::add);return list;
    }
    String begin(BlockPos p,JsonObject request) {
        cancel();
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return "inventory_busy";
        JsonObject actual=describe(p);
        if(actual==null||!actual.equals(request))return "mining_offer_changed_or_unsafe";
        offer=request.deepCopy();target=p.toImmutable();original=mc.world.getBlockState(p).getBlock();
        if(!nav.plan(target,false))return "no_safe_mining_path";
        return null;
    }
    JsonObject tick() {
        if(offer==null)return error("mining_not_started");
        if(++ticks>350)return error("mining_timeout");
        if(mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler)return error("inventory_changed");
        if(!leased) {
            int moving=nav.tick();if(moving<0)return error("mining_path_obstructed");if(moving==0)return null;
            if(!safe(target)||!mc.world.getBlockState(target).isOf(original))return error("mining_site_changed");
            int slot=offer.get("tool_slot").getAsInt();var tool=mc.player.getInventory().getStack(slot);
            if(!tools.usable(tool,mc.world.getBlockState(target))||tool.getDamage()!=offer.get("tool_damage").getAsInt())return error("tool_changed");
            String failure=tool.isEmpty()?lease.acquireHand(slot):lease.acquireTool(offer.get("tool_id").getAsString(),slot);
            if(failure!=null)return error(failure);leased=true;return null;
        }
        nav.release();
        if(before==null) {
            if(!lease.ready())return null;
            mc.getNetworkHandler().sendPacket(new net.minecraft.network.packet.c2s.play.UpdateSelectedSlotC2SPacket(mc.player.getInventory().selectedSlot));
            before=snapshot();return null;
        }
        if(!before.isDone())return null;
        if(before.isCompletedExceptionally())return error("mining_baseline_unavailable");
        var a=before.join();
        if(!a.get("held_id").getAsString().equals(offer.get("tool_id").getAsString())
                ||a.get("damage").getAsInt()!=offer.get("tool_damage").getAsInt()
                ||!a.get("suitable").getAsBoolean()) {
            if(!attacked&&ticks<100){before=null;return null;}
            return error("server_tool_changed");
        }
        if(!a.get("block").getAsString().equals(offer.get("id").getAsString()))return error("server_block_changed");
        if(mc.world.getBlockState(target).isAir()) {
            mc.options.attackKey.setPressed(false);mc.interactionManager.cancelBlockBreaking();
            if(++airTicks<5)return null;
            if(after==null)after=snapshot();if(!after.isDone())return null;
            if(after.isCompletedExceptionally())return error("mining_result_unavailable");
            var b=after.join();int mined=b.get("mined").getAsInt()-a.get("mined").getAsInt();
            boolean hand=offer.get("tool_id").getAsString().equals("minecraft:air");
            // A native pickup can fill the previously empty selected slot after the block breaks.
            if(b.get("block").getAsString().equals("minecraft:air")&&mined==1
                    &&(hand || b.get("held_id").equals(a.get("held_id"))&&b.get("damage").getAsInt()==a.get("damage").getAsInt()+offer.get("tool_wear").getAsInt())) {
                b.addProperty("before_block",a.get("block").getAsString());b.addProperty("after_block","minecraft:air");
                b.addProperty("mined_delta",mined);b.addProperty("tool_before_damage",a.get("damage").getAsInt());
                b.addProperty("tool_after_damage",hand?0:b.get("damage").getAsInt());b.add("tool_id",a.get("held_id"));
                b.addProperty("tool_suitable",true);b.add("inventory_before",a.get("inventory"));b.add("inventory_after",b.get("inventory"));return b;
            }
            after=null;return null;
        }
        if(!safe(target)||!mc.world.getBlockState(target).isOf(original)||!lease.ready())return error("mining_conditions_changed");
        var hit=InteractionSupport.hit(mc,target,Vec3d.ofCenter(target),3.5);if(hit==null)return error("mining_out_of_reach");
        InteractionSupport.look(mc,Vec3d.ofCenter(target));mc.crosshairTarget=hit;mc.options.attackKey.setPressed(true);
        if(!attacked){mc.interactionManager.attackBlock(target,hit.getSide());mc.player.swingHand(Hand.MAIN_HAND);attacked=true;}
        return null;
    }
    private CompletableFuture<JsonObject> snapshot() {
        var result=new CompletableFuture<JsonObject>();var server=mc.getServer();var uuid=mc.player.getUuid();
        var dim=mc.world.getRegistryKey();var p=target.toImmutable();Block block=original;
        server.execute(()->{try {
            var player=server.getPlayerManager().getPlayer(uuid);var world=server.getWorld(dim);
            if(player==null||world==null||player.getWorld()!=world||!world.isChunkLoaded(p))throw new IllegalStateException("world_changed");
            var held=player.getMainHandStack();var j=new JsonObject();j.addProperty("server_verified",true);
            j.addProperty("block",Registries.BLOCK.getId(world.getBlockState(p).getBlock()).toString());
            j.addProperty("held_id",Registries.ITEM.getId(held.getItem()).toString());j.addProperty("damage",held.getDamage());
            j.addProperty("suitable",!block.getDefaultState().isToolRequired()||held.isSuitableFor(block.getDefaultState()));
            j.addProperty("mined",player.getStatHandler().getStat(Stats.MINED.getOrCreateStat(block)));
            j.add("inventory",InteractionSupport.inventory(player.getInventory()));result.complete(j);
        }catch(Exception e){result.completeExceptionally(e);}});return result;
    }
    private static JsonObject error(String text){var j=new JsonObject();j.addProperty("error",text);return j;}
    void cancel(){try{lease.release();}finally{nav.release();mc.options.attackKey.setPressed(false);if(mc.interactionManager!=null)mc.interactionManager.cancelBlockBreaking();offer=null;target=null;original=null;before=after=null;leased=attacked=false;ticks=airTicks=0;}}
}
