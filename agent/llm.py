"""Conselheiro opcional, assíncrono. Nunca é executor nem fonte de fatos confirmados."""
import asyncio
import hashlib
import json
import os
import time
from urllib.parse import urlparse
import httpx


class LanguageAdvisor:
    PURPOSES = {'integrated', 'cognitive', 'philosophy', 'autobiography', 'goal', 'social'}
    TASK_RULES = {
        'integrated': 'Relacione as experiências recentes, questões e metas executáveis fornecidas.',
        'cognitive': 'Proponha uma pergunta e uma hipótese refutável sobre uma observação ainda não resolvida.',
        'philosophy': 'Proponha uma interpretação narrativa provisória ligada a uma evidência citada; não produza monólogo privado.',
        'autobiography': 'Sugira um rascunho em primeira pessoa somente sobre experiências e lembranças fornecidas.',
        'goal': 'Escolha somente entre subjects existentes na lista de metas e explique preferência de alto nível.',
        'social': 'Interprete apenas metadados sociais observados; não afirme conversa, amizade, romance ou parentesco não registrados.'}

    def __init__(self, config=None, transport=None):
        self.config = config or {}
        self.transport = transport
        self.task = None
        self.last_call = -1e30
        self.calls = []
        self.cache = {}
        self.result = None
        self.status = 'disabled'
        self.error = None

    def schedule(self, context, purpose='integrated'):
        if self.config.get('provider', 'none') == 'none': return
        if purpose not in self.PURPOSES: raise ValueError('Tarefa de raciocínio desconhecida')
        if self.task and not self.task.done(): return
        current = time.monotonic()
        self.calls = [v for v in self.calls if current-v < 3600]
        if current-self.last_call < max(30, self.config.get('interval_seconds',60)) or len(self.calls)>=min(60,self.config.get('calls_per_hour',12)): return
        key = hashlib.sha256((purpose + json.dumps(context,sort_keys=True)).encode()).hexdigest()
        if key in self.cache:
            self.result = self.cache[key];self.status='cached';return
        self.last_call=current;self.calls.append(current)
        self.task=asyncio.create_task(self._run(context,key,purpose))

    async def _run(self, context, key, purpose):
        self.status='thinking'
        try:
            provider=self.config['provider']
            base=self.config.get('base_url','http://127.0.0.1:11434' if provider=='ollama' else 'https://api.openai.com/v1').rstrip('/')
            parsed=urlparse(base)
            if parsed.username or parsed.password or (parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost')):
                raise ValueError('Endpoint deve usar HTTPS ou loopback')
            model=self.config.get('model')
            if not model: raise ValueError('Configure o nome do modelo instalado/disponível')
            messages=[{'role':'system','content':
                       'Você auxilia um personagem artificial fictício no Minecraft. '+self.TASK_RULES[purpose]+' '
                       'Responda somente JSON com preferred_subject (nulo ou um subject exato da lista goals), '
                       'question, hypothesis, interpretation, reflection, journal_draft e social_interpretation. '
                       'Separe interpretação e hipótese de fatos. Nunca afirme que ação ocorreu sem evidência explícita. '
                       'Não declare crafting, coleta, visita, relação, morte, construção ou resultado não incluído na memória. '
                       'Não emita comandos físicos, código, segredos ou caminhos locais. Use primeira pessoa somente como narrativa simulada.'},
                      {'role':'user','content':json.dumps(context,ensure_ascii=False)[:10000]}]
            limit=min(1024,max(64,self.config.get('max_output_tokens',384)))
            headers={}
            if provider=='ollama':
                url=base+'/api/chat'
                payload=dict(model=model,messages=messages,stream=False,format='json',options={'num_predict':limit,'num_ctx':4096},keep_alive='2m')
            elif provider=='openai_compatible':
                url=base+'/chat/completions'
                secret=os.environ.get(self.config.get('api_key_env','MINELIFE_LLM_API_KEY'),'')
                if secret: headers['Authorization']='Bearer '+secret
                payload=dict(model=model,messages=messages,max_completion_tokens=limit)
            else: raise ValueError('Provedor desconhecido')
            async with httpx.AsyncClient(timeout=15,transport=self.transport,follow_redirects=False,trust_env=False) as client:
                response=await client.post(url,headers=headers,json=payload)
                response.raise_for_status()
                if len(response.content)>65536: raise ValueError('Resposta excessiva')
                data=response.json()
            content=data['message']['content'] if provider=='ollama' else data['choices'][0]['message']['content']
            value=json.loads(content)
            allowed={g['subject'] for g in context.get('goals',[])}
            preferred=value.get('preferred_subject')
            if preferred not in allowed: preferred=None
            # Texto livre é mantido como sugestão NÃO VERIFICADA, fora do Knowledge/Journal factual.
            self.result={'world':context['world'],'preferred_subject':preferred,'purpose':purpose,
                         'source_event_ids':[str(x) for x in context.get('source_event_ids',[])[:12]],
                         **{k:str(value.get(k,''))[:1000] for k in ('question','hypothesis','interpretation','reflection','journal_draft','social_interpretation')}}
            self.cache[key]=self.result
            if len(self.cache)>32: self.cache.pop(next(iter(self.cache)))
            self.status='ready';self.error=None
        except Exception as exc:
            self.status='fallback';self.error=type(exc).__name__;self.result=None

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass

    def snapshot(self):
        return {'status':self.status,'error':self.error,'calls_last_hour':len(self.calls),'suggestion_unverified':self.result}
