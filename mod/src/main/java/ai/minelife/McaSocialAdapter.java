package ai.minelife;

import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.entity.Entity;
import net.minecraft.entity.player.PlayerEntity;
import java.lang.reflect.Field;
import java.util.Optional;
import java.util.UUID;

/** Optional MCA integration: version-gated reads only. Native entity interaction stays in the controller. */
final class McaSocialAdapter {
    static final String VERSION="7.7.19+1.21.1";
    static final String SCREEN="net.conczin.mca.client.gui.InteractScreen";
    static boolean supported() {
        return FabricLoader.getInstance().getModContainer("mca")
                .map(mod->VERSION.equals(mod.getMetadata().getVersion().getFriendlyString())).orElse(false);
    }
    static boolean supportedType(String id) {return id.equals("mca:male_villager")||id.equals("mca:female_villager");}
    static boolean canContact(Entity entity,String id) {
        if(!supported()||!supportedType(id))return false;
        try {
            return Class.forName("net.conczin.mca.entity.VillagerEntityMCA",false,entity.getClass().getClassLoader()).isInstance(entity);
        }catch(ReflectiveOperationException|LinkageError e){return false;}
    }
    static Optional<UUID> interactingPlayer(Entity entity,String id) throws ReflectiveOperationException {
        if(!canContact(entity,id))throw new IllegalStateException("unsupported_mca_adapter");
        Object interactions=entity.getClass().getMethod("getInteractions").invoke(entity);
        Object result=interactions.getClass().getMethod("getInteractingPlayer").invoke(interactions);
        if(!(result instanceof Optional<?> value))throw new IllegalStateException("mca_interaction_getter_changed");
        if(value.isEmpty())return Optional.empty();
        if(!(value.get() instanceof PlayerEntity player))throw new IllegalStateException("mca_interaction_player_changed");
        return Optional.of(player.getUuid());
    }
    static Optional<UUID> screenPerson(Object screen) {
        if(!supported()||screen==null||!screen.getClass().getName().equals(SCREEN))return Optional.empty();
        try {
            Field field=screen.getClass().getDeclaredField("villager");
            if(!field.trySetAccessible())return Optional.empty();
            Object person=field.get(screen);
            return person instanceof Entity entity?Optional.of(entity.getUuid()):Optional.empty();
        }catch(ReflectiveOperationException|RuntimeException|LinkageError e){return Optional.empty();}
    }
}
