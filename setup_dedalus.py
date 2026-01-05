from pathlib import Path
import subprocess, os, sys

# ==================================================
# Repository-relative paths
# ==================================================
# Note: In a real repo, this would be __file__. 
# If running directly in Colab cell as a script, we assume CWD is the root.

REPO_DIR = Path(__file__).resolve().parent

INSTALL_SCRIPT = REPO_DIR / "setup" / "install_dedalus.sh"
MAGIC_FILE     = REPO_DIR / "magic" / "dedalus_magic.py"

# ==================================================
# Helpers
# ==================================================
def run(cmd, cwd=None):
    result = subprocess.run(
        cmd, 
        cwd=cwd, 
        check=True,
        capture_output=False, # Let output flow to stdout
        text=True
    )
    return result

# ==================================================
# 1. Install / update Dedalus environment
# ==================================================
opts = sys.argv[1:]
print("🔧 Installing Dedalus environment...")
# Make script executable just in case
subprocess.run(["chmod", "+x", str(INSTALL_SCRIPT)])
run(["bash", str(INSTALL_SCRIPT), *opts], cwd=REPO_DIR)

# ==================================================
# 2. Load %%dedalus magic
# ==================================================
print("✨ Loading Dedalus Jupyter magic...", end=" ")
if MAGIC_FILE.exists():
    code = MAGIC_FILE.read_text()
    exec(compile(code, str(MAGIC_FILE), "exec"), globals())
    # Manually load the extension since we are exec-ing inside a script
    try:
        load_ipython_extension(get_ipython())
        print("%%dedalus registered ✅")
    except Exception as e:
        print(f"\n⚠️ Failed to register magic: {e}")
else:
    print(f"\n❌ Magic file not found: {MAGIC_FILE}")