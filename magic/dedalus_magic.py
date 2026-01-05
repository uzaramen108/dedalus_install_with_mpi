# ==================================================
# dedalus_magic.py 
# ==================================================

import os, subprocess, tempfile, textwrap, shlex
from IPython.core.magic import register_cell_magic

# --------------------------------------------------
# Hard-coded micromamba path
# --------------------------------------------------
MICROMAMBA = "/content/micromamba/bin/micromamba"
ENV_NAME = "dedalus"

# --------------------------------------------------
# MPI detection helpers
# --------------------------------------------------
def detect_mpi(env):
    try:
        # Check MPI version inside the micromamba environment
        cmd = [MICROMAMBA, "run", "-n", ENV_NAME, "mpiexec", "--version"]
        out = subprocess.run(
            cmd,
            env=env, capture_output=True, text=True, timeout=5
        )
        txt = (out.stdout + out.stderr).lower()
        if "open mpi" in txt or "open-mpi" in txt:
            return "openmpi"
    except Exception:
        pass
    return "mpich"

def mpi_version(env):
    try:
        cmd = [MICROMAMBA, "run", "-n", ENV_NAME, "mpiexec", "--version"]
        out = subprocess.run(
            cmd,
            env=env, capture_output=True, text=True, timeout=5
        )
        return (out.stdout + out.stderr).splitlines()[0]
    except Exception:
        return "unknown"


# --------------------------------------------------
# %%dedalus cell magic
# --------------------------------------------------
@register_cell_magic
def dedalus(line, cell):
    args = shlex.split(line)

    # -----------------------------
    # Options
    # -----------------------------
    np = 1
    info_mode = "--info" in args
    time_mode = "--time" in args

    if "-np" in args:
        try:
            np = int(args[args.index("-np") + 1])
        except (ValueError, IndexError):
            print("❌ Error: -np option requires an integer argument")
            return

    # -----------------------------
    # Environment
    # -----------------------------
    env = os.environ.copy()
    # OpenMPI often requires these flags to run as root in containers (Colab)
    env.update({
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
        "OMP_NUM_THREADS": "1",        # Avoid thread oversubscription
        "NUMEXPR_MAX_THREADS": "1",
    })

    mpi_impl = detect_mpi(env)
    mpi_ver  = mpi_version(env)

    # -----------------------------
    # Command builder
    # -----------------------------
    def build_cmd(script):
        # Even for np=1, running through mpiexec ensures the environment is consistent
        # But `python script.py` is faster for serial. Let's stick to MPI logic if requested.
        
        launcher = "mpirun" if mpi_impl == "openmpi" else "mpiexec"
        
        if np == 1 and not info_mode:
             # Serial execution optimization (optional, but safe to use mpiexec always)
             pass 

        return [
            MICROMAMBA, "run", "-n", ENV_NAME,
            launcher, "-n", str(np),
            "python", script
        ]

    # -----------------------------
    # --info mode
    # -----------------------------
    if info_mode:
        info_code = """
import dedalus.public as d3
from mpi4py import MPI
import sys, platform, os

comm = MPI.COMM_WORLD
if comm.rank == 0:
    print()
    print("🐍 Python          :", sys.version.split()[0])
    print("🌊 Dedalus         :", d3.__version__)
    print("💻 Platform        :", platform.platform())
    print("🧵 Running as root :", os.geteuid() == 0)
    print("⚡ MPI Size        :", comm.Get_size())
"""
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(info_code)
            script = f.name

        try:
            res = subprocess.run(
                build_cmd(script),
                env=env, capture_output=True, text=True
            )
            print(res.stdout, end="")
            print(res.stderr, end="")
        finally:
            os.remove(script)

        print("\n🔎 Dedalus runtime info")
        print("-----------------------")
        print(f"Environment        : {ENV_NAME}")
        print(f"micromamba         : {MICROMAMBA}")
        print(f"MPI implementation : {mpi_impl.upper()}")
        print(f"MPI version        : {mpi_ver}")
        print(f"MPI ranks (-np)    : {np}")
        return

    # -----------------------------
    # Normal execution (with optional timing)
    # -----------------------------
    user_code = textwrap.dedent(cell)

    if time_mode:
        wrapped = f"""
from mpi4py import MPI
import time

_comm = MPI.COMM_WORLD
_rank = _comm.rank
_size = _comm.size

# -----------------
# synchronize before timing
# -----------------
_comm.Barrier()
_t0 = time.perf_counter()

# -----------------
# User code
# -----------------
try:
{textwrap.indent(user_code, '    ')}
except Exception as e:
    import traceback
    traceback.print_exc()
    _comm.Abort(1)

# -----------------
# synchronize after user code
# -----------------
_comm.Barrier()
_t1 = time.perf_counter()

# -----------------
# elapsed time only on rank 0
# -----------------
if _rank == 0:
    print(f"⏱ Elapsed time: {{_t1 - _t0:.6f}} s")
"""
    else:
        # Simple wrapping to catch errors and abort MPI properly
        wrapped = f"""
try:
{textwrap.indent(user_code, '    ')}
except Exception as e:
    import traceback
    from mpi4py import MPI
    traceback.print_exc()
    MPI.COMM_WORLD.Abort(1)
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(wrapped)
        script = f.name

    try:
        # Real-time output streaming is tricky with subprocess.run capture_output=True.
        # But capture_output=False prints to the console directly which is what we want in Colab cells.
        # FEniCSx script used capture_output=True which buffers output until the end.
        # For long simulations, we might want to stream it. 
        # But let's keep consistency with the FEniCSx logic first.
        
        # Using Popen to stream output line by line for long running Dedalus sims
        process = subprocess.Popen(
            build_cmd(script),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        for line in process.stdout:
            print(line, end="")
            
        process.wait()
        
    finally:
        if os.path.exists(script):
            os.remove(script)