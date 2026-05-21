import os
import subprocess

def run_agy(mode: str):
    env = os.environ.copy()
    if mode == "clean":
        for k in list(env.keys()):
            if k.startswith("ANTIGRAVITY_") or k.startswith("GEMINI_") or k.startswith("CODEX_"):
                del env[k]
    elif mode == "fixed":
        for k in list(env.keys()):
            if k.startswith("ANTIGRAVITY_") or k.startswith("GEMINI_") or k.startswith("CODEX_"):
                del env[k]
        gemini_dir = os.path.abspath(os.path.join(os.path.expanduser("~"), ".gemini"))
        env["GEMINI_DIR"] = gemini_dir
        env["GEMINI_HOME"] = gemini_dir
    
    # Locate agy.exe
    import shutil
    exe = shutil.which("agy")
    if not exe:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            candidate = os.path.join(local_app_data, "agy", "bin", "agy.exe")
            if os.path.exists(candidate):
                exe = candidate
    if not exe:
        home = os.path.expanduser("~")
        candidate = os.path.join(home, "AppData", "Local", "agy", "bin", "agy.exe")
        if os.path.exists(candidate):
            exe = candidate
    if not exe:
        exe = "agy"
        
    cmd = [exe, "--print", "Translate hello to Thai.", "--dangerously-skip-permissions"]
    print(f"Running with mode={mode} using {exe}...")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        stdout, stderr = proc.communicate(timeout=15)
        print(f"Return code: {proc.returncode}")
        print(f"Stdout len: {len(stdout)}")
        print(f"Stderr len: {len(stderr)}")
        print(f"Stdout: {stdout.strip()!r}")
        print(f"Stderr: {stderr.strip()!r}")
    except Exception as e:
        print(f"Failed: {e}")

print("--- Test 1: Inherited Env ---")
run_agy("inherited")
print("\n--- Test 2: Clean Env ---")
run_agy("clean")
print("\n--- Test 3: Fixed Env (GEMINI_DIR absolute) ---")
run_agy("fixed")

