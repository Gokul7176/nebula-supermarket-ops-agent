import os
import json
from typing import Dict, Any, List, Tuple
from google import genai
from google.genai import types

from src.agent.context import current_chat_id_var, current_user_message_var
from src.agent.prompt import SYSTEM_PROMPT
from src.tools.registry import ALL_TOOLS, TOOL_MAP

def get_gemini_client() -> genai.Client:
    """Instantiates Google GenAI Client with GEMINI_API_KEY env var."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")
    return genai.Client(api_key=api_key)

import time

def process_user_message_agent(
    user_message: str,
    conversation_history: List[Dict[str, Any]] = None,
    model_name: str = None,
    chat_id: str = "default"
) -> Tuple[str, List[str]]:
    """
    Core Pure Agentic Control Loop:
    Telegram User Message -> LLM -> Tool Selection -> Tool Execution -> Tool Result -> LLM -> Final Text Response.
    
    Supports multi-tool chaining per turn.
    Returns:
        (final_text_response, list_of_generated_file_paths)
    """
    token_chat = current_chat_id_var.set(str(chat_id))
    token_msg = current_user_message_var.set(str(user_message))
    try:
        return _process_user_message_agent_impl(user_message, conversation_history, model_name, str(chat_id))
    finally:
        current_chat_id_var.reset(token_chat)
        current_user_message_var.reset(token_msg)

def _process_user_message_agent_impl(
    user_message: str,
    conversation_history: List[Dict[str, Any]] = None,
    model_name: str = None,
    chat_id: str = "default"
) -> Tuple[str, List[str]]:
    if model_name is None:
        model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    client = get_gemini_client()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )

    # Convert conversation history into GenAI Content types if provided
    contents = []
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))

    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    generated_files: List[str] = []
    max_turns = 10  # Protection against infinite loops
    current_turn = 0

    CASCADE_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash"]

    last_tool_summary: Optional[str] = None

    while current_turn < max_turns:
        current_turn += 1
        
        response = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                break  # Call succeeded
            except Exception as e:
                err_str = str(e).lower()

                # Retry transient 503 errors with backoff first
                if ("503" in err_str or "unavailable" in err_str or "high demand" in err_str) and attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                # If 503, 429, 404, or quota limit persists, fall back to next model in cascade
                if any(k in err_str for k in ["503", "429", "unavailable", "high demand", "quota", "resource_exhausted", "not found", "no longer available"]):
                    next_model = None
                    try:
                        curr_idx = CASCADE_MODELS.index(model_name)
                        if curr_idx + 1 < len(CASCADE_MODELS):
                            next_model = CASCADE_MODELS[curr_idx + 1]
                    except ValueError:
                        next_model = None

                    if next_model and next_model != model_name:
                        return process_user_message_agent(user_message, conversation_history, model_name=next_model, chat_id=chat_id)

                raise e

        # Append assistant candidate to conversation stream
        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        # Check if model requested function calls
        function_calls = response.function_calls
        if not function_calls:
            # Model produced final text response
            raw_text = (response.text or "").strip()
            if not raw_text or raw_text.lower().strip(" .!") in ["request processed successfully", "processed successfully", "request completed successfully"]:
                if last_tool_summary:
                    final_text = last_tool_summary
                elif generated_files:
                    final_text = f"Report generated successfully: {os.path.basename(generated_files[-1])}"
                else:
                    final_text = "Request processed successfully."
            else:
                final_text = raw_text
            return final_text, generated_files

        # Execute returned tool function calls sequentially
        function_response_parts = []
        for call in function_calls:
            func_name = call.name
            func_args = call.args or {}
            
            if func_name not in TOOL_MAP:
                tool_result = {"status": "error", "error": f"Tool '{func_name}' not found."}
            else:
                try:
                    tool_func = TOOL_MAP[func_name]
                    tool_result = tool_func(**func_args)
                    
                    # Track if tool returned a file path (PDF/PPTX)
                    if isinstance(tool_result, dict):
                        if "file_path" in tool_result:
                            generated_files.append(tool_result["file_path"])
                        if "summary" in tool_result:
                            last_tool_summary = tool_result["summary"]
                except Exception as ex:
                    tool_result = {"status": "error", "error": str(ex)}

            function_response_parts.append(
                types.Part.from_function_response(
                    name=func_name,
                    response={"result": tool_result}
                )
            )

        # Feed tool execution responses back to LLM context
        contents.append(types.Content(role="user", parts=function_response_parts))

    return last_tool_summary or "Processing completed after multi-turn tool execution.", generated_files
