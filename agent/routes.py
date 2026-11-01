"""Progressive return through freshly advertised local frontiers, never a claimed global safe path."""
import json
import math
import time
from uuid import uuid4
from agent.memory import now

class RouteManager:
    MAX_DETOUR_SEGMENTS=3
    MAX_DETOUR_DISTANCE=6
    MAX_SEGMENTS=64

    def __init__(self,memory):self.m=memory;self.reason='Nenhum retorno necessário.'

    def request(self,s,destination,source,purpose):
        if 'explore' not in s.capabilities or s.player.danger or s.player.food<=8:return None
        position=(s.player.x,s.player.y,s.player.z);end=tuple(destination[k] for k in ('x','y','z'))
        distance=math.dist(position,end)
        rows=self.m.rows('SELECT * FROM ReturnRoutes WHERE world=? AND dimension=? AND source=? ORDER BY created DESC,rowid DESC LIMIT 1',(s.world,s.dimension,source))
        route=rows[0] if rows else None
        if distance<=12:
            if route and route['status']=='active':self.m.db.execute("UPDATE ReturnRoutes SET status='local',updated=? WHERE id=?",(now(),route['id']))
            return None
        if route and route['status']=='blocked' and time.time()<route['retry_after']:
            self.reason='Retorno suspenso por falta de progresso; reavaliar depois sem repetir o mesmo trecho.';return None
        if route is None or route['status']=='local':
            rid=str(uuid4());stamp=now()
            remembered={**destination,'_route_origin':list(position)}
            self.m.db.execute('INSERT INTO ReturnRoutes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,s.world,s.dimension,source,json.dumps(remembered),purpose,'active','[]',0.,distance,stamp,stamp))
            route=self.m.rows('SELECT * FROM ReturnRoutes WHERE id=?',(rid,))[0]
        elif route['status']=='blocked':
            self.m.db.execute("UPDATE ReturnRoutes SET status='active',updated=? WHERE id=?",(now(),route['id']))
        history=json.loads(route['history']);seen={tuple(p[k] for k in ('x','y','z')) for p in history}
        origin=json.loads(route['destination']).get('_route_origin')
        if origin is not None:seen.add(tuple(math.floor(v) for v in origin))
        # Reconstruct budgets from verified arrivals, including after a process restart.
        # Keep the best checkpoint until at least one block of real progress is made.
        best=route['start_distance'];detours=0
        for point in history:
            remaining=math.dist((point['x']+.5,point['y'],point['z']+.5),end)
            if remaining<=best-1:best=remaining;detours=0
            else:detours+=1
        choices=[];local_detours=[]
        for f in s.frontiers:
            target=(f.x+.5,f.y,f.z+.5)
            if not f.safe or math.dist(position,target)>15 or math.dist(position,target)<2 or (f.x,f.y,f.z) in seen:continue
            # Every segment still needs a fresh safe frontier; no global path is inferred.
            remaining=math.dist(target,end);gain=distance-remaining
            progress=gain>=1 and remaining<=best-1
            if len(history)>=self.MAX_SEGMENTS:continue
            if not progress and (detours>=self.MAX_DETOUR_SEGMENTS or
                                 remaining>best+self.MAX_DETOUR_DISTANCE or f.path_length>15):continue
            failed=self.m.rows("SELECT 1 FROM GoalPlans WHERE world=? AND subject=? AND (attempts>=2 OR cooldown>?)",
                               (s.world,f"return:{route['id']}:{f.x}:{f.y}:{f.z}",time.time()))
            if not failed:
                if progress:choices.append((gain/f.path_length,f))
                else:local_detours.append((gain,-f.path_length,f))
        if not choices and local_detours:
            choices=[(1,max(local_detours,key=lambda p:p[:2])[2])]
        if not choices:
            self.m.db.execute("UPDATE ReturnRoutes SET status='blocked',retry_after=?,updated=? WHERE id=?",(time.time()+60,now(),route['id']))
            self.reason='Sem trecho observado dentro do orçamento de retorno; uma rota completa não foi demonstrada.';return None
        f=max(choices,key=lambda p:p[0])[1];target=dict(x=f.x,y=f.y,z=f.z,id='minecraft:air')
        self.reason='Avançar por um trecho anunciado como transitável; revalidar o próximo trecho após chegar.'
        return dict(subject=f"return:{route['id']}:{f.x}:{f.y}:{f.z}",description=purpose,reason=self.reason,
                    priority=300,kind='explore',skill='explore_region',params=dict(target=target,route=route['id']))

    def record(self,s,cmd,eid):
        rid=cmd.get('route')
        if not rid:return
        rows=self.m.rows("SELECT * FROM ReturnRoutes WHERE id=? AND world=? AND dimension=? AND status='active'",(rid,s.world,s.dimension))
        if not rows:return
        row=rows[0];history=json.loads(row['history']);target=cmd['target']
        history.append({**{k:target[k] for k in ('x','y','z')},'event':eid})
        self.m.db.execute('UPDATE ReturnRoutes SET history=?,updated=? WHERE id=?',(json.dumps(history),now(),rid))
