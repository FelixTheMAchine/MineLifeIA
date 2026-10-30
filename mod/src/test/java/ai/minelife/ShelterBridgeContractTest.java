package ai.minelife;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

/** Synthetic project observation over a real loopback socket, not Minecraft gameplay. */
public final class ShelterBridgeContractTest {
    public static void main(String[] args) throws Exception {
        var client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        var hello=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/handshake")).version(HttpClient.Version.HTTP_1_1)
                .header("Authorization","Bearer transport-fixture").timeout(Duration.ofSeconds(3)).GET().build();
        var response=client.send(hello,HttpResponse.BodyHandlers.ofString());
        if(response.statusCode()!=200||!response.body().contains("shelters-v1"))throw new AssertionError("shelter handshake");
        String body="""
          {"protocol":1,"session":"%s","world":"%s","dimension":"minecraft:overworld",
           "seq":1,"day":1,"time":1000,"active":true,"armed":true,
           "capabilities":["build_shelter","inspect_shelter","enter_shelter","leave_shelter"],
           "player":{"x":0.5,"y":64,"z":0.5,"health":20,"food":20,"danger":false,
             "inventory":{"minecraft:oak_planks":16,"minecraft:oak_door":1}},
           "blocks":[],"shelter_sites":[{"x":0,"y":64,"z":0}],"results":[]}
          """.formatted(UUID.randomUUID(),"e".repeat(64));
        var step=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/step")).version(HttpClient.Version.HTTP_1_1)
                .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json")
                .timeout(Duration.ofSeconds(3)).POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var action=client.send(step,HttpResponse.BodyHandlers.ofString());
        if(action.statusCode()!=200||!action.body().contains("inspect_shelter")||!action.body().contains("refuge_v1"))throw new AssertionError("shelter observation/action: "+action.statusCode());
        System.out.println("Shelter HTTP/1.1 observation and project command passed (synthetic).");
    }
}
