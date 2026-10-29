package ai.minelife;

/** Pure proof classification; a client slot becoming empty is not evidence by itself. */
final class FoodConsumptionEvidence {
    enum Result { VERIFIED, NO_CONSUMPTION, WRONG_AMOUNT, NO_NUTRITION }

    static Result classify(int foodBefore, int foodAfter, int itemCountBefore, int itemCountAfter) {
        int consumed = itemCountBefore - itemCountAfter;
        if (consumed == 0) return Result.NO_CONSUMPTION;
        if (consumed != 1) return Result.WRONG_AMOUNT;
        return foodAfter > foodBefore ? Result.VERIFIED : Result.NO_NUTRITION;
    }

    static boolean awaitingConfirmation(Result result,int ticksWithEmptySlot) {
        return result==Result.NO_CONSUMPTION && ticksWithEmptySlot<20;
    }

    static boolean allowed(String id) {
        // Containers need different inventory evidence; harmful/teleporting food is never selected.
        return id.startsWith("minecraft:") && !java.util.Set.of("minecraft:rotten_flesh","minecraft:spider_eye",
                "minecraft:poisonous_potato","minecraft:pufferfish","minecraft:chicken","minecraft:chorus_fruit",
                "minecraft:suspicious_stew","minecraft:honey_bottle","minecraft:rabbit_stew",
                "minecraft:mushroom_stew","minecraft:beetroot_soup").contains(id);
    }

    private FoodConsumptionEvidence() {}
}
