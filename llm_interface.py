from typing import Dict, List, Any
from dotenv import load_dotenv
from langchain.prompts import ChatPromptTemplate
from langchain.globals import set_debug, set_verbose
import time
import random
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# set_debug(True)
# set_verbose(True)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Disable HTTP request logs from langchain
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)

load_dotenv()


def get_available_models() -> List[str]:
    """Return a list of available LLM models"""
    # You can customize this list based on the models you want to support
    return ["gemini-2.0-flash-lite", "gpt-4o-mini", "gpt-4.1-nano", "gemini-2.0-flash",]

# def get_available_models() -> List[str]:
#     return [
#         "gemini-2.0-flash-lite",
#         "gemini-2.0-flash",
#         "gemini-2.0-pro",
#         "gpt-4o-mini",
#         "gpt-4.1-nano",
#         "gpt-4.1",
#         "gpt-4.1-mini",
#         "o3-mini",
#         "claude-3-opus",
#         "claude-3-7-sonnet",
#     ]



def run_llm_query(
    model: str,
    prompt_template: str,
    prompt_vars: Dict[str, Any],
    max_retries: int = 3,
    base_wait: float = 1.0,
    max_wait: float = 10.0,
) -> str:
    """
    Run a query against the specified LLM using the template and variables with retry logic.

    Args:
        model: The LLM model to use
        prompt_template: The template string for the prompt
        prompt_vars: Variables to format into the template
        max_retries: Maximum number of retry attempts
        base_wait: Base wait time for exponential backoff (seconds)
        max_wait: Maximum wait time between retries (seconds)
    """
    # Create prompt from template
    template = ChatPromptTemplate.from_template(prompt_template)
    formatted_prompt = template.format_messages(**prompt_vars)

    # Define which exceptions to retry on
    retryable_exceptions = (
        ConnectionError,
        TimeoutError,
        # Add more specific exceptions as needed for different providers
    )

    # Define the retry decorator
    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=base_wait, max=max_wait),
        retry=retry_if_exception_type(retryable_exceptions),
        before_sleep=lambda retry_state: logger.info(
            f"Retry attempt {retry_state.attempt_number} for {model} after {retry_state.outcome.exception()}"
        ),
    )
    def execute_with_retry():
        try:
            # Setup the appropriate model
            if "gpt" in model.lower():
                from langchain_openai import ChatOpenAI

                llm = ChatOpenAI(model_name=model, temperature=0.7)
            elif "gemini" in model.lower():
                from langchain_google_genai import ChatGoogleGenerativeAI

                llm = ChatGoogleGenerativeAI(model=model, temperature=0.7)
            elif "claude" in model.lower():
                from langchain_anthropic import ChatAnthropic

                llm = ChatAnthropic(model=model, temperature=0.7)
            else:
                raise ValueError(f"Unsupported model: {model}")

            # Execute the query
            response = llm.invoke(formatted_prompt)
            return response.content

        except Exception as e:
            # Log the error
            logger.error(f"Error querying {model}: {str(e)}")

            # If it's a retryable exception, re-raise it for the retry mechanism
            if isinstance(e, retryable_exceptions):
                raise

            # For rate limiting errors, apply exponential backoff
            if "rate limit" in str(e).lower() or "quota exceeded" in str(e).lower():
                wait_time = base_wait * (2 ** random.uniform(0, 1))
                logger.info(f"Rate limited. Waiting {wait_time:.2f}s before retry")
                time.sleep(min(wait_time, max_wait))
                raise ConnectionError(f"Rate limiting error: {str(e)}")

            # For other exceptions, just raise them
            raise

    # Execute with retry logic
    try:
        return execute_with_retry()
    except Exception as e:
        # If all retries failed, log the final error and raise
        logger.error(f"All {max_retries} retry attempts failed for {model}: {str(e)}")
        raise


def stream_llm_query(model: str, prompt_template: str, prompt_vars: Dict[str, Any]):
    """Stream a query response from the LLM for real-time display"""

    # Create prompt from template
    template = ChatPromptTemplate.from_template(prompt_template)
    formatted_prompt = template.format_messages(**prompt_vars)

    # Setup the appropriate model with streaming
    if "gpt" in model.lower():
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model_name=model, temperature=0.7, streaming=True)
    elif "gemini" in model.lower():
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(model=model, temperature=0.7, streaming=True)
    elif "claude" in model.lower():
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(model=model, temperature=0.7, streaming=True)
    else:
        raise ValueError(f"Unsupported model: {model}")

    # Return the streaming response
    for chunk in llm.stream(formatted_prompt):
        yield chunk.content
