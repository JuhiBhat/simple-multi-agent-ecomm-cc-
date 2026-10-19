"""Builds the LLM every agent uses, from environment variables (see .env.example)."""
import logging
import os

from crewai import LLM

logger = logging.getLogger("agent_llm")


def build_llm() -> LLM:
    model_type = os.getenv("MODEL_TYPE", "openai").lower()
    if model_type == "ollama":
        model = os.getenv("OLLAMA_MODEL", "llama3.1")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        logger.info(f"Using Ollama model {model} at {base_url}")
        return LLM(model=f"ollama/{model}", base_url=base_url, temperature=0)

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # Vocareum course keys need https://openai.vocareum.com/v1 ; a personal OpenAI key needs no base URL
    base_url = os.getenv("OPENAI_BASE_URL") or None
    logger.info(f"Using OpenAI model {model} (base_url={base_url or 'default'})")
    return LLM(model=f"openai/{model}", api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url, temperature=0)
