package ai.minelife;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

/** Real HTTP/1.1 exchange with synthetic sensor data. This does not run Minecraft. */
public final class ResourcesBridgeContractTest {
    public static void main(String[] args) throws Exception {
        var client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        var hello=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/handshake"))
                .header("Authorization","Bearer transport-fixture").timeout(Duration.ofSeconds(3)).GET().build();
        var response=client.send(hello,HttpResponse.BodyHandlers.ofString());
        if(response.statusCode()!=200||!response.body().contains("mining-cooking-v1"))throw new AssertionError("resource handshake");
        String action=args[1];
        String inventory=switch(action) {
            case "mine"->"{\"minecraft:wooden_pickaxe\":1}";
            case "plant"->"{\"minecraft:wheat_seeds\":3}";
            default->"{\"minecraft:chicken\":1,\"minecraft:coal\":1}";
        };
        String mining=action.equals("mine")?"""
          [{"x":2,"y":64,"z":0,"id":"minecraft:stone","tool_id":"minecraft:wooden_pickaxe",
            "tool_slot":0,"tool_damage":0,"tool_max_damage":59,"tool_speed":2,
            "tool_suitable":true,"tool_required":true,"tool_wear":1,"tool_material":"wood"}]
          """:"[]";
        String cooking=action.equals("furnace_inspect")?"""
          [{"id":"minecraft:cooked_chicken","input_id":"minecraft:chicken","output_id":"minecraft:cooked_chicken",
            "cook_ticks":200,"fuel_id":"minecraft:coal","fuel_ticks":1600}]
          """:"[]";
        String farmland=action.equals("plant")?"[{\"x\":2,\"y\":64,\"z\":0}]":"[]";
        String tools=action.equals("mine")?"""
          [{"id":"minecraft:wooden_pickaxe","slot":0,"damage":0,"max_damage":59,"kind":"pickaxe","usable":true}]
          """:"[]";
        String body="""
          {"protocol":1,"session":"%s","world":"%s","dimension":"minecraft:overworld",
           "seq":1,"day":1,"time":1000,"active":true,"armed":true,
           "capabilities":["mine","pickup","furnace_load","furnace_inspect","furnace_take","plant"],
           "player":{"x":0,"y":64,"z":0,"health":20,"food":20,"danger":false,"inventory":%s,"tools":%s},
           "blocks":[{"x":3,"y":64,"z":0,"id":"minecraft:furnace","log":false,"lit":false}],
           "mining":%s,"cooking":%s,"farmland":%s,"results":[]}
          """.formatted(UUID.randomUUID(),"f".repeat(64),inventory,tools,mining,cooking,farmland);
        var step=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/step"))
                .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json")
                .timeout(Duration.ofSeconds(3)).POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var result=client.send(step,HttpResponse.BodyHandlers.ofString());
        if(result.statusCode()!=200||!result.body().contains("\"action\":\""+action+"\""))
            throw new AssertionError(action+" contract: "+result.statusCode()+" "+result.body());
        System.out.println(action+" observation/command HTTP/1.1 contract passed (synthetic).");
    }
}
