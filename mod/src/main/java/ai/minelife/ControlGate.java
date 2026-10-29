package ai.minelife;

/** Estado de autorização independente do jogo, testável sem simular física. */
public final class ControlGate {
    public boolean active, armed;
    public long epoch;
    public String state = "DISABLED";
    public void key(int key, boolean safe) {
        if (key == 10) stop("EMERGENCY_STOP", true);
        else if (key == 8) { if (active || armed) stop("DISABLED", true); else if (safe) enable(); }
        else if (key == 9) { if (active) stop("PAUSED", false); else if (armed && safe) enable(); }
    }
    public void enable() { active = true; armed = true; state = "ACTIVE"; epoch++; }
    public void stop(String reason, boolean disarm) { active = false; if (disarm) armed = false; state = reason; epoch++; }
    public boolean accepts(long replyEpoch) { return active && armed && replyEpoch == epoch; }
    public boolean heartbeatExpired(long now, long lastReply) { return now - lastReply > 3_000_000_000L; }
}
