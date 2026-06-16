# Qwen-3.5-9B with SGLang

This directory contains the necessary configurations to deploy the `Qwen/Qwen3.5-9B` model using `sglang` as the serving backend.

## Architectural Flow

The architecture is designed for robustness and scalability, handling requests in a staged process:

```
+-----------+      +----------------+      +-----------------+      +---------------------+
|   User    |----->|     NGINX      |----->|  FastAPI Gateway  |----->|   SGLang Server     |
|           |      | (Port 80)      |      |  (Port 9000)    |      | (Port 8000)         |
+-----------+      +----------------+      +-----------------+      +---------------------+
```

1.  **User Request**: The user sends a request to the NGINX proxy on port 80.
2.  **NGINX Proxy**: NGINX acts as a reverse proxy, handling SSL termination, rate limiting, and basic authentication before forwarding the request to the FastAPI gateway.
3.  **FastAPI Gateway**: This gateway service is responsible for routing requests to the correct model backend. It reads the `model` from the request payload and uses an internal mapping to determine the target SGLang server.
4.  **SGLang Server**: The SGLang server runs the `Qwen/Qwen3.5-9B` model, performs the inference, and streams the response back to the gateway.

## Component Descriptions

-   **NGINX (`nginx:latest`)**: The public-facing entry point. It provides a layer of security and control, including rate limiting (5 requests/second per IP) and API key authentication (`Bearer soyboy`).
-   **FastAPI Gateway (`gateway/`)**: A Python-based service that acts as a smart router. It determines which model server to forward the request to based on the `model` field in the JSON payload.
-   **SGLang Server (`lmsysorg/sglang:latest`)**: The core inference engine. It uses the `sglang` library to serve the `Qwen/Qwen3.5-9B` model, optimized for high-throughput and low-latency.

## Detailed File Descriptions

### `docker-compose.yml`

This file orchestrates the deployment of the three services.

-   **`sglang-qwen35-9B` service**:
    -   `image: lmsysorg/sglang:latest`: Uses the latest official SGLang image.
    -   `gpus: all`:  Assigns all available GPUs to the container.
    -   `environment`: Passes the Hugging Face token and other SGLang specific environment variables.
    -   `volumes`: Mounts the local Hugging Face cache to speed up model loading on subsequent runs.
    -   `command`: Specifies the model to load (`Qwen/Qwen3.5-9B`) and enables speculative decoding with the EAGLE algorithm.

-   **`gateway` service**:
    -   `build: ./gateway`: Builds the FastAPI gateway image from the `gateway` directory.
    -   `depends_on: - sglang-qwen35-9B`: Ensures that the SGLang server is started before the gateway.
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

-   **`MODEL_MAP`**: A dictionary that maps model names to their corresponding SGLang server URLs.
-   **`DEFAULT_MODEL`**: The default model to be used if the request does not specify a model.
-   **`lifespan` function**: Creates an `httpx.AsyncClient` for communication with the backend model servers.
-   **`proxy` function**: The main endpoint that handles all incoming requests, routing them to the correct model server.

## Speculative Decoding

This configuration uses speculative decoding with the **EAGLE** algorithm to accelerate inference.

-   `--speculative-algorithm EAGLE`: Specifies the EAGLE algorithm for speculative decoding.
-   `--speculative-num-steps 3`: The number of speculative steps.
-   `--speculative-eagle-topk 1`: The top-k candidates to consider for the EAGLE algorithm.
-   `--speculative-num-draft-tokens 4`: The number of draft tokens to generate.

Speculative decoding works by using a smaller, faster "draft" model to generate a sequence of draft tokens. The larger, more powerful "target" model then validates these tokens in parallel. This can lead to a significant speedup in inference time.

## Configuration

-   **`../.env`**: You must provide your Hugging Face token in the `.env` file in the parent directory.
    -   `HF_TOKEN`: Your Hugging Face access token.
-   **`./.env`**: This directory contains a `.env` file that can be used for SGLang specific configurations. For example, you can add `GPU_MEMORY_UTILIZATION` to control the GPU memory usage by the sglang server. By default, this file only contains the `HF_TOKEN`.
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
    "model": "Qwen/Qwen3.5-9B",
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
