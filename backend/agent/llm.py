"""
LLM setup. Picks the first provider whose API key is found in the environment:
Gemini -> Groq -> OpenAI. Only ONE key is needed (Gemini and Groq have free tiers).
Model names can be overridden with GEMINI_MODEL / GROQ_MODEL / OPENAI_MODEL.
"""

import os

from langchain_core.language_models.chat_models import BaseChatModel


def get_structured_llm(schema, max_tokens=None):
    llm = get_llm(max_tokens=max_tokens)

    if llm_provider() == "groq":
        from groq import RateLimitError

        return llm.with_structured_output(
            schema,
            method="json_schema",
        ).with_retry(
            retry_if_exception_type=(RateLimitError,),
            wait_exponential_jitter=True,
            stop_after_attempt=3,
        )

    return llm.with_structured_output(schema)

def llm_provider() -> str | None:
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None

def get_llm(max_tokens: int | None = None) -> BaseChatModel:
    """Return a chat model for the available provider."""
    provider = llm_provider()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), temperature=0.2
        )
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0.1,
            reasoning_effort="low",
            max_tokens=max_tokens,
            timeout=60,
            max_retries=5,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0.2)

    raise RuntimeError(
        "No LLM API key found. Set GOOGLE_API_KEY, Groq API key or OPENAI_API_KEY in .env"
    )
