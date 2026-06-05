import subprocess
import sys
import time
import unittest
from pathlib import Path


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_app_compiles(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        app_file = project_root / "app.py"
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(app_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"py_compile failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_streamlit_starts_headless(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        app_file = project_root / "app.py"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app_file),
                "--server.headless",
                "true",
                "--server.port",
                "8765",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=2)
                    self.fail(
                        "Streamlit exited early.\n"
                        f"exit={process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
                    )
                time.sleep(0.4)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            # Drain/close pipes to avoid ResourceWarning in unittest.
            process.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
