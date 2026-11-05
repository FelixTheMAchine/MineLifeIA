package ai.minelife;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.UUID;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.MinecraftClient;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.entity.player.PlayerEntity;

/** Optional, pinned getters run exclusively on the integrated server thread. */
final class PhysiologyAdapter {
    private record Scope(String session, String world, String dimension, long epoch, UUID player,
                         MinecraftServer server, long generation) {}
    private final PhysiologyCache<Scope,JsonObject> cache=new PhysiologyCache<>();
    private MinecraftServer pendingServer;
    private long generation;

    void reset() { generation++; cache.invalidate(); }

    JsonObject observation(MinecraftClient mc, String session, String world, String dimension, long epoch) {
        // Server shutdown may discard a queued callback. Retire it only after
        // its executor thread ends; a slow running read still owns the slot.
        if(pendingServer!=null && !pendingServer.getThread().isAlive()) {
            cache.retireStoppedExecutor(); pendingServer=null;
        }
        MinecraftServer server=mc.getServer();
        if(server==null || mc.player==null || !server.getThread().isAlive()) { reset(); return null; }
        Scope scope=new Scope(session,world,dimension,epoch,mc.player.getUuid(),server,generation);
        var cached=cache.get(scope,System.nanoTime());
        var next=cache.begin(scope);
        if(next!=null) {
            pendingServer=server;
            try {
                server.execute(() -> {
                    try { next.complete(read(scope)); }
                    catch(Exception | LinkageError e) { next.complete(null); }
                });
            } catch(RuntimeException e) { next.complete(null); }
        }
        if(cached==null) return null;
        long age=System.nanoTime()-cached.nanoTime();
        if(age<0 || age>PhysiologyCache.MAX_AGE_NS) return null;
        JsonObject result=cached.value().deepCopy();
        result.addProperty("sample_age_ms",age/1_000_000L);
        return result;
    }

    private PhysiologyCache.Sample<JsonObject> read(Scope s) {
        long sampledAt=System.nanoTime();
        ServerPlayerEntity player=s.server.getPlayerManager().getPlayer(s.player);
        if(player==null || !player.getWorld().getRegistryKey().getValue().toString().equals(s.dimension)) return null;
        JsonObject result=new JsonObject();
        result.addProperty("version",1); result.addProperty("source","integrated_server");
        result.addProperty("session",s.session); result.addProperty("world",s.world);
        result.addProperty("dimension",s.dimension); result.addProperty("control_epoch",s.epoch);
        result.addProperty("player_uuid",s.player.toString()); result.addProperty("server_tick",player.getServerWorld().getTime());
        result.add("thirst",thirst(player));
        result.add("temperature",temperature(player));
        return new PhysiologyCache.Sample<>(result,sampledAt);
    }

    private static JsonObject sensor(String mod, String version, String api) {
        JsonObject result=new JsonObject();
        var container=FabricLoader.getInstance().getModContainer(mod);
        String installed=container.map(c -> c.getMetadata().getVersion().getFriendlyString()).orElse(null);
        result.addProperty("status",installed==null?"not_installed":installed.equals(version)?"unknown":"unsupported");
        result.add("mod_version",installed==null?JsonNull.INSTANCE:new com.google.gson.JsonPrimitive(installed));
        result.addProperty("api",api); result.add("data",JsonNull.INSTANCE);
        return result;
    }

    private static JsonObject thirst(ServerPlayerEntity player) {
        JsonObject result=sensor("dehydration","1.4.2","dehydration:ThirstManagerAccess-v1.4.2");
        if(!result.get("status").getAsString().equals("unknown")) return result;
        try {
            Class<?> access=Class.forName("net.dehydration.access.ThirstManagerAccess");
            Object manager=access.getMethod("getThirstManager").invoke(player);
            int level=(Integer)manager.getClass().getMethod("getThirstLevel").invoke(manager);
            boolean enabled=(Boolean)manager.getClass().getMethod("hasThirst").invoke(manager);
            if(level<0 || level>20) return result;
            JsonObject data=new JsonObject(); data.addProperty("level",level); data.addProperty("has_thirst",enabled);
            result.add("data",data); result.addProperty("status","observed");
        } catch(ReflectiveOperationException | RuntimeException | LinkageError e) { /* Unknown, never clamp. */ }
        return result;
    }

    private static JsonObject temperature(ServerPlayerEntity player) {
        JsonObject result=sensor("environmentz","2.2.0","environmentz:EnvironmentzApi-v2.2.0");
        if(!result.get("status").getAsString().equals("unknown")) return result;
        try {
            Class<?> api=Class.forName("net.environmentz.api.EnvironmentzApi");
            int body=(Integer)api.getMethod("getTemperature",PlayerEntity.class).invoke(null,player);
            if(body < -1_000_000 || body > 1_000_000) return result;
            Object thresholds=api.getMethod("getBodyTemperatureThresholds").invoke(null);
            JsonObject limits=new JsonObject(); int previous=Integer.MIN_VALUE;
            for(String name:new String[]{"maxVeryCold","maxCold","minCold","normal","minHot","maxHot","maxVeryHot"}) {
                int value=(Integer)thresholds.getClass().getMethod(name).invoke(thresholds);
                if(value < -1_000_000 || value > 1_000_000 || value<=previous) return result;
                limits.addProperty(name,value); previous=value;
            }
            JsonObject data=new JsonObject(); data.addProperty("body",body); data.addProperty("unit","internal");
            data.add("thresholds",limits);
            data.addProperty("heat_affected",(Boolean)api.getMethod("isHeatAffected",PlayerEntity.class).invoke(null,player));
            data.addProperty("cold_affected",(Boolean)api.getMethod("isColdAffected",PlayerEntity.class).invoke(null,player));
            data.add("ambient",JsonNull.INSTANCE);
            result.add("data",data); result.addProperty("status","observed");
        } catch(ReflectiveOperationException | RuntimeException | LinkageError e) { /* Unknown, never Celsius. */ }
        return result;
    }
}
