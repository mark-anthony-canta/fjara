"""Cached document embeddings for large imports; cache stays in ignored data/."""
import asyncio
import hashlib
import json
import math
import os
import httpx
from pathlib import Path
from .core import DIMENSIONS, ProviderError, key, request


def validate_vectors(vectors, expected):
    if len(vectors) != expected or any(len(v) != DIMENSIONS or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('Invalid embedding batch response')


async def embed_cached(client, texts, batch_size=16, cache_dir=Path('data/embedding-cache')):
    model=os.getenv('GEMINI_EMBEDDING_MODEL','gemini-embedding-001')
    cache_dir.mkdir(parents=True,exist_ok=True)
    vectors=[None]*len(texts); missing=[]
    for i,text in enumerate(texts):
        digest=hashlib.sha256(json.dumps([model,DIMENSIONS,'RETRIEVAL_DOCUMENT',text],ensure_ascii=False).encode()).hexdigest()
        path=cache_dir/f'{digest}.json'
        if path.exists():
            vector=json.loads(path.read_text(encoding='utf-8'))
            validate_vectors([vector],1); vectors[i]=vector
        else: missing.append((i,text,path))
    for start in range(0,len(missing),batch_size):
        batch=missing[start:start+batch_size]
        body={'requests':[{'model':f'models/{model}','content':{'parts':[{'text':text}]},'taskType':'RETRIEVAL_DOCUMENT','outputDimensionality':DIMENSIONS} for _,text,_ in batch]}
        for attempt in range(4):
            try:
                response=await request(client,'POST',f'https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents',headers={'x-goog-api-key':key('GEMINI_API_KEY')},json=body)
                break
            except ProviderError as exc:
                if exc.status not in (429,500,502,503,504) or attempt==3: raise
                delay=60 if exc.status==429 else 5*(attempt+1)
                print(f'Embedding provider HTTP {exc.status}; waiting {delay} seconds before resuming cached batch.',flush=True)
                await asyncio.sleep(delay)
            except httpx.TransportError:
                if attempt==3: raise
                print('Embedding connection interrupted; retrying cached batch.',flush=True)
                await asyncio.sleep(5*(attempt+1))
        received=[entry['values'] for entry in response['embeddings']]
        validate_vectors(received,len(batch))
        for (index,_,path),vector in zip(batch,received):
            temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(vector),encoding='utf-8'); temporary.replace(path)
            vectors[index]=vector
    return vectors
