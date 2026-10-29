package ai.minelife;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

/** Contrato Java HTTP/1.1 -> FastAPI em banco temporário, não gameplay. */
public final class BridgeContractTest {
    public static void main(String[] args) throws Exception {
        var client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        var hello=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/handshake"))
            .version(HttpClient.Version.HTTP_1_1).header("Authorization","Bearer transport-fixture").timeout(Duration.ofSeconds(3)).GET().build();
        var response=client.send(hello,HttpResponse.BodyHandlers.ofString());
        if(response.statusCode()!=200 || !response.body().contains("HTTP/1.1")) throw new AssertionError("handshake");
        String body="{\"protocol\":1,\"session\":\""+UUID.randomUUID()+"\",\"world\":\""+"d".repeat(64)+"\",\"dimension\":\"minecraft:overworld\",\"seq\":1,\"day\":1,\"time\":1000,\"active\":true,\"armed\":true,\"player\":{\"x\":0,\"y\":64,\"z\":0,\"health\":20,\"food\":20,\"danger\":false,\"inventory\":{}},\"blocks\":[{\"x\":2,\"y\":64,\"z\":0,\"id\":\"minecraft:oak_log\",\"log\":true}],\"results\":[]}";
        var step=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/step")).version(HttpClient.Version.HTTP_1_1)
            .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json").timeout(Duration.ofSeconds(3))
            .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var action=client.send(step,HttpResponse.BodyHandlers.ofString());
        if(action.statusCode()!=200 || !action.body().contains("approach")) throw new AssertionError("observation/action: "+action.statusCode());
        System.out.println("Java HTTP/1.1 handshake and observation/command exchange passed.");
    }
}
