package ai.minelife;

import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import net.minecraft.block.BlockState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.*;
import net.minecraft.registry.Registries;
import java.util.*;

/** Uses actual suitability, mining multipliers and material APIs. No guessed mining tiers by item name. */
final class ToolManager {
    private final MinecraftClient mc;
    ToolManager(MinecraftClient mc){this.mc=mc;}
    JsonArray inventory() {
        var list=new JsonArray();if(mc.player==null)return list;
        for(int slot=0;slot<36;slot++) {
            var stack=mc.player.getInventory().getStack(slot);
            if(!(stack.getItem() instanceof MiningToolItem tool))continue;
            var j=new JsonObject();j.addProperty("id",Registries.ITEM.getId(stack.getItem()).toString());j.addProperty("slot",slot);
            j.addProperty("damage",stack.getDamage());j.addProperty("max_damage",stack.getMaxDamage());
            j.addProperty("kind",tool instanceof PickaxeItem?"pickaxe":tool instanceof AxeItem?"axe":tool instanceof ShovelItem?"shovel":tool instanceof HoeItem?"hoe":"other");
            j.addProperty("usable",stack.getMaxDamage()-stack.getDamage()>=3&&stack.getEnchantments().isEmpty());list.add(j);
        }
        return list;
    }
    boolean usable(ItemStack stack,BlockState state) {
        if(stack.isEmpty())return !state.isToolRequired();
        return stack.getItem() instanceof MiningToolItem && stack.isDamageable()&&stack.getEnchantments().isEmpty()
                &&stack.getMaxDamage()-stack.getDamage()>=3&&(!state.isToolRequired()||stack.isSuitableFor(state))
                &&stack.getMiningSpeedMultiplier(state)>1;
    }
    JsonObject choose(BlockState state) {
        var candidates=new ArrayList<ToolSelection.Candidate>();boolean hotbarSpace=false;
        for(int i=0;i<9;i++)hotbarSpace|=mc.player.getInventory().getStack(i).isEmpty();
        for(int slot=0;slot<36;slot++) {
            var stack=mc.player.getInventory().getStack(slot);
            if((slot>=9&&(!hotbarSpace||stack.isEmpty()))||!usable(stack,state))continue;
            int cost=0;
            if(!stack.isEmpty()) {
                var m=((ToolItem)stack.getItem()).getMaterial();
                cost=m==ToolMaterials.WOOD||m==ToolMaterials.STONE?0:m==ToolMaterials.IRON?1:m==ToolMaterials.GOLD?3:4;
            }
            candidates.add(new ToolSelection.Candidate(slot,cost,stack.getMiningSpeedMultiplier(state),stack.getDamage(),stack.getMaxDamage(),stack.isEmpty(),!state.isToolRequired()||stack.isSuitableFor(state)));
        }
        var selected=ToolSelection.choose(candidates,state.isToolRequired());if(selected==null)return null;
        var stack=mc.player.getInventory().getStack(selected.slot());var j=new JsonObject();
        j.addProperty("tool_id",Registries.ITEM.getId(stack.getItem()).toString());j.addProperty("tool_slot",selected.slot());
        j.addProperty("tool_damage",stack.getDamage());j.addProperty("tool_max_damage",stack.getMaxDamage());
        j.addProperty("tool_speed",selected.speed());j.addProperty("tool_required",state.isToolRequired());j.addProperty("tool_suitable",selected.suitable());
        j.addProperty("tool_wear",stack.isEmpty()?0:1);
        var mat=stack.getItem() instanceof ToolItem tool?tool.getMaterial():null;
        j.addProperty("tool_material",mat instanceof Enum<?> e?e.name().toLowerCase(Locale.ROOT):mat==null?"hand":"custom");
        return j;
    }
}
