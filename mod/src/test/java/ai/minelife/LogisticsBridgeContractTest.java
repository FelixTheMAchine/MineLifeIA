package ai.minelife;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

/** HTTP/1.1 bridge contract with synthetic observations; never a gameplay test. */
public final class LogisticsBridgeContractTest {
    public static void main(String[] args) throws Exception {
        var client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        var hello=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/handshake"))
                .header("Authorization","Bearer transport-fixture").GET().build();
        var greeting=client.send(hello,HttpResponse.BodyHandlers.ofString());
        if(greeting.statusCode()!=200||!greeting.body().contains("storage-v1")||!greeting.body().contains("agriculture-v1"))
            throw new AssertionError("logistics features missing");
        boolean till=args[1].equals("till");
        String offers=till?"""
          "tilling":[{"x":2,"y":63,"z":0,"id":"minecraft:dirt","tool_id":"minecraft:wooden_hoe",
          "tool_slot":0,"tool_damage":0,"tool_max_damage":59,"water":{"x":4,"y":63,"z":0}}]
          """:"\"storage\":[{\"x\":2,\"y\":64,\"z\":0}]";
        String body="""
          {"protocol":1,"session":"%s","world":"%s","dimension":"minecraft:overworld",
          "seq":1,"day":1,"time":1000,"active":true,"armed":true,
          "capabilities":["till","plant","storage_inspect","storage_deposit","storage_withdraw","eat"],
          "player":{"x":0,"y":64,"z":0,"health":20,"food":20,"danger":false,
          "inventory":{"minecraft:wheat_seeds":2,"minecraft:wooden_hoe":1,"minecraft:bread":2},
          "foods":[{"id":"minecraft:bread","slot":1,"count":2,"nutrition":5}]},
          "blocks":[],"results":[],%s}
          """.formatted(UUID.randomUUID(),"e".repeat(64),offers);
        var request=HttpRequest.newBuilder(URI.create(args[0]+"/bridge/step"))
                .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json")
                .timeout(Duration.ofSeconds(3)).POST(HttpRequest.BodyPublishers.ofString(body)).build();
        var result=client.send(request,HttpResponse.BodyHandlers.ofString());
        String expected=till?"till":"storage_inspect";
        if(result.statusCode()!=200||!result.body().contains("\"action\":\""+expected+"\""))
            throw new AssertionError("logistics contract: "+result.statusCode()+" "+result.body());
        if(args[1].equals("interrupt")) {
            var ids=java.util.regex.Pattern.compile("\"command\":\\{\"id\":\"([^\"]+)\"").matcher(result.body());
            if(!ids.find())throw new AssertionError("missing issued command");
            String id=ids.group(1);
            String hungry=body.replace("\"seq\":1","\"seq\":2").replace("\"food\":20","\"food\":4");
            var interrupt=client.send(post(args[0],hungry),HttpResponse.BodyHandlers.ofString());
            if(interrupt.statusCode()!=200||!interrupt.body().contains("\"interrupt\":\""+id+"\"")
                    ||!interrupt.body().contains("\"command\":null"))throw new AssertionError("missing correlated interruption: "+interrupt.body());
            String cancelled=hungry.replace("\"seq\":2","\"seq\":3").replace("\"results\":[]",
                    "\"results\":[{\"id\":\""+id+"\",\"status\":\"cancelled\",\"reason\":\"physiological_preemption\",\"evidence\":{}}]");
            var meal=client.send(post(args[0],cancelled),HttpResponse.BodyHandlers.ofString());
            if(meal.statusCode()!=200||!meal.body().contains("\"action\":\"eat\""))
                throw new AssertionError("cancellation did not permit meal: "+meal.body());
        }
        System.out.println(args[1]+" HTTP/1.1 observation/command contract passed (synthetic).");
    }
    private static HttpRequest post(String base,String body) {
        return HttpRequest.newBuilder(URI.create(base+"/bridge/step"))
                .header("Authorization","Bearer transport-fixture").header("Content-Type","application/json")
                .timeout(Duration.ofSeconds(3)).POST(HttpRequest.BodyPublishers.ofString(body)).build();
    }
}
