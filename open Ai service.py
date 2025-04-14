# --- START OF FILE app/services/openai_service.py ---
import os
import logging
import time
from typing import Optional, Tuple, List, Dict, Union
from flask import current_app, has_app_context
import openai
import tiktoken

# --- Logging ---
log = logging.getLogger(__name__)

# --- Singletons ---
_openai_client = None
_token_encoder = None

# --- Helper Functions ---
def get_openai_client(force_reload: bool = False):
    """Initializes and returns the OpenAI client using Flask config."""
    global _openai_client
    if _openai_client is None or force_reload:
        if force_reload: log.info("Forcing reload of OpenAI client.")
        api_key = os.environ.get('OPENAI_API_KEY') # Env var first
        if not api_key and has_app_context():
            api_key = current_app.config.get('OPENAI_API_KEY')

        if not api_key: log.error("OpenAI API key not found."); raise ValueError("OPENAI_API_KEY is not configured.")
        try:
            log.info("Initializing OpenAI client.")
            _openai_client = openai.OpenAI(api_key=api_key, timeout=120.0) # 2 min timeout
        except Exception as e: log.exception(f"Failed to initialize OpenAI client: {e}"); _openai_client = None; raise RuntimeError("Could not initialize OpenAI client") from e
    return _openai_client

def get_tokenizer(model_name="gpt-4"):
    """Gets a tiktoken tokenizer for a given model."""
    global _token_encoder
    encoding_name = "cl100k_base" # Common for recent models
    try:
        if _token_encoder is None or _token_encoder.name != encoding_name:
            log.info(f"Loading tiktoken encoding: {encoding_name}")
            _token_encoder = tiktoken.get_encoding(encoding_name)
    except Exception as e: log.error(f"Failed to load tiktoken encoding '{encoding_name}': {e}."); _token_encoder = None
    return _token_encoder

def count_message_tokens(messages: List[Dict[str, str]], model_name="gpt-4") -> int:
    """Estimates the token count for a list of messages using tiktoken."""
    encoder = get_tokenizer(model_name)
    if not encoder: return 999999 # Return large number if encoder fails to prevent API call

    if "gpt-3.5-turbo" in model_name: tokens_per_message, tokens_per_name = 4, -1
    elif "gpt-4" in model_name: tokens_per_message, tokens_per_name = 3, 1
    else: tokens_per_message, tokens_per_name = 3, 1 # Default

    num_tokens = 0
    try:
        for message in messages:
            num_tokens += tokens_per_message
            for key, value in message.items():
                if value: num_tokens += len(encoder.encode(str(value)))
                if key == "name": num_tokens += tokens_per_name
        num_tokens += 3 # Priming
        return num_tokens
    except Exception as e: log.error(f"Error counting tokens: {e}"); return 999999 # Return large number on error

