import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.asr import factory
from src.asr.engines.funasr import (
    REQUIRED_MODEL_FILES,
    convert_funasr_text,
    resolve_funasr_model,
)


class FunASRLocalModelTests(unittest.TestCase):
    def test_converts_simplified_output_to_taiwan_traditional(self):
        self.assertEqual(
            convert_funasr_text("软件和鼠标", "traditional-tw"),
            "軟體和滑鼠",
        )

    def test_can_keep_original_simplified_output(self):
        self.assertEqual(
            convert_funasr_text("软件和鼠标", "simplified"),
            "软件和鼠标",
        )

    def test_factory_forwards_selected_model_to_funasr(self):
        engine = factory.create_asr_engine(
            "funasr",
            model_size="/models/paraformer-zh",
        )

        self.assertEqual(engine.model_name, "/models/paraformer-zh")

    def test_paraformer_alias_prefers_complete_local_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            for filename in REQUIRED_MODEL_FILES:
                (model_dir / filename).write_bytes(b"model")

            with patch("src.asr.engines.funasr.LOCAL_MODEL_DIR", model_dir):
                self.assertEqual(resolve_funasr_model("paraformer-zh"), str(model_dir))

    def test_paraformer_alias_falls_back_when_local_model_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.asr.engines.funasr.LOCAL_MODEL_DIR", Path(tmp)):
                self.assertEqual(resolve_funasr_model("paraformer-zh"), "paraformer-zh")

    def test_model_load_disables_network_update_check(self):
        from src.asr.engines.funasr import FunASR

        auto_model = Mock(return_value=object())
        with patch("funasr.AutoModel", auto_model):
            engine = FunASR(model_name="/models/paraformer-zh")
            engine.ensure_ready()

        auto_model.assert_called_once_with(
            model="/models/paraformer-zh",
            disable_update=True,
        )


if __name__ == "__main__":
    unittest.main()
