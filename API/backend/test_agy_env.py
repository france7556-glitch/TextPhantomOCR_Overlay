import os
import shutil
import subprocess
import unittest


def _find_agy() -> str:
    exe = shutil.which("agy")
    if exe:
        return exe
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "agy", "bin", "agy.exe"))
    candidates.append(
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "agy", "bin", "agy.exe")
    )
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return ""


def _env_for_mode(mode: str) -> dict:
    env = os.environ.copy()
    if mode in ("clean", "fixed"):
        for key in list(env.keys()):
            if key.startswith(("ANTIGRAVITY_", "GEMINI_", "CODEX_")):
                del env[key]
    if mode == "fixed":
        gemini_dir = os.path.abspath(os.path.join(os.path.expanduser("~"), ".gemini"))
        env["GEMINI_DIR"] = gemini_dir
        env["GEMINI_HOME"] = gemini_dir
    env["NO_COLOR"] = "1"
    return env


class AgyEnvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = _find_agy()
        if not cls.exe:
            raise unittest.SkipTest("agy executable not found")

    def _run_agy(self, mode: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.exe, "--print", "Translate hello to Thai.", "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_env_for_mode(mode),
            timeout=20,
        )

    def test_inherited_env_exits_cleanly(self):
        proc = self._run_agy("inherited")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_clean_env_exits_cleanly(self):
        proc = self._run_agy("clean")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_fixed_env_exits_cleanly(self):
        proc = self._run_agy("fixed")
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
