package ai.minelife;

import com.google.gson.*;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** One canonical resource shared with the Python planner; no command may redefine its geometry. */
final class ShelterBlueprint {
    static final String ID="refuge_v1";
    static final Set<String> WOODS=Set.of("oak","spruce","birch","jungle","acacia","dark_oak","mangrove","cherry","bamboo","crimson","warped");
    record Cell(int x,int y,int z,int sx,int sy,int sz,Direction face,String role) {
        BlockPos target(BlockPos anchor){return anchor.add(x,y,z);}
        BlockPos support(BlockPos anchor){return anchor.add(sx,sy,sz);}
        boolean accepts(String item){return material(item,role.equals("door")?"_door":"_planks");}
    }
    static boolean material(String item,String suffix) {
        return WOODS.stream().anyMatch(wood->item.equals("minecraft:"+wood+suffix));
    }
    static final List<Cell> CELLS=load();
    private static List<Cell> load() {
        try(var stream=ShelterBlueprint.class.getResourceAsStream("/minelife_ai/blueprints/refuge_v1.json")) {
            if(stream==null)throw new IllegalStateException("missing_blueprint");
            var value=JsonParser.parseReader(new InputStreamReader(stream,StandardCharsets.UTF_8)).getAsJsonObject();
            if(!value.get("id").getAsString().equals(ID))throw new IllegalStateException("blueprint_identity");
            List<Cell> result=new ArrayList<>();
            for(var raw:value.getAsJsonArray("steps")) {
                var row=raw.getAsJsonObject();var p=row.getAsJsonArray("offset");var s=row.getAsJsonArray("support");
                var cell=new Cell(p.get(0).getAsInt(),p.get(1).getAsInt(),p.get(2).getAsInt(),
                        s.get(0).getAsInt(),s.get(1).getAsInt(),s.get(2).getAsInt(),Direction.byName(row.get("face").getAsString()),row.get("role").getAsString());
                if(cell.face()==null || !cell.support(BlockPos.ORIGIN).offset(cell.face()).equals(cell.target(BlockPos.ORIGIN)))throw new IllegalStateException("invalid_blueprint_support");
                result.add(cell);
            }
            if(result.size()!=17)throw new IllegalStateException("blueprint_size");
            return List.copyOf(result);
        }catch(Exception e){throw new IllegalStateException("cannot_load_shelter_blueprint",e);}
    }
}
