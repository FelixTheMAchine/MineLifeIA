package ai.minelife;

public final class PhysiologyCacheTest {
    private static int assertions;
    private static void check(boolean value) { assertions++; if(!value) throw new AssertionError(assertions); }
    private record Scope(String session,String world,String dimension,String player,long epoch,long generation) {}

    public static void main(String[] args) {
        Scope initial=new Scope("s","w","d","p",1,0);
        var cache=new PhysiologyCache<Scope,Integer>();
        check(cache.get(initial,0)==null);
        var flight=cache.begin(initial); check(flight!=null);
        check(cache.begin(initial)==null);
        check(cache.get(initial,100)==null); // Nonblocking while server read is pending.
        flight.complete(new PhysiologyCache.Sample<>(8,100));
        check(cache.get(initial,100).value()==8);
        check(cache.get(initial,2_000_000_100L).value()==8);
        check(cache.get(initial,2_000_000_101L)==null);
        for(Scope changed:new Scope[]{new Scope("new","w","d","p",1,0),new Scope("s","new","d","p",1,0),
                new Scope("s","w","new","p",1,0),new Scope("s","w","d","new",1,0),
                new Scope("s","w","d","p",2,0),new Scope("s","w","d","p",1,1)}) {
            cache=new PhysiologyCache<>();
            flight=cache.begin(initial);
            cache.invalidate();
            check(cache.get(changed,100)==null);
            check(cache.begin(changed)==null); // No second queued read after context invalidation.
            flight.complete(new PhysiologyCache.Sample<>(8,100));
            check(cache.get(changed,100)==null); // Late old result cannot enter current context.
            var fresh=cache.begin(changed); check(fresh!=null);
            fresh.complete(new PhysiologyCache.Sample<>(10,200));
            check(cache.get(changed,200).value()==10);
            check(cache.get(initial,200)==null);
        }
        cache=new PhysiologyCache<>();flight=cache.begin(initial);
        flight.complete(new PhysiologyCache.Sample<>(8,200));
        check(cache.get(initial,199)==null); // Negative sample age is also invalid.
        cache=new PhysiologyCache<>();flight=cache.begin(initial);flight.complete(null);
        check(cache.get(initial,100)==null);check(cache.begin(initial)!=null);
        cache=new PhysiologyCache<>();flight=cache.begin(initial);
        cache.retireStoppedExecutor();
        check(flight.isDone());check(cache.get(initial,100)==null);
        check(!flight.complete(new PhysiologyCache.Sample<>(8,100)));
        check(cache.begin(initial)!=null);
        System.out.println("Physiology cache: "+assertions+" assertions passed; synthetic, not gameplay.");
    }
}
