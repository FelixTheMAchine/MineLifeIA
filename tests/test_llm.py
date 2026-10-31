import asyncio
import json
import unittest
import httpx
from agent.llm import LanguageAdvisor


class AdvisorTest(unittest.IsolatedAsyncioTestCase):
    async def test_optional_adapter_cache_and_no_physical_commands(self):
        requests=[]
        def respond(request):
            requests.append(request)
            if request.method=='GET':return httpx.Response(200,json={'models':[{'name':'fixture'}]})
            return httpx.Response(200,json={'message':{'content':json.dumps({'preferred_subject':'unsafe-unknown','question':'O que posso testar?','reflection':'uma sugestão'})}})
        advisor=LanguageAdvisor({'provider':'ollama','model':'fixture','calls_per_hour':1},httpx.MockTransport(respond))
        context={'world':'a'*64,'goals':[{'subject':'observe:stone'}],'knowledge':[]}
        advisor.schedule(context)
        await advisor.task
        self.assertIsNone(advisor.result['preferred_subject'])
        self.assertEqual(advisor.status,'ready')
        advisor.schedule(context)
        self.assertEqual(len(requests),2)
        self.assertNotIn('command',advisor.result)
        await advisor.close()

    async def test_failure_falls_back_without_crashing_cognition(self):
        advisor=LanguageAdvisor({'provider':'openai_compatible','model':'fixture'},httpx.MockTransport(lambda r:httpx.Response(503)))
        advisor.schedule({'world':'a'*64,'goals':[]})
        await advisor.task
        self.assertEqual(advisor.status,'fallback')
        self.assertIsNone(advisor.result)

    async def test_disabled_makes_no_network_call(self):
        advisor=LanguageAdvisor()
        advisor.schedule({'world':'a'*64})
        self.assertIsNone(advisor.task)

    async def test_missing_local_model_does_not_start_inference_or_download(self):
        calls=[]
        def response(r):calls.append(r);return httpx.Response(200,json={'models':[]})
        advisor=LanguageAdvisor({'provider':'ollama','model':'missing'},httpx.MockTransport(response))
        advisor.schedule({'world':'a'*64,'goals':[]});await advisor.task
        self.assertEqual(advisor.status,'fallback')
        self.assertEqual([r.method for r in calls],['GET'])

    async def test_structured_proposal_keeps_untrusted_text_separate_and_delivers_once(self):
        def response(r):
            return httpx.Response(200,json={'models':[{'name':'fixture'}]}) if r.method=='GET' else httpx.Response(200,json={'message':{'content':json.dumps(dict(
                proposal=dict(intent='study_material',evidence_ids=['fact']),claims=[dict(event_id='fact')],journal_draft='Texto não verificado.'))}})
        advisor=LanguageAdvisor({'provider':'ollama','model':'fixture'},httpx.MockTransport(response))
        advisor.schedule({'world':'a'*64,'goals':[],'source_event_ids':['fact']});await advisor.task
        self.assertEqual(advisor.take_result()['proposal']['intent'],'study_material')
        self.assertIsNone(advisor.take_result())
        self.assertEqual(advisor.result['journal_draft'],'Texto não verificado.')
