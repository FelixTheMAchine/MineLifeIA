package ai.minelife;

import java.util.Objects;
import java.util.concurrent.CompletableFuture;

/** Client-thread ownership; an invalidation never creates a second queued server read. */
final class PhysiologyCache<K,V> {
    static final long MAX_AGE_NS=2_000_000_000L;
    record Sample<V>(V value, long nanoTime) {}
    private CompletableFuture<Sample<V>> pending;
    private K pendingScope, cachedScope;
    private Sample<V> cached;

    void invalidate() { cached=null; cachedScope=null; }

    /** Only after the owning executor thread has terminated, so no read can still run. */
    void retireStoppedExecutor() { if(pending!=null) pending.complete(null); }

    Sample<V> get(K scope, long now) {
        if(!Objects.equals(scope,cachedScope)) invalidate();
        if(pending!=null && pending.isDone()) {
            Sample<V> ready=pending.getNow(null);
            if(ready!=null && Objects.equals(scope,pendingScope)) { cached=ready; cachedScope=scope; }
            pending=null; pendingScope=null;
        }
        if(cached==null) return null;
        long age=now-cached.nanoTime;
        if(age<0 || age>MAX_AGE_NS) { invalidate(); return null; }
        return cached;
    }

    CompletableFuture<Sample<V>> begin(K scope) {
        if(pending!=null) return null;
        pendingScope=scope; pending=new CompletableFuture<>();
        return pending;
    }
}
