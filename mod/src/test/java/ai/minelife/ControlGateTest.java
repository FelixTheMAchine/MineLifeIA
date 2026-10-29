package ai.minelife;

public final class ControlGateTest {
    private static int checks;
    private static void check(boolean condition) { checks++; if(!condition) throw new AssertionError("Control contract #"+checks); }
    public static void main(String[] args) {
        ControlGate gate=new ControlGate();
        gate.key(8,false);check(!gate.active && !gate.armed);
        gate.key(8,true);check(gate.active && gate.armed);
        long epoch=gate.epoch;check(gate.accepts(epoch));
        gate.key(9,true);check(!gate.active && gate.armed);check(!gate.accepts(epoch));
        gate.key(9,true);check(gate.active);
        gate.key(10,true);check(!gate.active && !gate.armed);check(gate.state.equals("EMERGENCY_STOP"));
        gate.key(9,true);check(!gate.active);
        gate.key(8,true);check(gate.active);
        gate.key(8,true);check(!gate.active && !gate.armed);
        check(gate.heartbeatExpired(3_100_000_000L,0));check(!gate.heartbeatExpired(2_900_000_000L,0));
        gate.stop("DISCONNECTED",true);check(!gate.active && !gate.armed);
        System.out.println("ControlGate: "+checks+" assertions passed (not a gameplay test).");
    }
}
