import json
import unittest
from pathlib import Path

from app.config import config
from webui import visibility as vis

ROOT = Path(__file__).parent.parent.parent


class TestVisibilityHelpers(unittest.TestCase):
    PAIRS = [("Pexels", "pexels"), ("Pixabay", "pixabay"), ("Local", "local")]

    def setUp(self):
        # 仅备份/恢复测试会改动的 ui key，避免污染真实 config 对象。
        self._keys = ["enabled_video_sources", "hidden_fields"]
        self._backup = {k: config.ui.get(k) for k in self._keys}

    def tearDown(self):
        for k, v in self._backup.items():
            if v is None:
                config.ui.pop(k, None)
            else:
                config.ui[k] = v

    # --- enabled_ids ---------------------------------------------------------

    def test_enabled_ids_unset_returns_all(self):
        config.ui.pop("enabled_video_sources", None)
        self.assertEqual(
            vis.enabled_ids("enabled_video_sources", ["pexels", "pixabay"]),
            ["pexels", "pixabay"],
        )

    def test_enabled_ids_empty_returns_all(self):
        config.ui["enabled_video_sources"] = []
        self.assertEqual(
            vis.enabled_ids("enabled_video_sources", ["pexels", "pixabay"]),
            ["pexels", "pixabay"],
        )

    def test_enabled_ids_subset_preserves_catalog_order(self):
        config.ui["enabled_video_sources"] = ["local", "pexels"]  # 顺序故意打乱
        self.assertEqual(
            vis.enabled_ids("enabled_video_sources", ["pexels", "pixabay", "local"]),
            ["pexels", "local"],
        )

    def test_enabled_ids_stale_ids_filtered(self):
        config.ui["enabled_video_sources"] = ["pexels", "ghost"]
        self.assertEqual(
            vis.enabled_ids("enabled_video_sources", ["pexels", "pixabay"]),
            ["pexels"],
        )

    def test_enabled_ids_no_overlap_falls_back_to_all(self):
        config.ui["enabled_video_sources"] = ["ghost"]
        self.assertEqual(
            vis.enabled_ids("enabled_video_sources", ["pexels", "pixabay"]),
            ["pexels", "pixabay"],
        )

    # --- filter_pairs / trim -------------------------------------------------

    def test_filter_pairs_keeps_order_and_filters(self):
        out = vis.filter_pairs(self.PAIRS, {"pexels", "local"}, id_index=1)
        self.assertEqual(out, [("Pexels", "pexels"), ("Local", "local")])

    def test_filter_pairs_never_empty(self):
        out = vis.filter_pairs(self.PAIRS, set(), id_index=1)
        self.assertEqual(out, self.PAIRS)

    def test_filter_pairs_id_index_zero(self):
        tts = [("no-voice", "No Voice"), ("azure-tts-v1", "Azure V1")]
        out = vis.filter_pairs(tts, {"azure-tts-v1"}, id_index=0)
        self.assertEqual(out, [("azure-tts-v1", "Azure V1")])

    def test_trim_reads_config(self):
        config.ui["enabled_video_sources"] = ["pixabay"]
        out = vis.trim("enabled_video_sources", self.PAIRS, id_index=1)
        self.assertEqual(out, [("Pixabay", "pixabay")])

    # --- resolve_index -------------------------------------------------------

    def test_resolve_index_found(self):
        self.assertEqual(vis.resolve_index(self.PAIRS, "pixabay", "pexels", id_index=1), 1)

    def test_resolve_index_missing_uses_default(self):
        self.assertEqual(vis.resolve_index(self.PAIRS, "ghost", "local", id_index=1), 2)

    def test_resolve_index_missing_and_no_default_returns_zero(self):
        self.assertEqual(vis.resolve_index(self.PAIRS, "ghost", None, id_index=1), 0)

    def test_resolve_index_default_also_missing_returns_zero(self):
        self.assertEqual(vis.resolve_index(self.PAIRS, "ghost", "alsoghost", id_index=1), 0)

    # --- hidden fields -------------------------------------------------------

    def test_is_hidden_and_hidden_fields(self):
        config.ui["hidden_fields"] = ["video_count", "play_voice"]
        self.assertTrue(vis.is_hidden("video_count"))
        self.assertFalse(vis.is_hidden("video_aspect"))
        self.assertEqual(vis.hidden_fields(), {"video_count", "play_voice"})

    def test_hidden_fields_unset_is_empty(self):
        config.ui.pop("hidden_fields", None)
        self.assertEqual(vis.hidden_fields(), set())
        self.assertFalse(vis.is_hidden("anything"))

    # --- registry sanity -----------------------------------------------------

    def test_registry_keys_unique_and_catalogs_nonempty(self):
        config_keys = [e["config_key"] for e in vis.TRIMMABLE]
        self.assertEqual(len(config_keys), len(set(config_keys)))
        for e in vis.TRIMMABLE:
            self.assertTrue(e["catalog"], f"empty catalog for {e['config_key']}")
            self.assertIn(e["main_id_index"], (0, 1))

        field_ids = [f[0] for f in vis.HIDEABLE]
        self.assertEqual(len(field_ids), len(set(field_ids)))


class TestVisibilityWiring(unittest.TestCase):
    """Guard the contract between the registry (visibility.py) and Main.py wiring."""

    @classmethod
    def setUpClass(cls):
        cls.main_src = (ROOT / "webui" / "Main.py").read_text(encoding="utf-8")
        cls.en = json.loads(
            (ROOT / "webui" / "i18n" / "en.json").read_text(encoding="utf-8")
        )["Translation"]

    def test_every_hideable_field_is_wired_in_main(self):
        for field_id, _ in vis.HIDEABLE:
            self.assertIn(
                f'is_hidden("{field_id}")',
                self.main_src,
                f"HIDEABLE field '{field_id}' has no is_hidden() guard in Main.py",
            )

    def test_every_trim_key_is_used_in_main(self):
        for entry in vis.TRIMMABLE:
            self.assertIn(
                f'"{entry["config_key"]}"',
                self.main_src,
                f"TRIMMABLE key '{entry['config_key']}' is not referenced in Main.py",
            )

    def test_panel_labels_present_in_english_locale(self):
        keys = [
            "Visibility Settings",
            "Visibility Help",
            "Visibility Trim Dropdowns",
            "Visibility Hide Fields",
            "Visibility Hidden Fields",
            "Visibility Save",
            "Visibility Saved",
        ]
        keys += [e["label_key"] for e in vis.TRIMMABLE]
        keys += [label for _, label in vis.HIDEABLE]
        missing = [k for k in keys if k not in self.en]
        self.assertEqual(missing, [], f"missing en.json translations: {missing}")


if __name__ == "__main__":
    unittest.main()
