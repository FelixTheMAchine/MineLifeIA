package ai.minelife;

/** Server-only proof that a bed interaction actually completed a night rest. */
final class RestEvidence {
    private RestEvidence() {}

    static boolean verified(long beforeTime, long afterTime, int beforeSleeps, int afterSleeps) {
        int beforeDay = Math.floorMod(beforeTime, 24000);
        int afterDay = Math.floorMod(afterTime, 24000);
        return beforeDay >= 12542 && afterDay < 12000 && afterSleeps > beforeSleeps;
    }
}
