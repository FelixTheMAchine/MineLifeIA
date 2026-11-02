package ai.minelife;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

/** Real Java/FastAPI exchange with synthetic NPC snapshots, not Minecraft gameplay. */
public final class SocialBridgeContractTest {
    private static final String PERSON="11111111-1111-4111-8111-111111111111";
    private static final String PLAYER="22222222-2222-4222-8222-222222222222";
    public static void main(String[] args) throws Exception {
        var client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
        var hello=client.send(request(args[0]+"/bridge/handshake",null),HttpResponse.BodyHandlers.ofString());
        if(hello.statusCode()!=200||!hello.body().contains("social-v1")||!hello.body().contains("social_contact"))throw new AssertionError("social handshake");
        String session=UUID.randomUUID().toString();
        var first=client.send(request(args[0]+"/bridge/step",body(session,1,"[]")),HttpResponse.BodyHandlers.ofString());
        String observe=command(first,"social_observe");
        String snapshot=snapshot("null");
        String observed=proof(observe,snapshot,snapshot,"");
        var second=client.send(request(args[0]+"/bridge/step",body(session,2,observed)),HttpResponse.BodyHandlers.ofString());
        String contact=command(second,"social_contact");
        String gui=",\"interaction_accepted\":true,\"mca_version\":\"7.7.19+1.21.1\",\"gui\":{\"observed\":true,\"screen_class\":\"net.conczin.mca.client.gui.InteractScreen\",\"person_uuid\":\""+PERSON+"\"}";
        var third=client.send(request(args[0]+"/bridge/step",body(session,3,proof(contact,snapshot,snapshot("\""+PLAYER+"\""),gui))),HttpResponse.BodyHandlers.ofString());
        if(third.statusCode()!=200||!third.body().contains(contact)||!third.body().contains("\"command\":null"))throw new AssertionError("social acknowledgement: "+third.body());
        var state=client.send(request(args[0]+"/api/state",null),HttpResponse.BodyHandlers.ofString());
        if(state.statusCode()!=200||!state.body().contains("\"relationship\":\"unknown\"")||!state.body().contains(PERSON))throw new AssertionError("social memory absent");
        System.out.println("Social observation/contact/memory HTTP/1.1 contract passed (synthetic).");
    }
    private static HttpRequest request(String url,String body){
        var builder=HttpRequest.newBuilder(URI.create(url)).header("Authorization","Bearer transport-fixture").timeout(Duration.ofSeconds(4));
        return body==null?builder.GET().build():builder.header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build();
    }
    private static String command(HttpResponse<String> result,String action){
        if(result.statusCode()!=200||!result.body().contains("\"action\":\""+action+"\""))throw new AssertionError(result.body());
        var match=java.util.regex.Pattern.compile("\"command\":\\{\"id\":\"([^\"]+)\"").matcher(result.body());
        if(!match.find())throw new AssertionError("issued id absent");return match.group(1);
    }
    private static String body(String session,int sequence,String results){return """
        {"protocol":1,"session":"%s","world":"%s","dimension":"minecraft:overworld","seq":%d,"day":1,"time":1000,
         "active":true,"armed":true,"capabilities":["social_observe","social_contact"],"blocks":[],"results":%s,
         "social":[{"person_uuid":"%s","entity_type":"mca:male_villager","name":"Alex","x":2,"y":64,"z":0,"can_contact":true}],
         "player":{"x":0,"y":64,"z":0,"health":20,"food":20,"danger":false,"inventory":{}}}
        """.formatted(session,"d".repeat(64),sequence,results,PERSON);}
    private static String snapshot(String interacting){return """
        {"person_uuid":"%s","entity_type":"mca:male_villager","name":"Alex","position":{"x":2,"y":64,"z":0},
         "dimension":"minecraft:overworld","alive":true,"visible":true,"distance":2,"player_uuid":"%s",
         "inventory":{},"inventory_fingerprint":"%s","main_hand":"minecraft:air","off_hand":"minecraft:air","interacting_player":%s}
        """.formatted(PERSON,PLAYER,"a".repeat(64),interacting);}
    private static String proof(String command,String before,String after,String extra){return """
        [{"id":"%s","status":"success","reason":"synthetic_native_fixture","evidence":{"server_verified":true,
          "target":{"x":2,"y":64,"z":0},"person_uuid":"%s","entity_type":"mca:male_villager","dimension":"minecraft:overworld",
          "before":%s,"after":%s%s}}]
        """.formatted(command,PERSON,before,after,extra);}
}
