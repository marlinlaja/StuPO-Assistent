import time
from dataclasses import dataclass

from openai import OpenAI
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEFAULT_THINKING, LLM_MODEL, LLM_TIMEOUT_SECONDS



# --- Datenmodell ---

@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0

    def add(self, other: "TokenUsage") -> None:
        self.input += other.input
        self.output += other.output



# --- LLM ---

# thinking = "none" oder die Stufe fuer reasoning_effort. Die Nachricht kommt so zurueck, dass sie direkt wieder an
# messages angehaengt werden kann. step benennt den Aufruf im Log, json_output erzwingt ein JSON-Objekt als Antwort
# (der Prompt muss dann JSON erwaehnen). tool_choice="none" laesst die Tools in der Anfrage (der Cache gilt fuer ihren
# Anfang), das LLM darf sie aber nicht mehr aufrufen.
def call_llm(messages: list[dict], tools: list[dict] | None = None, thinking: str = DEFAULT_THINKING,
             step: str | None = None, json_output: bool = False,
             tool_choice: str | None = None) -> tuple[dict, TokenUsage]:
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=LLM_TIMEOUT_SECONDS)
    request = {"model": LLM_MODEL, "messages": messages, "extra_body": {"thinking": {"type": "disabled"}}}
    if thinking != "none":
        request["extra_body"] = {"thinking": {"type": "enabled"}}
        request["reasoning_effort"] = thinking
    if tools:
        request["tools"] = tools
        if tool_choice:
            request["tool_choice"] = tool_choice
    if json_output:
        request["response_format"] = {"type": "json_object"}

    start = time.monotonic()
    response = client.chat.completions.create(**request)
    usage = TokenUsage(response.usage.prompt_tokens, response.usage.completion_tokens)
    step_name = step or ("Recherche" if tools else "Antwort")
    log_call(f"{step_name} ({thinking})", time.monotonic() - start, response.usage)
    return as_message(response.choices[0].message), usage



# Fuer die Antwortzeit: Dauer und Tokens jedes Aufrufs, Thinking-Tokens, wenn DeepSeek sie mitliefert
def log_call(step: str, seconds: float, usage: CompletionUsage) -> None:
    details = getattr(usage, "completion_tokens_details", None)
    thinking_tokens = getattr(details, "reasoning_tokens", None)
    thinking = f", davon {thinking_tokens} Thinking" if thinking_tokens else ""
    # DeepSeek berechnet Eingabe aus dem Cache (gleicher Anfang wie eine fruehere Anfrage) deutlich guenstiger
    cached_tokens = getattr(usage, "prompt_cache_hit_tokens", None)
    cached = f" (davon {cached_tokens} aus dem Cache)" if cached_tokens is not None else ""
    tokens = f"{usage.prompt_tokens} Tokens Eingabe{cached}, {usage.completion_tokens} Ausgabe{thinking}"
    print(f"LLM {step}: {seconds:.1f} s, {tokens}", flush=True)



def as_message(reply: ChatCompletionMessage) -> dict:
    message = {"role": "assistant", "content": reply.content or ""}

    # mit Thinking und Tools will DeepSeek das Denken der vorigen Runden zurueck
    if getattr(reply, "reasoning_content", None):
        message["reasoning_content"] = reply.reasoning_content

    if reply.tool_calls:
        message["tool_calls"] = [as_tool_call(tool_call) for tool_call in reply.tool_calls]
    return message



def as_tool_call(tool_call: ChatCompletionMessageToolCall) -> dict:
    function = {"name": tool_call.function.name, "arguments": tool_call.function.arguments}
    return {"id": tool_call.id, "type": "function", "function": function}
