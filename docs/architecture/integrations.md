# Integrations Blueprint

## LiteLLM Integration

- All LLM execution routes through LiteLLM (`/v1/chat/completions`).
- Model aliases and provider backends are configured in
  `deploy/docker/litellm_config.yaml`.
- Worker fallback chain defaults to:
  1. `openai/gpt-4o-mini`
  2. `vllm/meta-llama/Llama-3.1-8B-Instruct`
  3. `ollama/llama3.1:8b`

## Ollama Integration

- Ollama runs as local service on `http://ollama:11434`.
- Best for development, local inference, and data-resident workloads.
- Exposed via LiteLLM alias `ollama-llama3.1`.

## vLLM Integration

- vLLM runs OpenAI-compatible API endpoint at `http://vllm:8000/v1`.
- Intended for higher throughput/self-hosted serving.
- Exposed via LiteLLM alias `vllm-llama3.1`.

## Langfuse Integration

- Worker activities open a tracing span per node execution.
- Trace IDs are attached to run records and emitted run events.
- Prompt, response, and provider metadata are captured for debugging/evals.

## Future Integrations

- Add tool adapters as worker activities for:
  - MCP-compatible tools
  - Slack/Jira/Notion connectors
  - Internal HTTP and DB data access
