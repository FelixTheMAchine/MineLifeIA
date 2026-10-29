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

    private FoodConsumptionEvidence() {}
}
