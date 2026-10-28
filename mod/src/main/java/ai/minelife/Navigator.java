package ai.minelife;

import net.minecraft.block.BlockState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.hit.HitResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.RaycastContext;
import java.util.*;

/** Busca limitada sobre chão sólido. Não coloca nem destrói blocos para abrir caminho. */
final class Navigator {
    private final MinecraftClient mc;
    private final Deque<BlockPos> route = new ArrayDeque<>();
    private Vec3d lastPosition;
    private int stuckTicks;

    Navigator(MinecraftClient mc) { this.mc = mc; }

    boolean hazardous(BlockPos p) {
        String id = Registries.BLOCK.getId(mc.world.getBlockState(p).getBlock()).toString();
        return id.contains("lava") || id.contains("fire") || id.contains("cactus") ||
               id.contains("magma") || id.contains("campfire") || id.contains("berry_bush") || id.contains("powder_snow");
    }

    boolean passable(BlockPos p) {
        return mc.world.isChunkLoaded(p) && mc.world.getBlockState(p).getCollisionShape(mc.world, p).isEmpty()
            && mc.world.getFluidState(p).isEmpty() && !hazardous(p);
    }

    boolean walkable(BlockPos p) {
        BlockState floor = mc.world.getBlockState(p.down());
        if (!passable(p) || !passable(p.up()) || !floor.isSideSolidFullSquare(mc.world, p.down(), Direction.UP)) return false;
        for (Direction d : Direction.Type.HORIZONTAL) if (hazardous(p.offset(d)) || hazardous(p.down().offset(d))) return false;
        return !hazardous(p.down());
    }

    boolean visibleFrom(Vec3d eye, BlockPos target) {
        Vec3d center = Vec3d.ofCenter(target);
        if (eye.squaredDistanceTo(center) > 3.5 * 3.5) return false;
        BlockHitResult hit = mc.world.raycast(new RaycastContext(eye, center, RaycastContext.ShapeType.OUTLINE,
                RaycastContext.FluidHandling.NONE, mc.player));
        return hit.getType() == HitResult.Type.BLOCK && hit.getBlockPos().equals(target);
    }

    boolean plan(BlockPos target, boolean collect) {
        route.clear(); stuckTicks = 0; lastPosition = null;
        BlockPos start = mc.player.getBlockPos();
        ArrayDeque<BlockPos> queue = new ArrayDeque<>();
        Map<BlockPos, BlockPos> parent = new HashMap<>();
        queue.add(start); parent.put(start, start);
        BlockPos end = null;
        while (!queue.isEmpty() && parent.size() < 1400) {
            BlockPos p = queue.remove();
            boolean goal = collect ? Vec3d.ofBottomCenter(p).squaredDistanceTo(Vec3d.ofBottomCenter(target)) < 1.2
                                   : visibleFrom(Vec3d.ofBottomCenter(p).add(0, 1.62, 0), target);
            if (goal) { end = p; break; }
            for (Direction d : Direction.Type.HORIZONTAL) {
                for (int dy : new int[]{0, 1, -1}) {
                    BlockPos next = p.offset(d).up(dy);
                    if (Math.abs(next.getX() - start.getX()) > 15 || Math.abs(next.getZ() - start.getZ()) > 15 ||
                        Math.abs(next.getY() - start.getY()) > 5 || parent.containsKey(next) || !walkable(next)) continue;
                    if (dy == 1 && !passable(p.up(2))) continue;
                    if (dy == -1 && !passable(next.up(2))) continue;
                    parent.put(next, p); queue.add(next); break;
                }
            }
        }
        if (end == null) return false;
        while (!end.equals(start)) { route.addFirst(end); end = parent.get(end); }
        return true;
    }

    /** 1 = chegou, 0 = avançando, -1 = caminho inválido/travado. */
    int tick() {
        if (route.isEmpty()) { release(); return 1; }
        BlockPos next = route.peek();
        if (!walkable(next)) { release(); return -1; }
        Vec3d pos = mc.player.getPos();
        Vec3d dest = Vec3d.ofBottomCenter(next);
        if (Math.abs(pos.x - dest.x) < .24 && Math.abs(pos.z - dest.z) < .24 && Math.abs(pos.y - dest.y) < .6) {
            route.remove(); release(); return route.isEmpty() ? 1 : 0;
        }
        if (lastPosition != null && pos.squaredDistanceTo(lastPosition) < .0001) stuckTicks++; else stuckTicks = 0;
        lastPosition = pos;
        if (stuckTicks > 35) { release(); return -1; }
        // Nunca ande sobre uma borda que mudou desde o planejamento.
        if (!mc.player.isOnGround() && mc.player.getVelocity().y < -.3 && mc.player.fallDistance > 1.4f) { release(); return -1; }
        float yaw = (float)Math.toDegrees(Math.atan2(-(dest.x - pos.x), dest.z - pos.z));
        mc.player.setYaw(yaw); mc.player.setPitch(12);
        mc.options.forwardKey.setPressed(true);
        mc.options.jumpKey.setPressed(next.getY() > pos.y + .45 && mc.player.isOnGround());
        mc.options.sprintKey.setPressed(false);
        return 0;
    }

    void release() {
        mc.options.forwardKey.setPressed(false);
        mc.options.backKey.setPressed(false);
        mc.options.leftKey.setPressed(false);
        mc.options.rightKey.setPressed(false);
        mc.options.jumpKey.setPressed(false);
        mc.options.sprintKey.setPressed(false);
        mc.options.sneakKey.setPressed(false);
    }
}
