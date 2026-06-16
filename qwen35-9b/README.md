# Qwen-3.5-9B Model

This directory serves as a container for deploying the `qwen35-9b` model using different serving technologies.

## Architectural Overview

The deployment architecture for this model is modular, with different serving backends available in subdirectories. Each subdirectory contains a complete setup for a specific serving technology, including a model server, a gateway, and a reverse proxy.

The detailed architectural flow and component descriptions are provided in the `README.md` file within each serving technology's subdirectory.

### Available Serving Technologies:

-   **`vllm/`**: Provides a setup for deploying the model using **vLLM**, an engine for fast LLM inference and serving.
-   **`sglang/`**: Provides a setup for deploying the model using **SGLang**, a structured generation language for large language models.

## Deployment

To deploy the model, you must first choose a serving technology and then navigate to the corresponding subdirectory.

### Example: Deploying with vLLM

1.  **Navigate to the vLLM directory:**
    ```bash
    cd vllm
    ```
2.  **Follow the instructions:**
    - Open the `README.md` file in the `vllm` directory for detailed instructions on configuration and deployment.

### Example: Deploying with SGLang

1.  **Navigate to the SGLang directory:**
    ```bash
    cd sglang
    ```
2.  **Follow the instructions:**
    - Open the `README.md` file in the `sglang` directory for detailed instructions on configuration and deployment.

## General Prerequisites

-   Docker
-   Docker Compose
