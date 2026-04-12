import unittest
from pathlib import Path


class TestAssetVersioning(unittest.TestCase):
    def test_stylesheet_is_versioned(self):
        p = Path(__file__).resolve().parents[1] / "app" / "templates" / "base.html"
        txt = p.read_text(encoding="utf-8")
        self.assertIn("css/styles.css') }}?v={{ app_version", txt)

    def test_holding_history_js_is_versioned(self):
        p = Path(__file__).resolve().parents[1] / "app" / "templates" / "holding_detail.html"
        txt = p.read_text(encoding="utf-8")
        self.assertIn("js/holding-history.js') }}?v={{ app_version", txt)
