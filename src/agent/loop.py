import os
import json
from typing import Dict, Any, List, Tuple
from google import genai
from google.genai import types

from src.agent.prompt import SYSTEM_PROMPT
from src.tools.registry import ALL_TOOLS, TOOL_MAP

def get_gemini_client() -> genai.Client:
    """Instantiates Google GenAI Client with GEMINI_API_KEY env var."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")
    return genai.Client(api_key=api_key)

def process_user_message_agent(
    user_message: str,
    conversation_history: List[Dict[str, Any]] = None,
    model_name: str = "gemini-2.5-flash"
) -> Tuple[str, List[str]]:
    """
    Core Pure Agentic Control Loop:
    Telegram User Message -> LLM -> Tool Selection -> Tool Execution -> Tool Result -> LLM -> Final Text Response.
    
    Supports multi-tool chaining per turn.
    Returns:
        (final_text_response, list_of_generated_file_paths)
    """
    client = get_gemini_client()

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        temperature=0.2,
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

    while current_turn < max_turns:
        current_turn += 1
        
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            # Fallback model attempt if gemini-2.5-flash is unavailable
            if "not found" in str(e).lower() and model_name != "gemini-1.5-flash":
                return process_user_message_agent(user_message, conversation_history, model_name="gemini-1.5-flash")
            raise e

        # Append assistant candidate to conversation stream
        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        # Check if model requested function calls
        function_calls = response.function_calls
        if not function_calls:
            # Model produced final text response
            final_text = response.text or "Request processed successfully."
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
                    if isinstance(tool_result, dict) and "file_path" in tool_result:
                        generated_files.append(tool_result["file_path"])
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

    return "Processing completed after multi-turn tool execution.", generated_files
