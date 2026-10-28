"""Integração HTTP em socket loopback real, com mundo sintético e banco temporário.

Este teste não conecta ao Minecraft e não gera evidências de gameplay real.
"""
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
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
            server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
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
