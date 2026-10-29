package ai.minelife;

import com.google.gson.JsonObject;
import net.minecraft.block.BedBlock;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.stat.Stats;
import net.minecraft.util.Hand;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.util.math.Vec3d;

import java.util.concurrent.CompletableFuture;

/** Sleeps only in an observed vanilla bed and reports success from integrated-server statistics/time. */
final class RestController {
    private final MinecraftClient mc;
    private final Navigator navigator;
    private BlockPos bed;
    private CompletableFuture<JsonObject> before, after;
    private final PendingServerRead<JsonObject> confirmation=new PendingServerRead<>();
    private boolean interacted;
    private int ticks, sampleCooldown;

    RestController(MinecraftClient mc, Navigator navigator) { this.mc=mc; this.navigator=navigator; }
    boolean ownsScreen() { return bed!=null && interacted && mc.currentScreen instanceof net.minecraft.client.gui.screen.SleepingChatScreen; }

    String begin(BlockPos target) {
        cancel();
        if (mc.world==null || !(mc.world.getBlockState(target).getBlock() instanceof BedBlock)) return "bed_changed";
        if (mc.world.getRegistryKey()!=net.minecraft.world.World.OVERWORLD) return "bed_not_in_overworld";
        int time=(int)Math.floorMod(mc.world.getTimeOfDay(),24000);
        if (time<12542) return "not_night";
        if (!mc.world.getEntitiesByClass(net.minecraft.entity.mob.HostileEntity.class,
                mc.player.getBoundingBox().expand(8),e->e.isAlive()).isEmpty()) return "threat_near_bed";
        bed=target.toImmutable();
        before=snapshot();
        if (!navigator.plan(bed,false,false)) return "no_safe_path_to_bed";
        return null;
    }

    JsonObject tick() {
        if (bed==null) return error("rest_not_started");
        if (++ticks>240) return error(interacted?"bed_rest_not_confirmed":"bed_approach_timeout");
        if (before==null || !before.isDone()) return null;
        if (before.isCompletedExceptionally()) return error("server_evidence_unavailable_before_rest");
        if (!interacted) {
            int path=navigator.tick();
            if (path<0) return error("path_obstructed_to_bed");
            if (path==0) return null;
            if (!(mc.world.getBlockState(bed).getBlock() instanceof BedBlock)) return error("bed_changed");
            if (!mc.world.getEntitiesByClass(net.minecraft.entity.mob.HostileEntity.class,
                    mc.player.getBoundingBox().expand(8),e->e.isAlive()).isEmpty()) return error("threat_near_bed");
            Vec3d hit=Vec3d.ofCenter(bed);
            var result=mc.interactionManager.interactBlock(mc.player,Hand.MAIN_HAND,
                    new BlockHitResult(hit,Direction.UP,bed,false));
            if (!result.isAccepted()) return error("bed_interaction_rejected");
            interacted=true;
            return null;
        }
        if (++sampleCooldown<10) return null;
        sampleCooldown=0;
        after=confirmation.request(this::snapshot);
        if (!after.isDone()) return null;
        if (after.isCompletedExceptionally()) return error("server_evidence_unavailable_after_rest");
        JsonObject first=before.join(),last=after.join();
        if (RestEvidence.verified(first.get("time").getAsLong(),last.get("time").getAsLong(),
                first.get("sleep_count").getAsInt(),last.get("sleep_count").getAsInt())) {
            last.addProperty("rest_completed",true);
            last.addProperty("time_before",first.get("time").getAsLong());
            last.addProperty("sleep_count_before",first.get("sleep_count").getAsInt());
            last.addProperty("sleep_count_after",last.get("sleep_count").getAsInt());
            return last;
        }
        int time=Math.floorMod(last.get("time").getAsLong(),24000);
        if (time<12000) return error("day_transition_without_sleep_stat");
        after=null;confirmation.clear();
        return null;
    }

    private CompletableFuture<JsonObject> snapshot() {
        CompletableFuture<JsonObject> result=new CompletableFuture<>();
        var server=mc.getServer();var uuid=mc.player.getUuid();var dimension=mc.world.getRegistryKey();
        BlockPos capturedBed=bed.toImmutable();
        server.execute(()->{
            try {
                ServerPlayerEntity player=server.getPlayerManager().getPlayer(uuid);
                var world=server.getWorld(dimension);
                if(player==null||world==null)throw new IllegalStateException("player_or_world_missing");
                JsonObject value=new JsonObject();value.addProperty("server_verified",true);
                value.addProperty("time",world.getTimeOfDay());
                value.addProperty("sleep_count",player.getStatHandler().getStat(Stats.CUSTOM.getOrCreateStat(Stats.SLEEP_IN_BED)));
                value.addProperty("bed_block",Registries.BLOCK.getId(world.getBlockState(capturedBed).getBlock()).toString());
                result.complete(value);
            }catch(Exception e){result.completeExceptionally(e);}
        });
        return result;
    }

    private static JsonObject error(String reason){JsonObject value=new JsonObject();value.addProperty("error",reason);return value;}
    void cancel(){
        try {
            if(bed!=null && interacted && mc.player!=null && mc.player.isSleeping() && mc.getNetworkHandler()!=null)
                mc.getNetworkHandler().sendPacket(new net.minecraft.network.packet.c2s.play.ClientCommandC2SPacket(mc.player,
                        net.minecraft.network.packet.c2s.play.ClientCommandC2SPacket.Mode.STOP_SLEEPING));
        } finally {
            navigator.release();bed=null;before=after=null;confirmation.clear();interacted=false;ticks=sampleCooldown=0;
        }
    }
}
