import os
import shutil
import subprocess
import tempfile
import unittest


def _find_agy() -> str:
    exe = shutil.which("agy")
    if exe:
        return exe
    candidate = os.path.join(
        os.path.expanduser("~"), "AppData", "Local", "agy", "bin", "agy.exe"
    )
    return candidate if os.path.exists(candidate) else ""


def _agy_env() -> dict:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    for key in list(env.keys()):
        if key.startswith(("ANTIGRAVITY_", "CODEX_")):
            del env[key]
        elif key.startswith("GEMINI_") and key not in ("GEMINI_API_KEY", "GEMINI_MODEL"):
            del env[key]
    gemini_dir = os.path.abspath(os.path.join(os.path.expanduser("~"), ".gemini"))
    env["GEMINI_DIR"] = gemini_dir
    env["GEMINI_HOME"] = gemini_dir
    return env


class AgyCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = _find_agy()
        if not cls.exe:
            raise unittest.SkipTest("agy executable not found")
        cls.prompt = "Reply with exactly: HELLO_TEST_123"
        cls.cwd = os.path.expanduser("~")
        cls.env = _agy_env()

    def test_temp_file_redirection_exits_cleanly(self):
        out_file = os.path.join(tempfile.gettempdir(), "agy_test_stdout.txt")
        err_file = os.path.join(tempfile.gettempdir(), "agy_test_stderr.txt")
        try:
            with open(out_file, "w", encoding="utf-8") as fout, open(
                err_file, "w", encoding="utf-8"
            ) as ferr:
                proc = subprocess.Popen(
                    [self.exe, "--print", self.prompt, "--dangerously-skip-permissions"],
                    stdin=subprocess.DEVNULL,
                    stdout=fout,
                    stderr=ferr,
                    cwd=self.cwd,
                    env=self.env,
                )
                proc.wait(timeout=20)
            with open(err_file, "r", encoding="utf-8", errors="replace") as ferr:
                stderr_txt = ferr.read()
            self.assertEqual(proc.returncode, 0, stderr_txt)
        finally:
            for path in (out_file, err_file):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def test_pipe_capture_exits_cleanly(self):
        proc = subprocess.run(
            [self.exe, "--print", self.prompt, "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.cwd,
            env=self.env,
            creationflags=0x08000000 if os.name == "nt" else 0,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
