"""Integration helpers to evaluate deliverables with a large language model."""
from __future__ import annotations

import json
import os
import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Sequence

MISSING_OPENAI_DEPENDENCY_MESSAGE = (
    "La evaluación con modelos de lenguaje requiere la dependencia opcional 'openai'. "
    "Instálala para habilitar esta funcionalidad."
)


class LLMConfigurationError(RuntimeError):
    """Raised when the OpenAI client cannot be configured."""


class LLMEvaluationError(RuntimeError):
    """Raised when the evaluation request fails or returns an invalid payload."""


try:  # pragma: no cover - optional dependency
    from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    class _MissingOpenAIError(LLMConfigurationError):
        """Raised when the optional 'openai' package is unavailable."""

    class _MissingOpenAIModule:
        APIConnectionError = _MissingOpenAIError
        APIError = _MissingOpenAIError
        APITimeoutError = _MissingOpenAIError
        RateLimitError = _MissingOpenAIError

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                raise _MissingOpenAIError(MISSING_OPENAI_DEPENDENCY_MESSAGE)

        def OpenAI(self, *args, **kwargs):  # type: ignore[override]
            return self._Client(*args, **kwargs)

    _missing_openai = _MissingOpenAIModule()
    APIConnectionError = _missing_openai.APIConnectionError
    APIError = _missing_openai.APIError
    APITimeoutError = _missing_openai.APITimeoutError
    OpenAI = _missing_openai.OpenAI  # type: ignore[assignment]
    RateLimitError = _missing_openai.RateLimitError

DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo"
_MAX_COMPLETION_TOKENS = 300

SYSTEM_PROMPT = (
    "Eres un evaluador académico que revisa notas de estudiantes en español. "
    "Debes decidir si la entrega cumple con los criterios del contrato y responder "
    "únicamente en JSON usando las claves 'status' y 'feedback'. "
    "Marca 'status' como 'completado' cuando todos los criterios están cubiertos y "
    "'incompleto' cuando falta información, dando retroalimentación breve en español."
)
@dataclass
class LLMEvaluationResponse:
    """Normalized response returned by the LLM evaluator."""

    status: str
    feedback: str = ""

    def normalized_status(self) -> str:
        return (self.status or "").strip().lower()


def _normalize_items(values: Sequence[str] | str | None) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        clean = values.strip()
        return [clean] if clean else []
    normalized: List[str] = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, str):
            clean = item.strip()
        else:
            clean = str(item).strip()
        if clean:
            normalized.append(clean)
    return normalized


