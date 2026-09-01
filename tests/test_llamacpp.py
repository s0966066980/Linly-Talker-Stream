import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.llamacpp import (
    build_server_env,
    cuda_library_dirs,
    find_llama_server,
    gguf_block_count,
    resolve_gguf,
    stop_llama_on_port,
    shutdown_llama_server,
    suggest_gpu_layers,
)


class CudaLibraryDiscoveryTests(unittest.TestCase):
    def test_includes_directory_that_has_libcudart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "libcudart.so.12").write_bytes(b"x")
            found = cuda_library_dirs(extra_roots=[root])
            self.assertIn(root.resolve(), [path.resolve() for path in found])

    def test_skips_directory_without_cuda_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "readme.txt").write_text("nope")
            found = cuda_library_dirs(extra_roots=[root])
            self.assertNotIn(root.resolve(), [path.resolve() for path in found])

    def test_build_server_env_puts_cuda_dir_on_ld_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            cuda_dir = Path(tmp) / "cuda"
            bin_dir.mkdir()
            cuda_dir.mkdir()
            (cuda_dir / "libcudart.so.12").write_bytes(b"x")
            binary = bin_dir / "llama-server"
            binary.write_text("#!/bin/sh\n")
            with patch("src.llm.llamacpp.cuda_library_dirs", return_value=[cuda_dir]):
                env = build_server_env(binary)
            parts = env["LD_LIBRARY_PATH"].split(":")
            self.assertEqual(parts[0], str(bin_dir))
            self.assertIn(str(cuda_dir), parts)


class GpuLayerPlanningTests(unittest.TestCase):
    def test_fits_all_layers_when_vram_is_enough(self):
        self.assertEqual(suggest_gpu_layers(2 * 1024**3, 12000, 32), 99)

    def test_partial_offload_when_vram_is_tight(self):
        layers = suggest_gpu_layers(16 * 1024**3, 10000, 65)
        self.assertGreater(layers, 0)
        self.assertLess(layers, 65)

    def test_cpu_only_when_no_free_vram(self):
        self.assertEqual(suggest_gpu_layers(16 * 1024**3, 512, 65), 0)

    def test_reads_qwen_block_count(self):
        gguf = resolve_gguf("Qwen3.8-27B-Q4_K_M", extra_dir=str(Path.home() / "llama"))
        if gguf is None:
            self.skipTest("Qwen3.8-27B-Q4_K_M.gguf is not installed")
        self.assertEqual(gguf_block_count(gguf), 65)


class StopLlamaOnPortTests(unittest.TestCase):
    def test_refuses_to_kill_unrelated_process(self):
        with patch("src.llm.llamacpp._pids_listening_on", return_value=[4242]):
            with patch("src.llm.llamacpp._process_cmdline", return_value="python app.py"):
                with self.assertRaises(RuntimeError) as ctx:
                    stop_llama_on_port(8080)
        self.assertIn("其他程式", str(ctx.exception))

    def test_stops_leftover_llama_server(self):
        killed = []

        def fake_kill(pid, sig):
            killed.append((pid, sig))
            if sig == 15:
                raise ProcessLookupError

        with patch("src.llm.llamacpp._pids_listening_on", return_value=[335955]):
            with patch(
                "src.llm.llamacpp._process_cmdline",
                return_value="/home/oliver/llama/llama.cpp/build/bin/llama-server -m LFM.gguf",
            ):
                with patch("src.llm.llamacpp.os.kill", side_effect=fake_kill):
                    stop_llama_on_port(8080)
        self.assertEqual(killed[0][0], 335955)


class ShutdownOwnedServerTests(unittest.TestCase):
    def test_shutdown_stops_only_owned_process_and_is_idempotent(self):
        import src.llm.llamacpp as llamacpp

        class Process:
            def __init__(self):
                self.terminate_count = 0
                self.kill_count = 0

            def poll(self):
                return None if self.terminate_count == 0 else 0

            def terminate(self):
                self.terminate_count += 1

            def wait(self, timeout):
                return 0

            def kill(self):
                self.kill_count += 1

        process = Process()
        with patch.object(llamacpp, "_server_proc", process), patch.object(
            llamacpp, "_loaded_model", "LFM"
        ):
            shutdown_llama_server()
            shutdown_llama_server()

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 0)
        self.assertIsNone(llamacpp._server_proc)
        self.assertEqual(llamacpp._loaded_model, "")

    def test_shutdown_does_not_discover_or_kill_external_server(self):
        import src.llm.llamacpp as llamacpp

        with patch.object(llamacpp, "_server_proc", None), patch.object(
            llamacpp, "stop_llama_on_port"
        ) as stop:
            shutdown_llama_server()

        stop.assert_not_called()


class LlamaServerLaunchEnvTests(unittest.TestCase):
    def test_llama_server_loads_with_discovered_cuda_libs(self):
        binary = find_llama_server()
        if binary is None:
            self.skipTest("llama-server is not installed")
        env = build_server_env(binary)
        result = subprocess.run(
            [str(binary), "-h"],
            env=env,
            cwd=str(binary.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertNotIn("libcudart.so.12", combined)
        self.assertEqual(result.returncode, 0, combined[-500:])


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    unittest.main()
