"""Offline configuration regression tests; no model, audio or dataset imports.

Run the real runtime loader and TTS functions. Only the separate evaluation
script still uses AST isolation; it is not an offline runtime entrypoint.
All supplied credentials are nonfunctional test markers.
"""
import ast
import os
import sys
from pathlib import Path
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ENV_URL = "https://offline.test/v1/chat/completions"
ENV_TOKEN = "offline-unit-test-token-never-valid"


def selected_code(relative_path, names):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in ("__future__", "MobileAgent.config"):
            nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            nodes.append(node)
    # Synthetic filename prevents old source values appearing in tracebacks.
    return compile(ast.Module(body=nodes, type_ignores=[]), "<offline-config>", "exec")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.network_calls = 0
        self.socket_patch = patch.object(socket.socket, "connect", self.forbid_network)
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)

    def forbid_network(self, *args, **kwargs):
        self.network_calls += 1
        raise RuntimeError("Offline test blocked an external boundary")

    def tearDown(self):
        self.assertEqual(self.network_calls, 0, "Configuration reached an external boundary")

    def run_value(self, name):
        from run import load_runtime_setting
        return load_runtime_setting(name)

    def tts_function(self, name):
        from MobileAgent import api
        dependencies = patch.dict(sys.modules, {
            "openai": SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=self.forbid_network),
            "requests": SimpleNamespace(post=self.forbid_network),
        })
        dependencies.start()
        self.addCleanup(dependencies.stop)
        return getattr(api, name)

    def eval_settings(self):
        namespace = {
            "ast": ast, "os": os, "Path": Path,
            "Dict": dict, "Any": object,
            "RuntimeSettings": SimpleNamespace, "MODEL_NAME": "fixed-test-model",
        }
        exec(selected_code("evaluation/androidcontrol_eval.py", {
            "parse_literal_assignments", "load_runtime_settings",
        }), namespace)
        return namespace["load_runtime_settings"](ROOT)

    def test_run_requires_each_credential(self):
        for name in ("API_url", "token", "qwen_api"):
            with self.subTest(setting=name):
                with self.assertRaises(RuntimeError):
                    self.run_value(name)

    def test_run_rejects_empty_whitespace_and_placeholder(self):
        for value in ("", " ", "REPLACE_WITH_YOUR_TOKEN", "your-api-key", "changeme"):
            with self.subTest(value_kind="invalid"):
                os.environ["FOCALFLOW_CHAT_API_TOKEN"] = value
                with self.assertRaises(RuntimeError):
                    self.run_value("token")

    def test_run_uses_explicit_environment(self):
        for name, env, value in (
            ("API_url", "FOCALFLOW_CHAT_API_URL", ENV_URL),
            ("token", "FOCALFLOW_CHAT_API_TOKEN", ENV_TOKEN),
            ("qwen_api", "DASHSCOPE_API_KEY", ENV_TOKEN),
        ):
            with self.subTest(setting=name):
                os.environ[env] = value
                self.assertTrue(self.run_value(name) == value, "Environment setting was not used")

    def test_missing_tts_credentials_stop_before_external_boundary(self):
        os.environ["FOCALFLOW_LEGACY_TTS_API_URL"] = ENV_URL
        for name in ("text2audio", "text2audio_old"):
            with self.subTest(function=name):
                with self.assertRaises(RuntimeError):
                    self.tts_function(name)("synthetic text")

    def test_tts_rejects_placeholder_environment(self):
        os.environ["FOCALFLOW_LEGACY_TTS_API_URL"] = ENV_URL
        os.environ["OPENAI_API_KEY"] = "REPLACE_WITH_YOUR_TOKEN"
        os.environ["FOCALFLOW_LEGACY_TTS_API_TOKEN"] = "REPLACE_WITH_YOUR_TOKEN"
        for name in ("text2audio", "text2audio_old"):
            with self.subTest(function=name):
                with self.assertRaises(RuntimeError):
                    self.tts_function(name)("synthetic text")

    def test_tts_rejects_explicit_placeholder_instead_of_falling_back(self):
        os.environ["FOCALFLOW_LEGACY_TTS_API_URL"] = ENV_URL
        os.environ["OPENAI_API_KEY"] = ENV_TOKEN
        os.environ["FOCALFLOW_LEGACY_TTS_API_TOKEN"] = ENV_TOKEN
        for name in ("text2audio", "text2audio_old"):
            with self.subTest(function=name):
                with self.assertRaises(RuntimeError):
                    self.tts_function(name)("synthetic text", API_TOKEN="your-api-key")

    def test_legacy_tts_requires_nonplaceholder_endpoint(self):
        os.environ["FOCALFLOW_LEGACY_TTS_API_TOKEN"] = ENV_TOKEN
        for url in (None, "https://tts.invalid/v1/audio/speech"):
            if url is not None:
                os.environ["FOCALFLOW_LEGACY_TTS_API_URL"] = url
            with self.subTest(endpoint="missing" if url is None else "placeholder"):
                with self.assertRaises(RuntimeError):
                    self.tts_function("text2audio_old")("synthetic text")

    def test_eval_requires_environment(self):
        with self.assertRaises(RuntimeError):
            self.eval_settings()

    def test_eval_accepts_chat_environment(self):
        os.environ.update(FOCALFLOW_CHAT_API_URL=ENV_URL, FOCALFLOW_CHAT_API_TOKEN=ENV_TOKEN)
        settings = self.eval_settings()
        self.assertTrue(settings.api_url == ENV_URL, "Chat URL was not used")
        self.assertTrue(settings.api_token == ENV_TOKEN, "Chat token was not used")

    def test_eval_legacy_environment_keeps_precedence(self):
        os.environ.update(
            FOCALFLOW_API_URL=ENV_URL, FOCALFLOW_API_TOKEN=ENV_TOKEN,
            FOCALFLOW_CHAT_API_URL="https://other-offline.test/chat",
            FOCALFLOW_CHAT_API_TOKEN="another-nonfunctional-test-token",
        )
        settings = self.eval_settings()
        self.assertTrue(settings.api_url == ENV_URL, "Legacy URL precedence changed")
        self.assertTrue(settings.api_token == ENV_TOKEN, "Legacy token precedence changed")

    def test_eval_rejects_placeholder(self):
        os.environ.update(FOCALFLOW_API_URL=ENV_URL, FOCALFLOW_API_TOKEN="REPLACE_WITH_YOUR_TOKEN")
        with self.assertRaises(RuntimeError):
            self.eval_settings()

    def test_configuration_errors_do_not_echo_values(self):
        marker = "REPLACE_WITH_PRIVATE_TEST_MARKER"
        os.environ["FOCALFLOW_CHAT_API_TOKEN"] = marker
        with self.assertRaises(RuntimeError) as caught:
            self.run_value("token")
        self.assertNotIn(marker, str(caught.exception))

    def test_every_example_value_is_rejected(self):
        from MobileAgent.config import require_env
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            name, value = line.split("=", 1)
            with self.subTest(environment=name):
                os.environ[name] = value
                with self.assertRaises(RuntimeError) as caught:
                    require_env(name)
                self.assertNotIn(value, str(caught.exception))

    def test_tts_uses_environment_or_explicit_token_at_provider_boundary(self):
        class ProviderBoundaryReached(BaseException):
            pass

        for name, env in (("text2audio", "OPENAI_API_KEY"),
                          ("text2audio_old", "FOCALFLOW_LEGACY_TTS_API_TOKEN")):
            for explicit in (None, "explicit-nonfunctional-unit-test-token"):
                with self.subTest(function=name, explicit=explicit is not None):
                    os.environ[env] = ENV_TOKEN
                    os.environ["FOCALFLOW_LEGACY_TTS_API_URL"] = ENV_URL
                    function = self.tts_function(name)
                    captured = []

                    def client_boundary(**kwargs):
                        captured.append(kwargs["api_key"])
                        raise ProviderBoundaryReached()

                    def request_boundary(url, **kwargs):
                        captured.append((url, kwargs["headers"]["Authorization"]))
                        raise ProviderBoundaryReached()

                    sys.modules["openai"] = SimpleNamespace(DefaultHttpxClient=lambda **kw: SimpleNamespace(close=lambda: None), OpenAI=client_boundary)
                    sys.modules["requests"] = SimpleNamespace(post=request_boundary)
                    with self.assertRaises(ProviderBoundaryReached):
                        function("synthetic text", API_TOKEN=explicit)
                    expected = ENV_TOKEN if explicit is None else explicit
                    if name == "text2audio_old":
                        expected = (ENV_URL, "Bearer " + expected)
                    self.assertTrue(captured == [expected], "Configured token was not passed to the provider")


if __name__ == "__main__":
    unittest.main()
