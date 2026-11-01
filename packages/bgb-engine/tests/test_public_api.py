"""The engine's public import surface."""

import subprocess
import sys
from unittest import TestCase

import bgb_engine


class PublicApiTests(TestCase):
    def test_version_is_exposed(self):
        self.assertEqual(bgb_engine.__version__, '0.1.0')

    def test_the_contract_and_views_are_exported(self):
        for name in ('GameDefinition', 'Context', 'Action', 'RenderModel',
                     'GraphView', 'GridView', 'PendingSpec', 'Transition',
                     'BoardGraph', 'BoardGrid', 'Counters', 'PhaseMachine',
                     'TurnOrder'):
            self.assertTrue(hasattr(bgb_engine, name), name)

    def test_importing_the_engine_does_not_import_django(self):
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys, bgb_engine; '
             'raise SystemExit("django" in sys.modules)'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
