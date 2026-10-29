package ai.minelife;
import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;

/** Retains the pending response across game ticks, including slow or exceptional completions. */
final class PendingServerRead<T> {
    private CompletableFuture<T> pending;
    CompletableFuture<T> request(Supplier<CompletableFuture<T>> source) {
        if(pending==null)pending=source.get();
        return pending;
    }
    void clear(){pending=null;}
}
