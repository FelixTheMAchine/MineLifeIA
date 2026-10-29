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
        if(response.statusCode()!=200 || !response.body().contains("HTTP/1.1")
                || !response.body().contains("workstations-v1") || !response.body().contains("craft_table")) throw new AssertionError("handshake");
        String body="""
            {"protocol":1,"session":"%s","world":"%s","dimension":"minecraft:overworld",
             "seq":1,"day":1,"time":1000,"active":true,"armed":true,"capabilities":["craft_table"],
             "player":{"x":0,"y":64,"z":0,"health":20,"food":4,"danger":false,"inventory":{"minecraft:wheat":3}},
             "blocks":[{"x":2,"y":64,"z":0,"id":"minecraft:crafting_table","log":false}],
             "recipes":[{"id":"minecraft:bread","input_id":"minecraft:wheat","input_count":3,
               "inputs":{"minecraft:wheat":3},"output_id":"minecraft:bread","output_count":1,
               "grid":3,"station":{"x":2,"y":64,"z":0}}],"placement_spots":[],"results":[]}
            """.formatted(UUID.randomUUID(),"d".repeat(64));
        var step=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/step")).version(HttpClient.Version.HTTP_1_1)
            .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json").timeout(Duration.ofSeconds(3))
            .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var action=client.send(step,HttpResponse.BodyHandlers.ofString());
        if(action.statusCode()!=200 || !action.body().contains("craft_table")) throw new AssertionError("observation/action: "+action.statusCode());
        System.out.println("Java HTTP/1.1 handshake and workstation observation/command exchange passed (synthetic, not gameplay).");
    }
}
