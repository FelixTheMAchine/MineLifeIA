package ai.minelife;

import net.minecraft.util.math.*;
import java.util.*;

/** Static block geometry using the game's math classes. No client, world, save or gameplay is started. */
public final class ShelterGeometryTest {
    private static int checks;
    private static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
    public static void main(String[] args) {
        var cells=ShelterBlueprint.CELLS;Set<BlockPos> occupied=new HashSet<>();
        for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++)occupied.add(new BlockPos(x,-1,z));
        int wood=0,doors=0;
        for(int index=0;index<cells.size();index++) {
            var cell=cells.get(index);var p=cell.target(BlockPos.ORIGIN);var support=cell.support(BlockPos.ORIGIN);
            check(occupied.contains(support),"support not built before step "+index);
            check(!occupied.contains(p),"overlap at step "+index);
            check(!p.equals(BlockPos.ORIGIN)&&!p.equals(BlockPos.ORIGIN.up()),"interior obstructed");
            var eye=new Vec3d(.5,index==14?2.6:1.62,.5); // a native jump is needed only for the eave's top face
            var aim=Vec3d.ofCenter(support).add(Vec3d.of(cell.face().getVector()).multiply(.499));
            var contact=new Box(support).raycast(eye,aim);
            check(contact.isPresent(),"no support ray at step "+index);
            check(eye.distanceTo(aim)<3.5,"outside reach");
            double first=contact.orElseThrow().squaredDistanceTo(eye);
            for(var block:occupied) {
                if(block.equals(support))continue;
                var hit=new Box(block).raycast(eye,aim);
                check(hit.isEmpty() || hit.get().squaredDistanceTo(eye)>=first-1e-6,"support occluded at step "+index+" by "+block);
            }
            occupied.add(p);
            if(cell.role().equals("door")){doors++;occupied.add(p.up());}else wood++;
        }
        check(wood==16&&doors==1,"material accounting");
        for(int y=0;y<2;y++)for(int x=-1;x<=1;x++)for(int z=-1;z<=1;z++)
            if(x!=0||z!=0)check(occupied.contains(new BlockPos(x,y,z)),"shell gap");
        check(occupied.contains(new BlockPos(0,2,0)),"roof missing");
        check(!ShelterBlueprint.material("minecraft:iron_door","_door"),"iron door allowed");
        check(!ShelterBlueprint.material("mca:oak_door","_door"),"unknown door allowed");
        // Geometry fixtures use the 3/16-panel dimensions inspected in the mapped DoorBlock bytecode.
        // This does not instantiate a game block: registry bootstrap requires Fabric's runtime transformations.
        var panels=List.of(new Box(0,0,0,3/16.0,1,1),new Box(13/16.0,0,0,1,1,1),
                new Box(0,0,0,1,1,3/16.0),new Box(0,0,13/16.0,1,1,1));
        for(int index=0;index<panels.size();index++) {
            var panel=panels.get(index).offset(0,0,1);boolean open=index<2;
            var sweep=new Box(.2,0,.2,.8,1.8,2.8);
            check(panel.intersects(sweep)!=open,"door panel fixture blocks the center route");
            var aim=panel.getCenter();
            for(var eye:List.of(new Vec3d(.5,1.62,.5),new Vec3d(.5,1.62,2.5)))
                check(panel.raycast(eye,aim).isPresent(),"door panel fixture cannot be clicked from an access point");
        }
        System.out.println("Shelter blueprint: "+checks+" static geometry assertions passed; not gameplay.");
    }
}
