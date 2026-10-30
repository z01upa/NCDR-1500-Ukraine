from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

class OllamaError(RuntimeError):
    pass

class OllamaClient:
    def __init__(self,model:str,base_url:str="http://127.0.0.1:11434",timeout:int=90):
        self.model=model
        self.base_url=base_url.rstrip("/")
        self.timeout=timeout

    def _request(self,path:str,body:dict|None=None):
        data=json.dumps(body).encode("utf-8") if body is not None else None
        req=urllib.request.Request(self.base_url+path,data=data,headers={"Content-Type":"application/json"} if data else {})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaError(f"Ollama local API unavailable at {self.base_url}: {exc}") from exc
        except TimeoutError as exc:
            raise OllamaError(f"Ollama did not respond within {self.timeout}s") from exc

    def model_available(self)->bool:
        try:
            result=self._request("/api/tags")
            names={row.get("name","") for row in result.get("models",[])}
            return self.model in names
        except OllamaError:
            return False

    def chat_json(self,system_prompt:str,user_prompt:str,max_output_tokens:int=512)->tuple[str,dict]:
        payload={
            "model":self.model,
            "messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
            "format":"json",
            "stream":False,
            "think":False,
            "keep_alive":"60s",
            "options":{"temperature":0,"num_ctx":4096,"num_predict":max_output_tokens},
        }
        last=None
        for attempt in range(2):
            try:
                response=self._request("/api/chat",payload)
                content=response.get("message",{}).get("content","")
                if not content: raise OllamaError("Ollama returned an empty message")
                try: parsed=json.loads(content)
                except json.JSONDecodeError as exc: raise OllamaError(f"Qwen response was not valid JSON: {exc}") from exc
                return content,parsed
            except OllamaError as exc:
                last=exc
                if attempt<1: time.sleep(1)
        raise last or OllamaError("Ollama request failed")

    def unload(self)->None:
        self._request("/api/generate",{"model":self.model,"prompt":"","stream":False,"keep_alive":0,
                                       "options":{"num_predict":1}})
