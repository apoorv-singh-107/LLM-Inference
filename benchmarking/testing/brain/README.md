# Infrastructure and Model Testing

This directory contains a suite of Python scripts designed for comprehensive testing and benchmarking of the AI service and its underlying gateway infrastructure. The scripts cover everything from model performance evaluation to infrastructure robustness and security.

## Scripts

### `benchmark_runner.py`

A general-purpose script for benchmarking the performance and output of various models through the `/generative_response` SSE endpoint. It sends questions from an Excel file and records key metrics.

-   **Functionality**: Measures latency (total time, time to first token), throughput (tokens/second), token usage, and high-level agentic behavior (tool calls).
-   **Output**: Generates a `benchmark_results.xlsx` file summarizing the performance for each question.

### `test_gateway.py`

A powerful and comprehensive testing suite focused on the **LLM Gateway's infrastructure**, not the model's intelligence. It is designed to ensure the gateway is robust, secure, and performs well under pressure.

-   **Test Suites Included**:
    -   **Authentication**: Checks for correct handling of valid, invalid, and malformed API keys.
    -   **Rate Limiting**: Verifies that the leaky bucket rate limiter correctly throttles requests during bursts and allows recovery.
    -   **Model Routing**: Ensures the gateway correctly routes requests to the specified model and handles requests for unknown models gracefully.
    -   **Concurrency & Load Testing**: Assesses the gateway's performance under high numbers of simultaneous requests.
    -   **Stress Testing**: Measures the gateway's stability under a sustained high rate of requests per second (RPS).
    -   **Security**: Includes a wide array of security checks, such as prompt injection attempts, oversized payloads, HTTP header injection, path traversal, and Slowloris DoS simulation.
    -   **DDoS Simulation**: Tests the gateway's resilience to Denial-of-Service attacks and its configuration regarding `X-Forwarded-For` headers.
-   **Output**: Produces a detailed, multi-sheet `gateway_test_results.xlsx` report with summaries for each test suite.

### `replay_analyzer.py`

A utility script for **offline analysis** of saved SSE (Server-Sent Events) response files. This is primarily a debugging tool to inspect the event stream from a previous benchmark run without having to connect to the live endpoint.

-   **Functionality**: Parses a raw SSE event file and prints a structured analysis, including:
    -   Event type distribution.
    -   A trace of all agentic steps and tool calls.
    -   Token usage statistics.
    -   The final assembled response.
-   **Usage**: `python replay_analyzer.py <path_to_sse_file> [question_text]`

## Common Files

-   `slm_exploration.xlsx`: The standard input file used by the benchmark runners, containing the questions, complexities, and other metadata for the test cases.
