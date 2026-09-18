"""One optional Responses API request, with timeout and validated mock fallback."""
import json
import os
import queue
import threading
import unicodedata
from typing import Any, Callable
from urllib.request import Request, urlopen

from llm.base import BasePlanner, PlannerText

Transport = Callable[[dict[str, Any], str, float], dict[str, Any]]


def request_response(payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    request = Request("https://api.openai.com/v1/responses",
                      data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Response exceeds demo size limit")
    return json.loads(raw)


class LLMPlanner(BasePlanner):
    def __init__(self, transport: Transport = request_response, deadline: float = 6.0):
        self.transport = transport
        self.deadline = deadline

    def bounded_request(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        results: queue.Queue = queue.Queue(maxsize=1)

        def request() -> None:
            try:
                results.put((True, self.transport(payload, key, 5.0)))
            except Exception as error:
                results.put((False, error))

        # Daemon thread prevents an unresponsive optional request from delaying process exit.
        threading.Thread(target=request, daemon=True).start()
        try:
            successful, result = results.get(timeout=self.deadline)
        except queue.Empty:
            raise TimeoutError("Optional enhancement deadline exceeded") from None
        if not successful:
            raise result
        return result

    def describe(self, goal: str, descriptions: dict[str, str]) -> PlannerText:
        def fallback(reason: str) -> PlannerText:
            return PlannerText(dict(descriptions), "mock", f"LLM fallback: {reason}; continuing with mock")

        key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = os.environ.get("OPENAI_MODEL", "").strip()
        if not key:
            return fallback("OPENAI_API_KEY is not set")
        if not model:
            return fallback("OPENAI_MODEL is not set")
        schema = {"type": "object", "properties": {tid: {"type": "string"} for tid in descriptions},
                  "required": list(descriptions), "additionalProperties": False}
        payload = {
            "model": model, "store": False, "max_output_tokens": 1200,
            "instructions": "Write one concise English description for each existing seminar task. "
                            "Preserve its meaning and all constraints. Return only the requested JSON. "
                            "Each description must be one line, at most 240 characters. "
                            "Do not include reasoning, status, dependencies, tools or execution instructions.",
            "input": json.dumps({"user_goal": goal, "task_descriptions": descriptions}),
            "text": {"format": {"type": "json_schema", "name": "seminar_task_descriptions",
                                "strict": True, "schema": schema}},
        }
        try:
            response = self.bounded_request(payload, key)
            if response.get("status") != "completed":
                return fallback("response was not completed")
            parts = [part for item in response.get("output", []) if item.get("type") == "message"
                     for part in item.get("content", [])]
            if any(part.get("type") == "refusal" for part in parts):
                return fallback("model declined the request")
            raw = "".join(part["text"] for part in parts if part.get("type") == "output_text")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or set(parsed) != set(descriptions):
                return fallback("unexpected task IDs or fields")
            if any(not isinstance(value, str) or not value.strip() or len(value) > 240
                   or any(unicodedata.category(char).startswith("C") for char in value)
                   for value in parsed.values()):
                return fallback("invalid description text")
            return PlannerText({tid: value.strip() for tid, value in parsed.items()}, "llm",
                               "LLM descriptions accepted; executable rules remain code-owned")
        except Exception as error:
            # Never log HTTP bodies, credentials, request headers, or exception messages.
            return fallback(f"request or validation failed ({type(error).__name__})")
