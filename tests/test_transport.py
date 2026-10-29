"""Integração HTTP em socket loopback real, com mundo sintético e banco temporário.

Este teste não conecta ao Minecraft e não gera evidências de gameplay real.
"""
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import os
import subprocess
import shutil
from uuid import uuid4
import httpx
import uvicorn
from agent.main import create_app


class TransportTest(unittest.TestCase):
    def test_real_loopback_request_and_result_ack(self):
        with tempfile.TemporaryDirectory() as td:
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            app = create_app(Path(td), {'token': 'test-secret-' * 4})
            server = uvicorn.Server(uvicorn.Config(app, http='h11', ws='none', log_level='error', access_log=False))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=2) as client:
                    self.assertEqual(client.get('/health').status_code, 200)
                    self.assertEqual(client.get('/api/state').status_code, 401)
                    headers = {'Authorization': 'Bearer ' + 'test-secret-' * 4}
                    handshake = client.get('/bridge/handshake', headers=headers)
                    self.assertEqual(handshake.status_code, 200)
                    self.assertIn('workstations-v1', handshake.json()['features'])
                    self.assertTrue({'place', 'craft_table', 'eat', 'pickup', 'harvest', 'sleep'} <= set(handshake.json()['actions']))
                    self.assertIn('workstations-v1', client.get('/health').json()['features'])
                    body = dict(protocol=1, session=str(uuid4()), world='c' * 64,
                                dimension='minecraft:overworld', seq=1, day=1, time=2000,
                                active=True, armed=True, results=[],
                                player=dict(x=0, y=64, z=0, health=20, food=20, danger=False, inventory={}),
                                blocks=[dict(x=2, y=64, z=0, id='minecraft:oak_log', log=True)])
                    response = client.post('/bridge/step', headers=headers, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    command = response.json()['command']
                    self.assertEqual(command['action'], 'approach')
                    body['seq'] = 2
                    body['results'] = [dict(id=command['id'], status='failed', reason='synthetic_transport_test', evidence={})]
                    response = client.post('/bridge/step', headers=headers, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn(command['id'], response.json()['ack'])
                    self.assertEqual(client.post('/bridge/step', headers=headers, json=body).status_code, 409)
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                sock.close()
            self.assertFalse(thread.is_alive())

    def test_java_http11_handshake_and_observation_command_exchange(self):
        root=Path(__file__).resolve().parents[1]
        classes=root/'mod/build/classes/java/test'
        if not shutil.which('java') or not (classes/'ai/minelife/BridgeContractTest.class').exists():
            self.skipTest('Compile o mod antes para executar o teste de transporte Java')
        with tempfile.TemporaryDirectory() as td:
            sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            app=create_app(Path(td),{'token':'transport-fixture'})
            versions=[]
            @app.middleware('http')
            async def capture(request,call_next):
                versions.append((request.scope['http_version'],request.headers.get('upgrade')))
                return await call_next(request)
            server=uvicorn.Server(uvicorn.Config(app,http='h11',ws='none',log_level='error',access_log=False))
            thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
            try:
                deadline=time.monotonic()+5
                while not server.started and time.monotonic()<deadline:time.sleep(.02)
                run=subprocess.run(['java','-cp',str(classes),'ai.minelife.BridgeContractTest',f'http://127.0.0.1:{port}'],capture_output=True,text=True,timeout=15)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual(versions,[('1.1',None),('1.1',None)])
            finally:
                server.should_exit=True;thread.join(5);sock.close()
