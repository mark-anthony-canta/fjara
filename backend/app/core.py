import os
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()
DIMENSIONS = 768
COLLECTION = os.getenv("QDRANT_COLLECTION", "fjara_knowledge_v1")
QDRANT = os.getenv("QDRANT_URL", "http://localhost:16333").rstrip("/")


class ProviderError(RuntimeError):
    def __init__(self, host: str, status: int):
        self.status = status
        super().__init__(f"{host} returned HTTP {status}")


def key(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in .env before ingestion")
    return value


def validate_source(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.skatturinn.is"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Sources must be HTTPS pages on www.skatturinn.is")
    return url


def chunks(text: str, size: int = 2400, overlap: int = 300) -> list[str]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Invalid chunk size or overlap")
    text = text.strip()
    result = []
    for start in range(0, len(text), size - overlap):
        result.append(text[start:start + size])
        if start + size >= len(text):
            break
    return result


async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    response = await client.request(method, url, **kwargs)
    # Never propagate response bodies or request headers into logs (secrets).
    if response.is_error:
        raise ProviderError(urlparse(url).hostname, response.status_code)
    return response.json()


async def embed(client: httpx.AsyncClient, text: str, task: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    data = await request(client, "POST",
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent",
        headers={"x-goog-api-key": key("GEMINI_API_KEY")},
        json={"model": f"models/{model}", "content": {"parts": [{"text": text}]},
              "taskType": task, "outputDimensionality": DIMENSIONS})
    vector = data["embedding"]["values"]
    if len(vector) != DIMENSIONS:
        raise ValueError("Unexpected embedding dimensions")
    return vector
