# Gemma 4 - 4B Parameter Model (`gemma4-e4b`)

This directory contains the necessary configurations to deploy the `gemma4-e4b` model using `sglang` for serving, with an NGINX reverse proxy and a FastAPI gateway.

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
4.  **SGLang Server**: The SGLang server runs the `gemma4-e4b` model, performs the inference, and streams the response back to the gateway.

## Component Descriptions

-   **NGINX (`nginx:latest`)**: The public-facing entry point. It provides a layer of security and control, including rate limiting (5 requests/second per IP) and API key authentication (`Bearer soyboy`).
-   **FastAPI Gateway (`gateway/`)**: A Python-based service that acts as a smart router. It determines which model server to forward the request to based on the `model` field in the JSON payload. This allows for a multi-model serving setup behind a single API endpoint.
-   **SGLang Server (`lmsysorg/sglang:gemma4`)**: The core inference engine. It uses the `sglang` library to serve the `gemma4-e4b` model, optimized for high-throughput and low-latency.

## Detailed File Descriptions

### `docker-compose.yml`

This file orchestrates the deployment of the three services.

-   **`sglang-gemma4-e4b` service**:
    -   `image: lmsysorg/sglang:gemma4`: Uses the official SGLang image for Gemma 4.
    -   `gpus: all`:  Assigns all available GPUs to the container.
    -   `ports: - "8000:8000"`: Exposes the SGLang server on port 8000.
    -   `environment: - HF_TOKEN=${HF_TOKEN}`: Passes the Hugging Face token from the `.env` file.
    -   `volumes`: Mounts the local Hugging Face cache to speed up model loading on subsequent runs.
    -   `command`: Specifies the model to load (`google/gemma-4-E4B-it`) and other SGLang server parameters.
-   **`gateway` service**:
    -   `build: ./gateway`: Builds the FastAPI gateway image from the `gateway` directory.
    -   `depends_on: - sglang-gemma4-e4b`: Ensures that the SGLang server is started before the gateway.
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

-   **`MODEL_MAP`**: A dictionary that maps model names to their corresponding SGLang server URLs. This allows the gateway to route requests to different models.
-   **`lifespan` function**: Creates an `httpx.AsyncClient` with aggressive connection pooling for efficient communication with the backend model servers.
-   **`get_forwardable_headers` function**: Cleans up incoming headers, removing hop-by-hop headers and preserving the original client IP address for traceability.
-   **`proxy` function**: This is the main endpoint that handles all incoming requests.
    1.  It peeks into the request body to get the `model` name.
    2.  It uses the `MODEL_MAP` to find the target SGLang server.
    3.  If the model is not found, it returns a 400 error.
    4.  It builds a new request and streams it to the target model server using the `httpx` client.
    5.  It then streams the response from the model server back to the client.

## Configuration

-   **`.env`**: You must provide your Hugging Face token in this file to allow the SGLang server to download the model from the Hugging Face Hub.
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
    "model": "google/gemma-4-E4B-it",
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
