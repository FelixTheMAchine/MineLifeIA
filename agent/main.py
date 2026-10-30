import asyncio
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from agent.config import ROOT, load_config
from agent.memory import MemoryManager
from agent.journal.writer import JournalWriter
from agent.engine import CognitiveEngine
from agent.protocol import Step
from agent.llm import LanguageAdvisor
from agent.skills import SkillRegistry

BRIDGE_FEATURES = ['workstations-v1','shelters-v1']
BRIDGE_ACTIONS = sorted({action for skill in SkillRegistry.skills.values() for action in skill.actions})


def create_app(root=ROOT, config=None):
    config = config or load_config(root)
    memory = MemoryManager(root / 'data' / 'memory.sqlite3')
    journal = JournalWriter(memory, root / 'journals')
    engine = CognitiveEngine(memory, journal, config.get('planning'))
    lock = asyncio.Lock()
    advisor = LanguageAdvisor(config.get('llm'))

    @asynccontextmanager
    async def lifespan(app):
        yield
        await advisor.close()
        memory.close()

    app = FastAPI(title='MineLife AI', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def protect(request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
            return JSONResponse({'detail': 'Origem não permitida'}, status_code=403)
        if request.url.path != '/health' and request.url.path != '/':
            auth = request.headers.get('authorization', '')
            if not hmac.compare_digest(auth, 'Bearer ' + config['token']):
                return JSONResponse({'detail': 'Token local necessário'}, status_code=401)
        if int(request.headers.get('content-length', '0')) > 262144:
            return JSONResponse({'detail': 'Mensagem grande demais'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/health')
    async def health():
        return {'service': 'MineLife AI', 'version': '0.2.0', 'protocol': 1,
                'features': BRIDGE_FEATURES, 'auto_publish': False}

    @app.get('/bridge/handshake')
    async def handshake():
        return {'protocol': 1, 'version': '0.2.0', 'transport': 'HTTP/1.1',
                'features': BRIDGE_FEATURES, 'heartbeat_ms': 250, 'lease_ms': 3000, 'actions': BRIDGE_ACTIONS}

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return (Path(__file__).parent / 'observer.html').read_text(encoding='utf-8')

    @app.get('/api/state')
    async def state():
        async with lock:
            return {**engine.snapshot(), 'llm': advisor.snapshot()}

    @app.post('/api/control/{action}')
    async def control(action: str):
        if action not in ('start', 'pause', 'resume', 'stop'):
            raise HTTPException(400, 'Ação inválida')
        async with lock:
            if not engine.snapshot()['connected']:
                raise HTTPException(409, 'Nenhum mundo conectado')
            if action in ('start', 'resume') and not engine.latest.armed:
                raise HTTPException(409, 'Autorize localmente com F8 no jogo')
            engine.control = action
            return {'queued': action}

    @app.post('/bridge/step')
    async def step(payload: Step):
        async with lock:
            try:
                engine.advice = advisor.result
                response = engine.step(payload)
                engine.record_advice(advisor.result)
                if payload.active and payload.armed and not payload.player.danger:
                    goals = engine.goals.rows(payload.world)
                    available=[{'subject':g['subject'],'description':g['description']} for g in goals if g['status']=='pending'][:8]
                    experiences=memory.rows('SELECT id,type,day,description,evidence FROM Events WHERE world=? AND verified=1 ORDER BY timestamp DESC LIMIT 8',(payload.world,))
                    cue=' '.join(g['description'] for g in available[:4])
                    recalled=engine.autobiography.recall(payload.world,cue,3) if cue else []
                    philosophical=memory.rows('SELECT theme,question,interpretation,origin_event FROM PhilosophicalQuestions WHERE world=? ORDER BY created DESC LIMIT 4',(payload.world,))
                    advisor.schedule({'world':payload.world, 'goals':available,
                                      'knowledge':memory.rows('SELECT subject,status FROM Knowledge WHERE world=? LIMIT 30',(payload.world,)),
                                      'experiences':experiences, 'source_event_ids':[e['id'] for e in experiences],
                                      'recalled_memories':[{'day':m['day'],'theme':m['theme'],'summary':m['summary']} for m in recalled],
                                      'philosophy':philosophical},'integrated')
                return response
            except ValueError as exc:
                memory.db.rollback()
                raise HTTPException(409, str(exc)) from exc

    return app


def main():
    import uvicorn
    app = create_app()
    # Nunca use 0.0.0.0: esta aplicação controla o personagem local.
    uvicorn.run(app, host='127.0.0.1', port=8765, http='h11', ws='none', access_log=False)


if __name__ == '__main__':
    main()
