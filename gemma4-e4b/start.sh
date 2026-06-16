#!/bin/bash
set -e

PARSER=/usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/gemma4_tool_parser.py

sed -i 's/from vllm.tool_parsers.abstract_tool_parser import ToolParser/from vllm.tool_parsers.abstract_tool_parser import Tool, ToolParser/' $PARSER
sed -i 's/def __init__(self, tokenizer: TokenizerLike):/def __init__(self, tokenizer: TokenizerLike, tools: list[Tool] | None = None):/' $PARSER
sed -i 's/super().__init__(tokenizer)/super().__init__(tokenizer, tools)/' $PARSER

exec python3 -m vllm.entrypoints.openai.api_server \
  --model google/gemma-4-E4B-it \
  --language-model-only \
  --enable-auto-tool-choice \
  --tool-call-parser gemma4 \
  --chat-template /app/chat_template.jinja \
  --performance-mode interactivity \
  --host 0.0.0.0 \
  --port 8000 \
  --gpu-memory-utilization 0.90 \
  --max-num-batched-tokens 512 \
  --max-num-seqs 16 \
  --kv-cache-dtype fp8 \
  --max-model-len 14160
