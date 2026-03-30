"""Tests for the config parser.

Run with: pytest test_task13.py -v
"""
from pathlib import Path
import pytest

spec_path = Path(__file__).parent / "fixed_parser.py"
if not spec_path.exists():
    pytest.skip("fixed_parser.py not found", allow_module_level=True)

from fixed_parser import load_config, get_setting, merge_configs


class TestBasicParsing:

    def test_simple_key_value(self):
        config = load_config("host:localhost")
        assert config["host"] == "localhost"

    def test_multiple_lines(self):
        text = "host:localhost\nport:8080\nenv:production"
        config = load_config(text)
        assert config["host"] == "localhost"
        assert config["port"] == "8080"
        assert config["env"] == "production"

    def test_whitespace_stripped_from_key(self):
        config = load_config("  host : localhost  ")
        assert "host" in config
        assert config["host"] == "localhost"

    def test_whitespace_stripped_from_value(self):
        config = load_config("host:  localhost  ")
        assert config["host"] == "localhost"


class TestEdgeCases:

    def test_value_with_colon(self):
        """Values containing ':' must not be split (e.g. URLs)."""
        config = load_config("endpoint:http://api.example.com:8080")
        assert config["endpoint"] == "http://api.example.com:8080"

    def test_value_with_multiple_colons(self):
        config = load_config("schedule:12:30:00")
        assert config["schedule"] == "12:30:00"

    def test_empty_lines_ignored(self):
        text = "host:localhost\n\nport:8080\n"
        config = load_config(text)
        assert len(config) == 2
        assert "host" in config
        assert "port" in config

    def test_comment_lines_ignored(self):
        text = "# this is a comment\nhost:localhost\n# another comment\nport:8080"
        config = load_config(text)
        assert len(config) == 2
        assert "host" in config

    def test_empty_string(self):
        config = load_config("")
        assert config == {}


class TestGetSetting:

    def test_existing_key(self):
        config = {"host": "localhost", "port": "8080"}
        assert get_setting(config, "host") == "localhost"

    def test_missing_key_returns_none(self):
        config = {"host": "localhost"}
        assert get_setting(config, "port") is None

    def test_missing_key_returns_default(self):
        config = {"host": "localhost"}
        assert get_setting(config, "port", default="9090") == "9090"

    def test_missing_key_default_false(self):
        config = {}
        assert get_setting(config, "debug", default=False) is False


class TestMergeConfigs:

    def test_merge_no_overlap(self):
        base = {"host": "localhost"}
        override = {"port": "8080"}
        result = merge_configs(base, override)
        assert result["host"] == "localhost"
        assert result["port"] == "8080"

    def test_override_wins(self):
        base = {"host": "localhost", "port": "8080"}
        override = {"port": "9090"}
        result = merge_configs(base, override)
        assert result["port"] == "9090"
        assert result["host"] == "localhost"

    def test_base_unchanged(self):
        base = {"host": "localhost"}
        override = {"host": "remotehost"}
        merge_configs(base, override)
        assert base["host"] == "localhost"
