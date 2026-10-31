package ai.minelife;

import java.util.Comparator;
import java.util.List;

/** Pure ranking policy; candidates' suitability, wear and speed come from the game's components/tags. */
final class ToolSelection {
    record Candidate(int slot,int cost,double speed,int damage,int maxDamage,boolean hand,boolean suitable) { }
    static Candidate choose(List<Candidate> candidates,boolean requiresTool) {
        return candidates.stream().filter(c->c.suitable()&&(!requiresTool||!c.hand())
                &&(c.hand()||c.maxDamage()-c.damage()>=3)&&Double.isFinite(c.speed())&&c.speed()>0)
                .min(Comparator.comparingInt(Candidate::cost).thenComparing(Comparator.comparingDouble(Candidate::speed).reversed())
                        .thenComparingInt(Candidate::damage).thenComparingInt(Candidate::slot)).orElse(null);
    }
}