# --- Core Function ---
def generate_chat_response(
    user_id: int, user_input: str,
    topic_context: Optional[List[str]] = None, # User's specific memory context
    knowledge_chunks: Optional[List[str]] = None, # Curated KB context
    response_mode: str = 'balanced', fact_verification: bool = False, # Placeholder
    conversation_history: Optional[List[Dict[str, str]]] = None, # Recent chat turns
    # Models from config or defaults
    fast_model: str = "gpt-3.5-turbo",
    balanced_model: str = "gpt-4-turbo-preview",
    thorough_model: str = "gpt-4-turbo-preview",
    max_response_tokens_default: int = 1000,
    temperature_default: float = 0.7
) -> Tuple[Optional[str], Optional[int]]:
    """Generates OpenAI response, handles context, token limits, and errors."""
    try:
        client = get_openai_client()
        if not client: raise RuntimeError("OpenAI client failed to initialize.")

        # --- Model Selection & Params ---
        model_name = balanced_model; max_tokens_response = max_response_tokens_default; temperature = temperature_default
        if response_mode == 'fast': model_name, max_tokens_response, temperature = fast_model, max(max_response_tokens_default // 2, 250), 0.8
        elif response_mode == 'thorough': model_name, max_tokens_response, temperature = thorough_model, max(max_response_tokens_default * 2, 500), 0.5
        log.debug(f"User {user_id}: OpenAI Call - Model='{model_name}', Mode='{response_mode}', Temp={temperature}, MaxResp={max_tokens_response}")

        # --- Construct Messages ---
        messages: List[Dict[str, str]] = []
        system_prompt_lines = ["You are Ask JDXX, an intelligent AI assistant."]
        if knowledge_chunks: system_prompt_lines.append("Base your answer primarily on the 'Relevant Knowledge Base Information'.")
        elif topic_context: system_prompt_lines.append("Base your answer on the 'Relevant Past Discussion Points'.")
        else: system_prompt_lines.append("Use your general knowledge.")
        if response_mode == 'thorough': system_prompt_lines.append("Provide detailed answers.")
        elif response_mode == 'fast': system_prompt_lines.append("Provide concise answers.")
        messages.append({"role": "system", "content": " ".join(system_prompt_lines)})
        if knowledge_chunks: messages.append({"role": "system", "content": "---\nRelevant Knowledge Base Info:\n" + "\n\n".join(f"- {item}" for item in knowledge_chunks) + "\n---"})
        if topic_context: messages.append({"role": "system", "content": "---\nRelevant Past Discussion Points (User Memory):\n" + "\n\n".join(f"- {item}" for item in topic_context) + "\n---"})
        if conversation_history: messages.extend(conversation_history) # Add history before user input
        messages.append({"role": "user", "content": user_input}) # User input is last

        # --- Token Limit Calculation & Truncation ---
        model_context_limits = {"gpt-4": 8192, "gpt-3.5-turbo": 16385, "gpt-4-turbo-preview": 128000}
        max_context_tokens = model_context_limits.get(model_name, 4096)
        max_prompt_tokens = max_context_tokens - max_tokens_response - 150 # Buffer

        current_prompt_tokens = count_message_tokens(messages, model_name)
        log.debug(f"User {user_id}: Initial token count: {current_prompt_tokens}, Max prompt tokens: {max_prompt_tokens}")

        # Truncate *conversation history* if needed (oldest turns first)
        while current_prompt_tokens > max_prompt_tokens and conversation_history and len(messages) > 2:
            first_history_index = 1 # Index after initial system prompt
            # Adjust index if context blocks were added
            if messages[1].get("role") == "system": first_history_index += 1
            if first_history_index < len(messages) and messages[first_history_index].get("role") == "system": first_history_index += 1

            if first_history_index < len(messages) - 1: # Ensure history exists before user input
                removed_message = messages.pop(first_history_index)
                log.warning(f"Truncating prompt ({current_prompt_tokens} > {max_prompt_tokens}). Removed history: {removed_message['role']}")
                current_prompt_tokens = count_message_tokens(messages, model_name)
            else: break # Cannot remove further

        if current_prompt_tokens > max_prompt_tokens:
            log.error(f"User {user_id}: Prompt still too long ({current_prompt_tokens}) after history truncation! Context might be too large.")
            # TODO: Consider truncating topic_context or knowledge_chunks here if necessary
            return "Sorry, the relevant context and your message are too long for the AI model.", None
        log.debug(f"Final token count: {current_prompt_tokens}. Sending {len(messages)} messages.")

        # --- Call API ---
        start_time = time.time()
        response = client.chat.completions.create(
            model=model_name, messages=messages, temperature=temperature, max_tokens=max_tokens_response
        )
        log.info(f"User {user_id}: OpenAI API call '{model_name}' completed in {time.time() - start_time:.2f}s")

        # --- Process Response ---
        ai_response_text, total_tokens_used = None, 0
        if response.choices:
            message = response.choices[0].message; finish_reason = response.choices[0].finish_reason
            ai_response_text = message.content.strip() if message and message.content else None
            log.debug(f"User {user_id}: Finish reason: {finish_reason}")
            if finish_reason == 'length': log.warning(f"User {user_id}: OpenAI response potentially truncated.")
        if response.usage: total_tokens_used = response.usage.total_tokens; log.debug(f"User {user_id}: Usage: {response.usage}")
        if not ai_response_text: log.warning(f"User {user_id}: OpenAI response content empty.")
        return ai_response_text or "Sorry, received an empty response.", total_tokens_used

    # --- Error Handling ---
    except openai.BadRequestError as e: log.error(f"User {user_id}: OpenAI Bad Request (Prompt too long?): {e}"); return "Sorry, request/context too long.", None
    except openai.APIConnectionError as e: log.error(f"... Connection Error: {e}"); return "Sorry, couldn't connect to AI.", None
    except openai.RateLimitError as e: log.error(f"... Rate Limit Error: {e}"); return "AI service busy. Try again shortly.", None
    except openai.AuthenticationError as e: log.error(f"... Auth Error: {e}"); return "AI service auth config issue.", None
    except openai.APIStatusError as e: log.error(f"... API Status Error {e.status_code}: {e.response}"); return f"AI service error (Code: {e.status_code}).", None
    except RuntimeError as e: log.error(f"OpenAI Client Runtime Error: {e}"); return "AI service client issue.", None
    except Exception as e: log.exception(f"User {user_id}: Unexpected error calling OpenAI API: {e}"); return "Sorry, an unexpected error occurred.", None
# --- END OF FILE app/services/openai_service.py ---