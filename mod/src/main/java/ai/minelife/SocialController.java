package ai.minelife;

import com.google.gson.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.entity.Entity;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.entity.passive.VillagerEntity;
import net.minecraft.entity.projectile.ProjectileUtil;
import net.minecraft.registry.Registries;
import net.minecraft.util.Hand;
import net.minecraft.util.math.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Observes real villagers and may open one supported MCA interface. Never selects dialogue or trade. */
final class SocialController {
    private final MinecraftClient mc;
    private final Navigator nav;
    private final HotbarLease handLease;
    private UUID person;
    private String type,action;
    private BlockPos planned;
    private int ticks,replans,sampleDelay,handChecks;
    private boolean attempted,accepted,leased;
    private Screen ownedGui;
    private CompletableFuture<JsonObject> before,after;
    SocialController(MinecraftClient mc,Navigator nav){this.mc=mc;this.nav=nav;handLease=new HotbarLease(mc);}
    private static String type(Entity entity){return Registries.ENTITY_TYPE.getId(entity.getType()).toString();}
    private static boolean allowed(Entity entity) {
        return entity instanceof VillagerEntity&&type(entity).equals("minecraft:villager")||McaSocialAdapter.supportedType(type(entity));
    }
    private boolean safe() {
        return mc.player!=null&&mc.world!=null&&mc.getServer()!=null&&mc.player.isAlive()&&mc.player.getHealth()>8
                &&mc.player.getHungerManager().getFoodLevel()>8&&Math.floorMod(mc.world.getTimeOfDay(),24000)<12000
                &&mc.world.getEntitiesByClass(HostileEntity.class,mc.player.getBoundingBox().expand(12),Entity::isAlive).isEmpty();
    }
    private Entity find() {
        if(mc.player==null||mc.world==null||person==null)return null;
        return mc.world.getOtherEntities(mc.player,mc.player.getBoundingBox().expand(16),
                e->e.getUuid().equals(person)&&e.isAlive()&&type(e).equals(type)&&allowed(e)).stream().findFirst().orElse(null);
    }
    private boolean emptyHands(){return mc.player.getMainHandStack().isEmpty()&&mc.player.getOffHandStack().isEmpty();}
    private int emptyHandSlot() {
        int selected=mc.player.getInventory().selectedSlot;
        if(mc.player.getInventory().getStack(selected).isEmpty())return selected;
        for(int i=0;i<9;i++)if(mc.player.getInventory().getStack(i).isEmpty())return i;
        return -1;
    }
    static String cleanName(String value) {
        StringBuilder clean=new StringBuilder();
        value.codePoints().filter(cp->!Character.isISOControl(cp)).forEach(clean::appendCodePoint);
        String stripped=clean.toString().strip();
        return stripped.substring(0,stripped.offsetByCodePoints(0,Math.min(96,stripped.codePointCount(0,stripped.length()))));
    }
    JsonArray offers() {
        JsonArray result=new JsonArray();if(mc.player==null||mc.world==null||person!=null||mc.currentScreen!=null)return result;
        mc.world.getOtherEntities(mc.player,mc.player.getBoundingBox().expand(12),
                e->e.isAlive()&&allowed(e)&&mc.player.canSee(e)&&mc.player.squaredDistanceTo(e)<=144).stream()
                .sorted(Comparator.comparingDouble(mc.player::squaredDistanceTo)).limit(8).forEach(e->{
                    String name=cleanName(e.getName().getString());if(name.isEmpty())return;
                    JsonObject j=new JsonObject();j.addProperty("person_uuid",e.getUuidAsString());j.addProperty("entity_type",type(e));
                    j.addProperty("name",name);j.addProperty("x",e.getX());j.addProperty("y",e.getY());j.addProperty("z",e.getZ());
                    j.addProperty("can_contact",McaSocialAdapter.canContact(e,type(e))&&mc.player.getOffHandStack().isEmpty()&&emptyHandSlot()>=0);result.add(j);
                });
        return result;
    }
    String begin(String requestedAction,BlockPos target,JsonObject request) {
        cancel();if(!Set.of("social_observe","social_contact").contains(requestedAction))return "unsupported_social_action";
        if(!safe()||mc.currentScreen!=null||mc.player.currentScreenHandler!=mc.player.playerScreenHandler
                ||!mc.player.currentScreenHandler.getCursorStack().isEmpty())return "social_not_safe_or_inventory_busy";
        try{person=UUID.fromString(request.get("person_uuid").getAsString());type=request.get("entity_type").getAsString();}
        catch(RuntimeException e){person=null;return "invalid_social_target";}
        action=requestedAction;Entity entity=find();
        if(entity==null||!mc.player.canSee(entity)||entity.getBlockPos().getSquaredDistance(target)>4)return "social_person_not_observed";
        if(action.equals("social_contact")&&(!McaSocialAdapter.canContact(entity,type)||!mc.player.getOffHandStack().isEmpty()||emptyHandSlot()<0))return "mca_contact_unavailable_or_no_empty_hand_slot";
        planned=entity.getBlockPos().toImmutable();
        if(!nav.plan(planned,true))return "no_safe_social_path";return null;
    }
    boolean ownsScreen(){
        if(!attempted||person==null)return false;
        if(ownedGui==null&&McaSocialAdapter.screenPerson(mc.currentScreen).filter(person::equals).isPresent())ownedGui=mc.currentScreen;
        return ownedGui!=null&&mc.currentScreen==ownedGui&&McaSocialAdapter.screenPerson(ownedGui).filter(person::equals).isPresent();
    }
    JsonObject tick() {
        if(person==null)return error("social_not_started");
        if(++ticks>260)return error("social_timeout");
        if(!safe())return error("social_safety_changed");
        Entity entity=find();if(entity==null)return error("social_person_changed");
        if(mc.currentScreen!=null&&!ownsScreen())return error("social_external_screen");
        if(!attempted&&action.equals("social_contact")&&(!mc.player.getOffHandStack().isEmpty()||leased&&!emptyHands()))return error("social_hands_changed");
        if(before==null) {
            if(entity.getBlockPos().getSquaredDistance(planned)>1) {
                if(++replans>3||!nav.plan(entity.getBlockPos(),true))return error("social_person_moved_or_no_path");
                planned=entity.getBlockPos().toImmutable();
            }
            if(mc.player.squaredDistanceTo(entity)>9||!mc.player.canSee(entity)) {
                int path=nav.tick();if(path<0)return error("social_path_obstructed");
                if(path>0) {
                    if(++replans>3||!nav.plan(entity.getBlockPos(),true))return error("social_no_visible_reach");
                    planned=entity.getBlockPos().toImmutable();
                }
                return null;
            }
            nav.release();
            if(action.equals("social_contact")&&!leased) {
                int slot=emptyHandSlot();if(slot<0)return error("social_no_empty_hand_slot");
                String failure=handLease.acquireHand(slot);if(failure!=null)return error(failure);
                leased=true;
                mc.getNetworkHandler().sendPacket(new net.minecraft.network.packet.c2s.play.UpdateSelectedSlotC2SPacket(mc.player.getInventory().selectedSlot));
                return null;
            }
            before=snapshot();return null;
        }
        if(!before.isDone())return null;if(before.isCompletedExceptionally())return error("social_server_before_unavailable");
        JsonObject a=before.join();
        // Slot selection and the server read are separate network operations.
        // Wait for server air hands before establishing the immutable baseline.
        if(action.equals("social_contact")&&!attempted&&(!a.get("main_hand").getAsString().equals("minecraft:air")||!a.get("off_hand").getAsString().equals("minecraft:air"))) {
            if(++handChecks>20)return error("social_server_empty_hand_unconfirmed");
            before=null;return null;
        }
        if(!validSnapshot(a))return error("social_server_before_changed");
        if(action.equals("social_observe"))return evidence(a,a);
        if(!a.get("interacting_player").isJsonNull())return error("social_person_already_interacting");
        if(!attempted) {
            if(mc.currentScreen!=null||!emptyHands()||!mc.player.canSee(entity)||mc.player.squaredDistanceTo(entity)>9)return error("social_contact_context_changed");
            var aim=entity.getBoundingBox().getCenter();var eye=mc.player.getEyePos();
            var hit=ProjectileUtil.raycast(mc.player,eye,aim,mc.player.getBoundingBox().stretch(aim.subtract(eye)).expand(1),
                    e->e.isAlive()&&e.canHit()&&!e.isSpectator(),eye.squaredDistanceTo(aim)+.01);
            if(hit==null||!hit.getEntity().getUuid().equals(person))return error("social_entity_raycast_miss");
            InteractionSupport.look(mc,aim);attempted=true;
            accepted=mc.interactionManager.interactEntityAtLocation(mc.player,entity,hit,Hand.MAIN_HAND).isAccepted();
            if(!accepted)return error("social_contact_rejected");
            ownsScreen();
            mc.player.swingHand(Hand.MAIN_HAND);return null;
        }
        if(!ownsScreen())return null;
        if(++sampleDelay<3)return null;sampleDelay=0;
        if(after==null)after=snapshot();if(!after.isDone())return null;
        if(after.isCompletedExceptionally())return error("social_server_after_unavailable");
        JsonObject b=after.join();
        if(!validSnapshot(b))return error("social_server_after_changed");
        if(!b.get("inventory").equals(a.get("inventory"))||!b.get("inventory_fingerprint").equals(a.get("inventory_fingerprint")))return error("social_inventory_changed");
        if(b.get("interacting_player").equals(a.get("player_uuid")))return evidence(a,b);
        if(!b.get("interacting_player").isJsonNull())return error("social_person_interacting_with_other_player");
        after=null;return null;
    }
    private boolean validSnapshot(JsonObject snapshot) {
        return snapshot.get("person_uuid").getAsString().equals(person.toString())&&snapshot.get("entity_type").getAsString().equals(type)
                &&snapshot.get("alive").getAsBoolean()&&snapshot.get("visible").getAsBoolean()&&snapshot.get("distance").getAsDouble()<=3.5
                &&(!action.equals("social_contact")||snapshot.get("main_hand").getAsString().equals("minecraft:air")&&snapshot.get("off_hand").getAsString().equals("minecraft:air"));
    }
    private JsonObject evidence(JsonObject a,JsonObject b) {
        JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);ev.addProperty("person_uuid",person.toString());
        ev.addProperty("entity_type",type);ev.add("dimension",b.get("dimension"));ev.add("before",a);ev.add("after",b);
        if(action.equals("social_contact")) {
            if(!ownsScreen())return error("social_gui_changed");
            JsonObject gui=new JsonObject();gui.addProperty("observed",true);gui.addProperty("screen_class",McaSocialAdapter.SCREEN);gui.addProperty("person_uuid",person.toString());
            ev.add("gui",gui);ev.addProperty("interaction_accepted",accepted);ev.addProperty("mca_version",McaSocialAdapter.VERSION);
        }
        return ev;
    }
    private CompletableFuture<JsonObject> snapshot() {
        CompletableFuture<JsonObject> future=new CompletableFuture<>();var server=mc.getServer();var playerId=mc.player.getUuid();
        var dimension=mc.world.getRegistryKey();UUID capturedPerson=person;String capturedType=type;boolean contact=action.equals("social_contact");
        server.execute(()->{try {
            var world=server.getWorld(dimension);var player=server.getPlayerManager().getPlayer(playerId);
            if(world==null||player==null||player.getWorld()!=world)throw new IllegalStateException("social_world_changed");
            Entity entity=world.getEntity(capturedPerson);
            if(entity==null||!entity.isAlive()||!allowed(entity)||!type(entity).equals(capturedType)||!world.isChunkLoaded(entity.getBlockPos()))throw new IllegalStateException("social_person_changed");
            if(Math.floorMod(world.getTimeOfDay(),24000)>=12000||player.getHungerManager().getFoodLevel()<=8||player.getHealth()<=8
                    ||!world.getEntitiesByClass(HostileEntity.class,player.getBoundingBox().expand(12),Entity::isAlive).isEmpty())throw new IllegalStateException("social_server_unsafe");
            JsonObject value=new JsonObject();value.addProperty("person_uuid",capturedPerson.toString());value.addProperty("entity_type",capturedType);
            String name=cleanName(entity.getName().getString());if(name.isEmpty())throw new IllegalStateException("social_name_unavailable");
            value.addProperty("name",name);JsonObject pos=new JsonObject();pos.addProperty("x",entity.getX());pos.addProperty("y",entity.getY());pos.addProperty("z",entity.getZ());value.add("position",pos);
            value.addProperty("dimension",dimension.getValue().toString());value.addProperty("alive",entity.isAlive());value.addProperty("visible",player.canSee(entity));
            value.addProperty("distance",player.distanceTo(entity));value.addProperty("player_uuid",playerId.toString());
            value.add("inventory",InteractionSupport.inventory(player.getInventory()));
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            for(int slot=0;slot<player.getInventory().size();slot++) {
                digest.update((slot+":"+player.getInventory().getStack(slot).encodeAllowEmpty(world.getRegistryManager())+"\n").getBytes(StandardCharsets.UTF_8));
            }
            value.addProperty("inventory_fingerprint",HexFormat.of().formatHex(digest.digest()));
            value.addProperty("main_hand",Registries.ITEM.getId(player.getMainHandStack().getItem()).toString());value.addProperty("off_hand",Registries.ITEM.getId(player.getOffHandStack().getItem()).toString());
            Optional<UUID> interacting=McaSocialAdapter.canContact(entity,capturedType)?McaSocialAdapter.interactingPlayer(entity,capturedType):Optional.empty();
            if(contact&&!McaSocialAdapter.canContact(entity,capturedType))throw new IllegalStateException("social_mca_adapter_unavailable");
            if(interacting.isPresent())value.addProperty("interacting_player",interacting.get().toString());else value.add("interacting_player",JsonNull.INSTANCE);
            future.complete(value);
        }catch(Exception|LinkageError e){future.completeExceptionally(e);}});return future;
    }
    private static JsonObject error(String reason){JsonObject j=new JsonObject();j.addProperty("error",reason);return j;}
    void cancel() {
        try{if(ownedGui!=null&&mc.currentScreen==ownedGui&&person!=null&&McaSocialAdapter.screenPerson(ownedGui).filter(person::equals).isPresent())ownedGui.close();}
        finally{handLease.release();nav.release();person=null;type=action=null;planned=null;ownedGui=null;before=after=null;ticks=replans=sampleDelay=handChecks=0;attempted=accepted=leased=false;}
    }
}