def _format_section(title: str, items: Iterable[str]) -> str:
    lines = [title]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _extract_json_block(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if "\n" in cleaned:
            first_line, rest = cleaned.split("\n", 1)
            if first_line.lower().startswith("json"):
                cleaned = rest
            else:
                cleaned = rest
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end >= start:
        cleaned = cleaned[start : end + 1]
    return cleaned.strip()


class OpenAILLMClient:
    """Simple wrapper around OpenAI's Chat Completions API."""

    def __init__(self, api_key: str, *, model: str = DEFAULT_OPENAI_MODEL, timeout: float | None = None) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "Configura la integración de OpenAI desde el panel administrativo o define la variable de entorno OPENAI_API_KEY."
            )
        model_name = (model or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        self._client = OpenAI(api_key=api_key)
        self._model = model_name
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAILLMClient":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "Configura la variable de entorno OPENAI_API_KEY para habilitar la evaluación automática de notas."
            )
        model = (os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        timeout = None
        timeout_raw = os.environ.get("OPENAI_TIMEOUT")
        if timeout_raw:
            try:
                timeout = float(timeout_raw)
            except ValueError as exc:
                raise LLMConfigurationError("OPENAI_TIMEOUT debe ser un número en segundos.") from exc
            if timeout <= 0:
                raise LLMConfigurationError("OPENAI_TIMEOUT debe ser mayor a cero segundos.")
        return cls(api_key=api_key, model=model, timeout=timeout)

    @classmethod
    def from_settings(cls) -> "OpenAILLMClient":
        try:
            from . import app as app_module  # type: ignore
        except ImportError:  # pragma: no cover - fallback for direct execution
            import app as app_module  # type: ignore

        settings = app_module.load_service_settings(
            ["openai_api_key", "openai_model", "openai_timeout"]
        )
        api_key = (settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "Configura la integración de OpenAI desde el panel administrativo o define la variable de entorno OPENAI_API_KEY."
            )
        model = (
            settings.get("openai_model")
            or os.environ.get("OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        ).strip() or DEFAULT_OPENAI_MODEL
        timeout_value = settings.get("openai_timeout") or os.environ.get("OPENAI_TIMEOUT")
        timeout = None
        if timeout_value:
            try:
                timeout = float(timeout_value)
            except ValueError as exc:
                raise LLMConfigurationError("El timeout de OpenAI debe ser un número en segundos.") from exc
            if timeout <= 0:
                raise LLMConfigurationError("El timeout de OpenAI debe ser mayor a cero segundos.")
        return cls(api_key=api_key, model=model, timeout=timeout)

    def evaluate_deliverable(
        self,
        *,
        content: str,
        keywords: Sequence[str] | None = None,
        criteria: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> LLMEvaluationResponse:
        keyword_list = _normalize_items(keywords)
        criteria_list = _normalize_items(criteria)
        sections: List[str] = []
        if keyword_list:
            sections.append(_format_section("Palabras clave obligatorias:", keyword_list))
        if criteria_list:
            sections.append(_format_section("Criterios de evaluación:", criteria_list))
        if not sections:
            sections.append("No hay criterios adicionales declarados, evalúa claridad y completitud general.")
        contract_context = "\n\n".join(sections)
        base_instructions = (
            instructions.strip()
            if isinstance(instructions, str) and instructions.strip()
            else (
                "Evalúa si las notas del estudiante cubren cada punto del contrato con suficiente detalle. "
                "Responde con 'completado' solo cuando todo está cubierto."
            )
        )
        notes_content = (content or "").strip()
        prompt_template = '''
            {base_instructions}

            {contract_context}

            Notas del estudiante:
            """
            {notes_content}
            """

            Responde ÚNICAMENTE en JSON exactamente con el formato:
            {{
              "status": "completado" o "incompleto",
              "feedback": "explica brevemente qué falta si corresponde"
            }}
            Si la entrega está completa puedes dejar "feedback" vacío.
            """
        '''
        user_prompt = textwrap.dedent(prompt_template).format(
            base_instructions=base_instructions,
            contract_context=contract_context,
            notes_content=notes_content,
        ).strip()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        request_args = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": _MAX_COMPLETION_TOKENS,
        }
        if self._timeout is not None:
            request_args["timeout"] = self._timeout
        try:
            completion = self._client.chat.completions.create(**request_args)
        except APITimeoutError as exc:  # pragma: no cover - network failure guard
            raise LLMEvaluationError(
                "La evaluación tardó demasiado en responder. Intenta nuevamente en unos minutos."
            ) from exc
        except RateLimitError as exc:  # pragma: no cover - network failure guard
            raise LLMEvaluationError(
                "El servicio de evaluación está saturado en este momento. Vuelve a intentarlo más tarde."
            ) from exc
        except APIConnectionError as exc:  # pragma: no cover - network failure guard
            raise LLMEvaluationError(
                "No se pudo conectar con el servicio de evaluación automática. Intenta otra vez en breve."
            ) from exc
        except APIError as exc:  # pragma: no cover - network failure guard
            raise LLMEvaluationError(
                "El evaluador automático devolvió un error inesperado. Por favor intenta nuevamente más tarde."
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise LLMEvaluationError(
                "No se pudo completar la evaluación automática. Intenta nuevamente más tarde."
            ) from exc

        try:
            first_choice = completion.choices[0]
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMEvaluationError(
                "La evaluación no devolvió ningún resultado interpretable. Intenta nuevamente."
            ) from exc
        raw_content = ""
        message = getattr(first_choice, "message", None)
        if message is not None:
            raw_content = getattr(message, "content", "") or ""
        if not raw_content and hasattr(first_choice, "text"):
            raw_content = getattr(first_choice, "text", "") or ""
        if not raw_content.strip():
            raise LLMEvaluationError(
                "La evaluación automática no generó una respuesta. Intenta nuevamente en unos minutos."
            )

        json_payload = _extract_json_block(raw_content)
        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError as exc:
            raise LLMEvaluationError(
                "La respuesta del evaluador no es JSON válido. Intenta nuevamente o contacta a tu instructor."
            ) from exc
        if not isinstance(parsed, dict):
            raise LLMEvaluationError(
                "La respuesta del evaluador tiene un formato desconocido. Intenta nuevamente más tarde."
            )
        status_raw = parsed.get("status") or parsed.get("estado")
        feedback_raw = parsed.get("feedback") or parsed.get("retroalimentacion")
        status_text = str(status_raw).strip() if status_raw is not None else ""
        if not status_text:
            raise LLMEvaluationError(
                "La respuesta del evaluador no incluyó el campo 'status'. Intenta nuevamente."
            )
        feedback_text = str(feedback_raw).strip() if feedback_raw is not None else ""
        return LLMEvaluationResponse(status=status_text, feedback=feedback_text)
