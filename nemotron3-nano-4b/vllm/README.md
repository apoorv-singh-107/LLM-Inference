# NVIDIA-Nemotron-3-Nano-4B-BF16 with vLLM

This directory contains the necessary configurations to deploy the `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` model using `vllm` as the serving backend.

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
4.  **vLLM Server**: The vLLM server runs the `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` model, performs the inference, and streams the response back to the gateway.

## Component Descriptions

-   **NGINX (`nginx:latest`)**: The public-facing entry point. It provides a layer of security and control, including rate limiting (5 requests/second per IP) and API key authentication (`Bearer soyboy`).
-   **FastAPI Gateway (`gateway/`)**: A Python-based service that acts as a smart router. It determines which model server to forward the request to based on the `model` field in the JSON payload.
-   **vLLM Server (`vllm/vllm-openai:v0.17.0`)**: The core inference engine. It uses the `vllm` library to serve the `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` model, optimized for high-throughput and low-latency. This setup uses a custom reasoning parser plugin (`nano_v3_reasoning_parser.py`).

## Detailed File Descriptions

### `docker-compose.yml`

This file orchestrates the deployment of the three services.

-   **`vllm-nemotron3-nano-4b` service**:
    -   `image: vllm/vllm-openai:v0.17.0`: Uses a specific version of the vLLM OpenAI-compatible server image.
    -   `gpus: all`:  Assigns all available GPUs to the container.
    -   `volumes`: Mounts the local Hugging Face cache and the custom reasoning parser (`nano_v3_reasoning_parser.py`) into the container.
    -   `command`: Specifies the model to load (`nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16`), the served model name (`nemotron3-nano-4B-BF16`), and other vLLM server parameters. It also specifies the custom reasoning parser to be used.
-   **`gateway` service**:
    -   `build: ./gateway`: Builds the FastAPI gateway image from the `gateway` directory.
    -   `depends_on: - vllm-nemotron3-nano-4b`: Ensures that the vLLM server is started before the gateway.
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

-   **`MODEL_MAP`**: A dictionary that maps model names to their corresponding vLLM server URLs. The key is the full Hugging Face model ID.
-   **`DEFAULT_MODEL`**: The default model to be used if the request does not specify a model.
-   **`lifespan` function**: Creates an `httpx.AsyncClient` for communication with the backend model servers.
-   **`proxy` function**: The main endpoint that handles all incoming requests, routing them to the correct model server.

### `nano_v3_reasoning_parser.py`

This file contains a custom reasoning parser for the Nemotron-3 model, which inherits from the `DeepSeekR1ReasoningParser`. It is used to extract the reasoning part from the model's output.

## Configuration

-   **`.env`**: You must provide your Hugging Face token in the `.env` file in the parent directory.
    -   `HF_TOKEN`: Your Hugging Face access token.
-   **`nginx.conf`**: The API key is hardcoded (`Bearer soyboy`).

## Deployment

To deploy the model, run the following command from this directory:

```bash
docker-compose up -d
```

## Usage

Once the services are running, you can interact with the model through the gateway on port `80`.

### Example Request

```bash
curl -X POST http://localhost/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer soyboy" -d '{
    "model": "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
    "messages": [
        {
            "role": "user",
            "content": "What is the capital of France?"
        }
    ],
    "stream": true
}'
```

## Stopping the Services

To stop the services, run:

```bash
docker-compose down
```
