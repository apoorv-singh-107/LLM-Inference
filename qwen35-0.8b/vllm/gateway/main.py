import logging
import orjson
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
import httpx

logger = logging.getLogger(__name__)

# Internal routing table
MODEL_MAP = {
    "Qwen/Qwen3.5-0.8B": "http://vllm-qwen35-0.8b:8000",
}
DEFAULT_MODEL = "Qwen/Qwen3.5-0.8B"

http_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Aggressive connection pooling for internal cluster traffic
    limits = httpx.Limits(max_keepalive_connections=500, max_connections=5000)
    global http_client
    http_client = httpx.AsyncClient(timeout=None, limits=limits)
    yield
    await http_client.aclose()


app = FastAPI(lifespan=lifespan)

# Standard hop-by-hop headers to strip
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def get_forwardable_headers(request: Request) -> dict:
    """Clean headers and maintain client IP traceability from Nginx."""
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS
    }
    # Ensure Nginx's original client IP is passed down to vLLM
    if "x-real-ip" in request.headers:
        headers["x-forwarded-for"] = request.headers["x-real-ip"]
    return headers


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, full_path: str):
    body_bytes = await request.body()
    target_base = None

    # Fast-path routing: Peek at the model using orjson
    if request.method in ["POST", "PUT"] and body_bytes:
        try:
            payload = orjson.loads(body_bytes)
            model = payload.get("model", DEFAULT_MODEL)
            target_base = MODEL_MAP.get(model)

            if not target_base:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": f"Model '{model}' not found in routing table.",
                            "type": "invalid_request_error",
                            "param": "model",
                            "code": "model_not_found",
                        }
                    },
                )
        except orjson.JSONDecodeError:
            pass

    # Fallback for GET requests (like /v1/models)
    if not target_base:
        target_base = MODEL_MAP[DEFAULT_MODEL]

    target_url = f"{target_base.rstrip('/')}/{full_path}"

    upstream_req = http_client.build_request(
        method=request.method,
        url=target_url,
        headers=get_forwardable_headers(request),
        content=body_bytes,
        params=request.query_params,
    )

    try:
        upstream_resp = await http_client.send(upstream_req, stream=True)
    except httpx.RequestError as e:
        logger.error(f"vLLM upstream failed: {e}")
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "Inference engine offline.",
                    "type": "server_error",
                }
            },
        )

    resp_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }

    # Crucial for Nginx SSE passthrough
    if "text/event-stream" in resp_headers.get("content-type", ""):
        resp_headers["X-Accel-Buffering"] = "no"

    return StreamingResponse(
        upstream_resp.aiter_raw(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        background=BackgroundTask(upstream_resp.aclose),
    )
