"""Test different methods to capture agy.EXE output on Windows."""
import subprocess, os, sys, time, tempfile

exe = r"C:\Users\franc\AppData\Local\agy\bin\agy.EXE"
prompt = "Reply with exactly: HELLO_TEST_123"
timeout = 30

env = os.environ.copy()
env["NO_COLOR"] = "1"
# Clear antigravity env vars like the real code does
for k in list(env.keys()):
    if k.startswith("ANTIGRAVITY_") or k.startswith("CODEX_"):
        del env[k]
    elif k.startswith("GEMINI_") and k not in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        del env[k]

gemini_dir = os.path.abspath(os.path.join(os.path.expanduser("~"), ".gemini"))
env["GEMINI_DIR"] = gemini_dir
env["GEMINI_HOME"] = gemini_dir

cwd = os.path.expanduser("~")

print("=" * 60)
print("TEST: Using temp file redirection via Popen + manual read")
print("=" * 60)

out_file = os.path.join(tempfile.gettempdir(), "agy_test_stdout.txt")
err_file = os.path.join(tempfile.gettempdir(), "agy_test_stderr.txt")

try:
    with open(out_file, "w", encoding="utf-8") as fout, \
         open(err_file, "w", encoding="utf-8") as ferr:
        proc = subprocess.Popen(
            [exe, "--print", prompt, "--dangerously-skip-permissions"],
            stdin=subprocess.DEVNULL,
            stdout=fout,
            stderr=ferr,
            cwd=cwd,
            env=env,
        )
        t0 = time.time()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        dt = time.time() - t0

    stdout_txt = open(out_file, "r", encoding="utf-8", errors="replace").read()
    stderr_txt = open(err_file, "r", encoding="utf-8", errors="replace").read()

    print(f"  Return code: {proc.returncode}")
    print(f"  Duration: {dt:.1f}s")
    print(f"  STDOUT len: {len(stdout_txt)}")
    print(f"  STDERR len: {len(stderr_txt)}")
    print(f"  STDOUT: [{stdout_txt[:300]}]")
    print(f"  STDERR: [{stderr_txt[:300]}]")
except Exception as e:
    print(f"  ERROR: {e}")

os.unlink(out_file) if os.path.exists(out_file) else None
os.unlink(err_file) if os.path.exists(err_file) else None

print()
print("=" * 60)
print("TEST: Using CREATE_NO_WINDOW + PIPE")  
print("=" * 60)

try:
    proc = subprocess.Popen(
        [exe, "--print", prompt, "--dangerously-skip-permissions"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    t0 = time.time()
    try:
        stdout_txt, stderr_txt = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_txt, stderr_txt = proc.communicate()
    dt = time.time() - t0

    print(f"  Return code: {proc.returncode}")
    print(f"  Duration: {dt:.1f}s")
    print(f"  STDOUT len: {len(stdout_txt)}")
    print(f"  STDERR len: {len(stderr_txt)}")
    print(f"  STDOUT: [{stdout_txt[:300]}]")
    print(f"  STDERR: [{stderr_txt[:300]}]")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nDone.")
