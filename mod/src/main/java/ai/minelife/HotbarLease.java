package ai.minelife;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.screen.slot.SlotActionType;

/** Moves an existing stack into an empty hotbar slot using a native SWAP, then restores if unchanged. */
final class HotbarLease {
    private final MinecraftClient mc;
    private ClientPlayerEntity owner;
    private int source=-1,selected=-1,previous=-1;
    private ItemStack original=ItemStack.EMPTY;
    HotbarLease(MinecraftClient mc){this.mc=mc;}
    String acquire(String item) {
        release();
        if(mc.player==null || mc.currentScreen!=null || mc.player.currentScreenHandler!=mc.player.playerScreenHandler
                || !mc.player.currentScreenHandler.getCursorStack().isEmpty())return "inventory_busy";
        for(int i=0;i<36;i++)if(!mc.player.getInventory().getStack(i).isEmpty()
                && Registries.ITEM.getId(mc.player.getInventory().getStack(i).getItem()).toString().equals(item)){source=i;break;}
        if(source<0)return "material_missing";
        owner=mc.player;previous=owner.getInventory().selectedSlot;original=owner.getInventory().getStack(source).copy();
        if(source<9)selected=source;
        else {
            for(int i=0;i<9;i++)if(owner.getInventory().getStack(i).isEmpty()){selected=i;break;}
            if(selected<0){release();return "empty_hotbar_slot_required";}
            mc.interactionManager.clickSlot(owner.playerScreenHandler.syncId,source,selected,SlotActionType.SWAP,owner);
        }
        owner.getInventory().selectedSlot=selected;
        return null;
    }
    boolean ready() {
        return owner!=null && owner==mc.player && selected>=0
                && ItemStack.areItemsAndComponentsEqual(owner.getInventory().getStack(selected),original);
    }
    void release() {
        try {
            if(owner!=null && owner==mc.player) {
                if(source>=9 && selected>=0 && mc.interactionManager!=null
                        && owner.currentScreenHandler==owner.playerScreenHandler
                        && owner.currentScreenHandler.getCursorStack().isEmpty()) {
                    var held=owner.getInventory().getStack(selected);
                    if(owner.getInventory().getStack(source).isEmpty() && !held.isEmpty()
                            && ItemStack.areItemsAndComponentsEqual(held,original)
                            && held.getCount()<=original.getCount() && held.getCount()>=original.getCount()-1)
                        mc.interactionManager.clickSlot(owner.playerScreenHandler.syncId,source,selected,SlotActionType.SWAP,owner);
                }
            }
        } finally {
            if(owner!=null && owner==mc.player && previous>=0)owner.getInventory().selectedSlot=previous;
            owner=null;source=selected=previous=-1;original=ItemStack.EMPTY;
        }
    }
}
