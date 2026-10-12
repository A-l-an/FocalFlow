"""Relocation checks import entry points only; no configuration/device/API reads."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]


def entry(name):
    path = BACKEND / 'tools/manual_testing' / (name + '.py')
    spec = importlib.util.spec_from_file_location('portable_' + name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortableEntrypointsTests(unittest.TestCase):
    def test_imported_launcher_and_runtime_resolve_this_backend(self):
        with patch.dict(os.environ, {}, clear=True):
            launcher, runtime = entry('manual_test'), entry('live_backend')
        self.assertEqual(Path(launcher.SOURCE), BACKEND)
        self.assertEqual(Path(runtime.SOURCE), BACKEND)
        self.assertEqual(launcher.PYTHON, sys.executable)
        self.assertEqual(launcher.CONFIG, Path.home() / '.config/focalflow/providers.env')
        self.assertEqual(runtime.CONFIG, launcher.CONFIG)

    def test_explicit_operator_paths_are_selected_before_defaults_bind(self):
        with tempfile.TemporaryDirectory(prefix='focalflow-portable-paths-') as folder:
            root = Path(folder)
            paths = {'FOCALFLOW_PYTHON': str(root / 'python'),
                     'FOCALFLOW_ADB': str(root / 'fake-adb'),
                     'FOCALFLOW_CONFIG': str(root / 'synthetic.env'),
                     'FOCALFLOW_STATE_DIR': str(root / 'state'),
                     'FOCALFLOW_RUN_DIR': str(root / 'run')}
            with patch.dict(os.environ, paths, clear=True):
                launcher, runtime = entry('manual_test'), entry('live_backend')
            self.assertEqual(launcher.PYTHON, paths['FOCALFLOW_PYTHON'])
            self.assertEqual(launcher.ADB, paths['FOCALFLOW_ADB'])
            self.assertEqual(launcher.disable_phone_service.__defaults__, (paths['FOCALFLOW_ADB'],))
            self.assertEqual(launcher.CONFIG, root / 'synthetic.env')
            self.assertEqual(runtime.CONFIG, launcher.CONFIG)
            self.assertEqual(launcher.BASE, root / 'state')
            self.assertEqual(runtime.ART, root / 'run')
