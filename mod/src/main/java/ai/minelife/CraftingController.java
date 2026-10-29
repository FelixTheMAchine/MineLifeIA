package ai.minelife;

import com.google.gson.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.ItemStack;
import net.minecraft.recipe.CraftingRecipe;
import net.minecraft.recipe.RecipeEntry;
import net.minecraft.registry.Registries;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.stat.Stats;
import net.minecraft.util.Identifier;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/** Crafting real via recipe book + quick move; nenhuma criação de stack no servidor. */
final class CraftingController {
    private final MinecraftClient mc;
    private JsonObject offer;
    private RecipeEntry<?> recipe;
    private CompletableFuture<JsonObject> before, after;
    private int phase, waitTicks;
    CraftingController(MinecraftClient mc) { this.mc=mc; }
    boolean ownsScreen() { return false; }

    JsonArray offers() {
        JsonArray result=new JsonArray();
        if (mc.player==null || mc.world==null) return result;
        Set<String> seen=new HashSet<>();
        for (RecipeEntry<?> entry:mc.world.getRecipeManager().values()) {
            if (!entry.id().getNamespace().equals("minecraft") || !mc.player.getRecipeBook().contains(entry)) continue;
            if (!(entry.value() instanceof CraftingRecipe craft) || !craft.fits(2,2)) continue;
            var ingredients=craft.getIngredients().stream().filter(i->!i.isEmpty()).toList();
            if(ingredients.isEmpty() || ingredients.size()>4) continue;
            ItemStack output=craft.getResult(mc.world.getRegistryManager());
            String outputId=Registries.ITEM.getId(output.getItem()).toString();
            if (!outputId.endsWith("_planks") && !Set.of("minecraft:stick","minecraft:crafting_table").contains(outputId)) continue;
            for(int i=0;i<36;i++) {
                ItemStack input=mc.player.getInventory().getStack(i);
                String inputId=Registries.ITEM.getId(input.getItem()).toString();
                if(input.isEmpty() || !(inputId.endsWith("_log") || inputId.endsWith("_planks")) || !ingredients.stream().allMatch(ingredient->ingredient.test(input))) continue;
                int total=0;
                for(int j=0;j<36;j++) if(mc.player.getInventory().getStack(j).isOf(input.getItem())) total+=mc.player.getInventory().getStack(j).getCount();
                if(total<ingredients.size()) continue;
                if(!seen.add(entry.id().toString())) break;
                JsonObject r=new JsonObject(); r.addProperty("id",entry.id().toString()); r.addProperty("input_id",inputId);
                r.addProperty("input_count",ingredients.size());
                r.addProperty("output_id",outputId);r.addProperty("output_count",output.getCount());result.add(r);break;
            }
            if(result.size()>=32) break;
        }
        return result;
    }

    String begin(JsonObject requested) {
        cancel();
        if(mc.currentScreen!=null || mc.player.currentScreenHandler!=mc.player.playerScreenHandler) return "inventory_busy";
        if(!mc.player.currentScreenHandler.getCursorStack().isEmpty()) return "cursor_not_empty";
        for(int i=0;i<=4;i++) if(mc.player.playerScreenHandler.getSlot(i).hasStack()) return "crafting_grid_not_empty";
        boolean space=false;
        for(int i=0;i<36;i++) if(mc.player.getInventory().getStack(i).isEmpty()) space=true;
        if(!space) return "inventory_full";
        for(JsonElement item:offers()) if(item.equals(requested)) {offer=requested.deepCopy();break;}
        if(offer==null) return "recipe_not_available";
        recipe=mc.world.getRecipeManager().get(Identifier.of(offer.get("id").getAsString())).orElse(null);
        if(recipe==null) {cancel();return "recipe_missing";}
        before=snapshot();phase=0;waitTicks=0;return null;
    }

    JsonObject tick() {
        if(offer==null) return error("craft_not_started");
        if(mc.player.currentScreenHandler!=mc.player.playerScreenHandler || mc.currentScreen!=null) return error("inventory_changed");
        if(++waitTicks>160) return error("craft_timeout");
        if(phase==0 && before.isDone()) {
            before.join();
            mc.interactionManager.clickRecipe(mc.player.playerScreenHandler.syncId,recipe,false);
            phase=1;waitTicks=0;
        } else if(phase==1) {
            ItemStack out=mc.player.playerScreenHandler.getSlot(0).getStack();
            if(Registries.ITEM.getId(out.getItem()).toString().equals(offer.get("output_id").getAsString()) && out.getCount()==offer.get("output_count").getAsInt()) {
                mc.interactionManager.clickSlot(mc.player.playerScreenHandler.syncId,0,0,SlotActionType.QUICK_MOVE,mc.player);
                phase=2;waitTicks=0;
            }
        } else if(phase==2 && waitTicks>=10) {
            if(after==null) after=snapshot();
            if(after.isDone()) {
                JsonObject value=after.join();
                int delta=value.get("crafted").getAsInt()-before.join().get("crafted").getAsInt();
                if(delta==offer.get("output_count").getAsInt()) {
                    value.add("inventory_before",before.join().get("inventory_after"));
                    value.addProperty("crafted_delta",delta);value.add("recipe",offer.get("id"));return value;
                }
                after=null;
            }
        }
        return null;
    }

    private CompletableFuture<JsonObject> snapshot() {
        var future=new CompletableFuture<JsonObject>();
        var server=mc.getServer();var uuid=mc.player.getUuid();var output=Registries.ITEM.get(Identifier.of(offer.get("output_id").getAsString()));
        server.execute(()->{
            try {
                var player=server.getPlayerManager().getPlayer(uuid);
                if(player==null) throw new IllegalStateException("player_missing");
                JsonObject counts=new JsonObject();
                for(int i=0;i<player.getInventory().size();i++) {
                    var stack=player.getInventory().getStack(i); if(stack.isEmpty()) continue;
                    String id=Registries.ITEM.getId(stack.getItem()).toString();counts.addProperty(id,stack.getCount()+(counts.has(id)?counts.get(id).getAsInt():0));
                }
                JsonObject ev=new JsonObject();ev.addProperty("server_verified",true);ev.add("inventory_after",counts);
                ev.addProperty("crafted",player.getStatHandler().getStat(Stats.CRAFTED.getOrCreateStat(output)));future.complete(ev);
            } catch(Exception e) {future.completeExceptionally(e);}
        });
        return future;
    }
    private JsonObject error(String reason) {JsonObject r=new JsonObject();r.addProperty("error",reason);return r;}
    // Parar não envia cliques adicionais. Um ingrediente já colocado fica na grade nativa.
    void cancel() {offer=null;recipe=null;before=null;after=null;phase=0;waitTicks=0;}
}
