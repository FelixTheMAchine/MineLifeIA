package ai.minelife;
import java.util.List;

/** Pure policy fixtures; actual tags/GUI/durability still need Fabric gameplay validation. */
public final class ToolSelectionTest {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("Tool policy #"+checks);}
    private static ToolSelection.Candidate c(int slot,int cost,double speed,int damage,int max,boolean hand,boolean suitable){return new ToolSelection.Candidate(slot,cost,speed,damage,max,hand,suitable);}
    public static void main(String[] args){
        var hand=c(0,0,1,0,0,true,true);var wood=c(1,0,2,0,59,false,true);
        var stone=c(2,0,4,0,131,false,true);var diamond=c(3,4,8,0,1561,false,true);
        check(ToolSelection.choose(List.of(hand,wood,stone,diamond),true)==stone);
        check(ToolSelection.choose(List.of(hand,diamond),false)==hand);
        check(ToolSelection.choose(List.of(hand,diamond),true)==diamond);
        check(ToolSelection.choose(List.of(c(1,0,2,0,59,false,false),diamond),true)==diamond);
        check(ToolSelection.choose(List.of(hand,c(1,0,4,129,131,false,true)),true)==null);
        check(ToolSelection.choose(List.of(hand,c(1,0,4,128,131,false,true)),true)!=null);
        check(ToolSelection.choose(List.of(c(1,0,Double.NaN,0,131,false,true)),true)==null);
        check(ToolSelection.choose(List.of(c(1,0,0,0,131,false,true)),true)==null);
        check(ToolSelection.choose(List.of(hand),true)==null);
        check(ToolSelection.choose(List.of(hand),false)==hand);
        System.out.println("Tool selection: "+checks+" policy assertions passed; not gameplay.");
    }
}
