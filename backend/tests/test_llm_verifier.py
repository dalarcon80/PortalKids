import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "testing-secret")

from backend.app import verify_llm
from backend.llm import (
    LLMConfigurationError,
    LLMEvaluationResponse,
    MISSING_OPENAI_DEPENDENCY_MESSAGE,
    OpenAILLMClient,
)


class DummyFiles:
    def __init__(self, content: str) -> None:
        self._content = content
        self.requested_paths = []

    def read_text(self, path: str) -> str:
        self.requested_paths.append(path)
        return self._content

    def describe_source(self, path: str) -> str:
        return f"repo::{path}"


class VerifyLLMTests(unittest.TestCase):
    def _build_contract(self) -> dict:
        return {
            "deliverable_path": "docs/m5_notes.md",
            "expected_keywords": ["limpieza", "tipos"],
            "criteria": ["Detalla el proceso de limpieza", "explica cómo manejas los duplicados"],
            "feedback_fail": "La entrega necesita más detalle.",
        }

    @patch("backend.app.OpenAILLMClient.from_env")
    def test_verify_llm_marks_completed(self, mock_from_env: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.evaluate_deliverable.return_value = LLMEvaluationResponse(
            status="completado",
            feedback="",
        )
        mock_from_env.return_value = mock_client

        files = DummyFiles("Notas completas sobre limpieza, tipos y duplicados.")
        passed, feedback = verify_llm(files, self._build_contract())

        self.assertTrue(passed)
        self.assertEqual(feedback, [])
        mock_from_env.assert_called_once()
        mock_client.evaluate_deliverable.assert_called_once()
        call_kwargs = mock_client.evaluate_deliverable.call_args.kwargs
        self.assertIn("content", call_kwargs)
        self.assertEqual(call_kwargs["keywords"], ["limpieza", "tipos"])
        self.assertIn("Detalla el proceso de limpieza", call_kwargs["criteria"])

    @patch("backend.app.OpenAILLMClient.from_env")
    def test_verify_llm_marks_incomplete_with_feedback(self, mock_from_env: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.evaluate_deliverable.return_value = LLMEvaluationResponse(
            status="incompleto",
            feedback="Falta detallar cómo tratas los tipos de datos.",
        )
        mock_from_env.return_value = mock_client

        files = DummyFiles("Notas parciales sobre limpieza.")
        passed, feedback = verify_llm(files, self._build_contract())

        self.assertFalse(passed)
        self.assertEqual(feedback, ["Falta detallar cómo tratas los tipos de datos."])
        mock_from_env.assert_called_once()
        mock_client.evaluate_deliverable.assert_called_once()

    @patch("backend.app.OpenAILLMClient.from_env")
    def test_verify_llm_returns_friendly_error_when_openai_missing(
        self, mock_from_env: MagicMock
    ) -> None:
        mock_from_env.side_effect = LLMConfigurationError(MISSING_OPENAI_DEPENDENCY_MESSAGE)

        files = DummyFiles("Notas incompletas.")
        passed, feedback = verify_llm(files, self._build_contract())

        self.assertFalse(passed)
        self.assertEqual(feedback, [MISSING_OPENAI_DEPENDENCY_MESSAGE])
        mock_from_env.assert_called_once()


class OpenAILLMClientFromEnvTests(unittest.TestCase):
    def test_from_env_propagates_missing_dependency_error(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "testing", "OPENAI_MODEL": "gpt-4"},
            clear=False,
        ):
            with patch("backend.llm.OpenAI") as mock_openai:
                mock_openai.side_effect = LLMConfigurationError(
                    MISSING_OPENAI_DEPENDENCY_MESSAGE
                )
                with self.assertRaises(LLMConfigurationError) as ctx:
                    OpenAILLMClient.from_env()

        self.assertEqual(str(ctx.exception), MISSING_OPENAI_DEPENDENCY_MESSAGE)
        mock_openai.assert_called_once()
        self.assertEqual(mock_openai.call_args.kwargs.get("api_key"), "testing")
