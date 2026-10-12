"""The legacy manual probe must never call a provider without explicit opt-in."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROBE = Path(__file__).resolve().parents[1] / 'test.py'


class ManualProbeTests(unittest.TestCase):
    def execute(self, arguments, module_name='__main__'):
        calls = []
        output = io.StringIO()
        # TTS owns network and audio: replace only that external operation.
        with patch.dict(sys.modules, {
                'MobileAgent.api': SimpleNamespace(text2audio=calls.append)}), \
                patch.object(sys, 'argv', [str(PROBE)] + arguments), \
                contextlib.redirect_stdout(output):
            runpy.run_path(str(PROBE), run_name=module_name)
        return calls, output.getvalue()

    def test_default_cli_has_no_provider_or_audio_call(self):
        calls, output = self.execute([])
        self.assertEqual(len(calls), 0, 'Default probe attempted live TTS')
        self.assertIn('--live', output)

    def test_import_has_no_provider_or_audio_call(self):
        calls, _ = self.execute([], module_name='manual_probe_import')
        self.assertEqual(len(calls), 0)

    def test_explicit_live_uses_one_short_synthetic_phrase(self):
        calls, _ = self.execute(['--live'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].strip())
        self.assertLess(len(calls[0]), 80, 'Probe still contains a long sample')
        self.assertNotIn('\n', calls[0])
