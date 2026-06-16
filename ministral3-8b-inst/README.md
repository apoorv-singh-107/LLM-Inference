# Ministral-8B-Instruct Model

This directory contains the necessary configurations to deploy the `ministral3-8b-inst` model using `vllm` as the serving backend.

## Architectural Flow

The architecture is designed for robustness and scalability, handling requests in a staged process:

```
+-----------+      +----------------+      +-----------------+      +---------------------+
|   User    |----->|     NGINX      |----->|  FastAPI Gateway  |----->|    vLLM Server      |
|           |      | (Port 80)      |      |  (Port 9000)    |      | (Port 8000)         |
+-----------+      +----------------+      +-----------------+      +---------------------+
```

1.  **User Request**: The user sends a request to the NGINX proxy on port 80.
2.  **NGINX Proxy**: NGINX acts as a reverse proxy, handling SSL termination, rate limiting, and basic authentication before forwarding the request to the FastAPI gateway.
3.  **FastAPI Gateway**: This gateway service is responsible for routing requests to the correct model backend. It reads the `model` from the request payload and uses an internal mapping to determine the target vLLM server.
4.  **vLLM Server**: The vLLM server runs the `ministral3-8b-inst` model, performs the inference, and streams the response back to the gateway.

## Component Descriptions

-   **NGINX (`nginx:latest`)**: The public-facing entry point. It provides a layer of security and control, including rate limiting (5 requests/second per IP) and API key authentication (`Bearer soyboy`).
-   **FastAPI Gateway (`gateway/`)**: A Python-based service that acts as a smart router. It determines which model server to forward the request to based on the `model` field in the JSON payload. This allows for a multi-model serving setup behind a single API endpoint.
-   **vLLM Server (`vllm/vllm-openai:latest`)**: The core inference engine. It uses the `vllm` library to serve the `ministral3-8b-inst` model, optimized for high-throughput and low-latency.

## Detailed File Descriptions

### `docker-compose.yml`

This file orchestrates the deployment of the three services.

-   **`vllm-ministral3-8b-inst` service**:
    -   `image: vllm/vllm-openai:latest`: Uses the official vLLM OpenAI-compatible server image.
    -   `gpus: all`:  Assigns all available GPUs to the container.
    -   `environment: - HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}`: Passes the Hugging Face token from the `.env` file.
    -   `volumes`: Mounts the local Hugging Face cache to speed up model loading on subsequent runs.
    -   `command`: Specifies the model to load (`mistralai/Ministral-3-8B-Instruct-2512`) and other vLLM server parameters, such as `gpu-memory-utilization`, `max-model-len`, etc.
-   **`gateway` service**:
    -   `build: ./gateway`: Builds the FastAPI gateway image from the `gateway` directory.
    -   `depends_on: - vllm-ministral3-8b-inst`: Ensures that the vLLM server is started before the gateway.
-   **`nginx` service**:
    -   `image: nginx:latest`: Uses the official NGINX image.
    -   `ports: - "80:80"`: Exposes the NGINX proxy on port 80.
    -   `volumes: - ./nginx.conf:/etc/nginx/nginx.conf:ro`: Mounts the NGINX configuration file in read-only mode.
    -   `depends_on: - gateway`: Ensures that the gateway is started before NGINX.

### `nginx.conf`

This file configures NGINX as a reverse proxy.

-   `limit_req_zone`: Sets up a rate-limiting zone named `api_limit` that allows 5 requests per second from a single IP address.
-   `map $http_authorization $auth_ok`: Creates a mapping to check if the `Authorization` header contains the correct Bearer token (`soyboy`).
-   `server` block:
    -   `listen 80`: Listens on port 80.
    -   `limit_req`: Applies the rate limiting defined earlier.
    -   `location /`:
        -   `if ($auth_ok = 0)`: Checks the authentication status and returns a `401 Unauthorized` error if the token is invalid.
        -   `proxy_pass http://gateway:9000`: Forwards valid requests to the `gateway` service on port 9000.
        -   `proxy_set_header`: Forwards necessary headers to the gateway and sets headers for streaming responses.

### `gateway/main.py`

This is the Python script for the FastAPI gateway.

-   **`MODEL_MAP`**: A dictionary that maps model names to their corresponding vLLM server URLs. This allows the gateway to route requests to different models.
-   **`DEFAULT_MODEL`**: The default model to be used if the request does not specify a model. This has been corrected to `mistralai/Ministral-3-8B-Instruct-2512`.
-   **`lifespan` function**: Creates an `httpx.AsyncClient` with aggressive connection pooling for efficient communication with the backend model servers.
-   **`get_forwardable_headers` function**: Cleans up incoming headers, removing hop-by-hop headers and preserving the original client IP address for traceability.
-   **`proxy` function**: This is the main endpoint that handles all incoming requests.
    1.  It peeks into the request body to get the `model` name.
    2.  It uses the `MODEL_MAP` to find the target vLLM server.
    3.  If the model is not found, it returns a 400 error.
    4.  It builds a new request and streams it to the target model server using the `httpx` client.
    5.  It then streams the response from the model server back to the client.

## Configuration

-   **`.env`**: You must provide your Hugging Face token in this file to allow the vLLM server to download the model from the Hugging Face Hub.
    -   `HF_TOKEN`: Your Hugging Face access token.
-   **`nginx.conf`**: The API key is hardcoded in this file (`Bearer soyboy`). You can change this to a more secure key in the `map` block.

## Deployment

To deploy the model, run the following command from this directory:

```bash
docker-compose up -d
```

This will build the gateway image and start all three services in the background.

## Usage

Once the services are running, you can interact with the model through the gateway, which is exposed on port `80` by default.

You must include the `Authorization` header with the correct bearer token.

### Example Request

```bash
curl -X POST http://localhost/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer soyboy" -d '{
    "model": "mistralai/Ministral-3-8B-Instruct-2512",
    "messages": [
        {
            "role": "user",
            "content": "What is the capital of France?"
        }
    ],
    "stream": true
}'
```

### Response (Streaming)

The response will be a stream of server-sent events (SSE). Each event will contain a chunk of the generated text.

## Stopping the Services

To stop the services, run:

```bash
docker-compose down
```
