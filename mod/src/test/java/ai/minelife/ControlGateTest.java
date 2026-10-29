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
        check(FoodConsumptionEvidence.classify(5,10,1,0)==FoodConsumptionEvidence.Result.VERIFIED);
        check(FoodConsumptionEvidence.classify(5,5,1,0)==FoodConsumptionEvidence.Result.NO_NUTRITION);
        check(FoodConsumptionEvidence.classify(5,10,2,0)==FoodConsumptionEvidence.Result.WRONG_AMOUNT);
        check(FoodConsumptionEvidence.classify(5,5,1,1)==FoodConsumptionEvidence.Result.NO_CONSUMPTION);
        check(RestEvidence.verified(13000,100,0,1));
        check(!RestEvidence.verified(13000,100,0,0));
        check(!RestEvidence.verified(6000,100,0,1));
        check(!RestEvidence.verified(12001,100,0,1));
        check(!RestEvidence.verified(13000,13010,0,1));
        System.out.println("ControlGate/Food/RestEvidence: "+checks+" assertions passed (not a gameplay test).");
    }
}
