from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from rainbowl_app import env


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class EnvLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_loaded = env._ENV_LOADED
        env._ENV_LOADED = False

    def tearDown(self) -> None:
        env._ENV_LOADED = self.original_loaded

    def test_last_duplicate_value_wins_inside_env_file(self) -> None:
        env_path = FIXTURES_DIR / "duplicate.env"
        with patch.dict(os.environ, {}, clear=True):
            env.load_env_file(env_path)
            self.assertEqual(os.environ["DB_HOST"], "supabase.example.com")

    def test_existing_process_environment_is_preserved(self) -> None:
        env_path = FIXTURES_DIR / "single.env"
        with patch.dict(os.environ, {"DB_HOST": "already-set.example.com"}, clear=True):
            env.load_env_file(env_path)
            self.assertEqual(os.environ["DB_HOST"], "already-set.example.com")
