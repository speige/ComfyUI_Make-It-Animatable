from pathlib import Path
import os
import sys
import subprocess, json, tempfile
from huggingface_hub import snapshot_download
import huggingface_hub

NODE_DIR = Path(__file__).parent.resolve()
REPO_NAME = "Make_It_Animatable"
REPO_DIR = NODE_DIR / REPO_NAME

REPO_URL = "https://github.com/jasongzy/Make-It-Animatable.git"

if NODE_DIR not in sys.path:
    sys.path.insert(0, NODE_DIR)

def run_cmd(cmd):
    print(f"[Make-It-Animatable] $ {' '.join(map(str, cmd))}")
    process = subprocess.Popen(cmd, cwd=str(REPO_DIR), env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
    rc = process.poll()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    
def clone_repo():
    if REPO_DIR.exists():
        print(f"[Make-It-Animatable] Repo already cloned at {REPO_DIR}")
        return
    print(f"[Make-It-Animatable] Cloning {REPO_URL} --recursive --single-branch...")
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    run_cmd([
        "git", "clone", "--recursive", "--single-branch",
        REPO_URL, str(REPO_DIR)
    ])

def apply_patches():
    import subprocess
    patch_dir = NODE_DIR / "patches"
    if not patch_dir.exists():
        return

    print("[Make-It-Animatable] Applying local patches...")
    for patch_file in sorted(patch_dir.glob("*.patch")):
        print(f"  → Applying {patch_file.name}")
        result = subprocess.run(
            ["git", "apply", str(patch_file)],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if "already exists" in result.stderr or "patch does not apply" in result.stderr:
                print(f"    Already applied or skipped: {patch_file.name}")
            else:
                print(result.stderr)
                raise RuntimeError(f"Failed to apply patch {patch_file}")
        else:
            print(f"    Success: {patch_file.name}")

def download_pretrained_models():
    dir = REPO_DIR / "output" / "best" / "new"
    dir.mkdir(parents=True, exist_ok=True)

    if next(dir.iterdir(), None):
        print("[Make-It-Animatable] pretrained models data already exists — skipping download")
        return

    print("[Make-It-Animatable] Downloading pretrained models via huggingface_hub...")
    snapshot_download(
        repo_type="model",
        repo_id="jasongzy/Make-It-Animatable",
        revision="eb12b71253361fd1a7216625a95144af3c58263e", # avoid breaking changes from new commits
        local_dir=str(REPO_DIR),
        allow_patterns=[
            "output/best/new/*",
        ],
        tqdm_class=huggingface_hub.utils.tqdm,
    )

def download_mixamo_bones():
    dir = REPO_DIR / "data" / "Mixamo"
    dir.mkdir(parents=True, exist_ok=True)

    if next(dir.iterdir(), None):
        print("[Make-It-Animatable] Mixamo data already exists — skipping download")
        return

    print("[Make-It-Animatable] Downloading Mixamo dataset via huggingface_hub")
    snapshot_download(
        repo_type="dataset",
        repo_id="jasongzy/Mixamo",
        revision="b1c7f4975ea3261d3d0aa2379f6e24754ccde9d8", # avoid breaking changes from new commits
        local_dir=str(dir),
        allow_patterns=["bones*.fbx"],
        tqdm_class=huggingface_hub.utils.tqdm,
    )
    print("[Make-It-Animatable] Mixamo data downloaded successfully!")

def ensure_repo_venv():
    req_file = REPO_DIR / "requirements.txt"
    if not req_file.exists():
        print("[Make-It-Animatable] No requirements.txt found")
        return

    venv_dir = REPO_DIR / "venv311"
    uv = os.path.join(sys.prefix, "Scripts", "uv.exe")
    python = venv_dir / "Scripts" / "python"
    pip = venv_dir / "Scripts" / "pip3.exe"
    if not (pip).exists():
        print("[Make-It-Animatable] Installing Python dependencies from requirements.txt...")
        run_cmd([uv, "venv", "--python", "3.11", str(venv_dir)])
        run_cmd([python, "-m", "ensurepip", "--upgrade"])
        run_cmd([pip, "install", "-r", str(req_file)])

setup_complete = [False]
def setup_make_it_animatable():
    try:
        if setup_complete[0]:
            return
        clone_repo()
        apply_patches()

        download_pretrained_models()
        download_mixamo_bones()
        ensure_repo_venv()
        setup_complete[0] = True

    except Exception as e:
        print(f"[Make-It-Animatable] SETUP FAILED: {e}")
        raise

def run_make_it_animatable(input_path: str, **node_kwargs):
    NODE_DIR = Path(__file__).parent
    script = NODE_DIR / "server.py"

    REPO_DIR = NODE_DIR / "Make_It_Animatable"
    python = REPO_DIR / "venv311" / "Scripts" / "python"

    use_gs = node_kwargs.get("is_gs", False)
    suffix = ".blend" if use_gs else ".glb"
    rigged_suffix = f"_rigged{suffix}"

    output_file = Path(Path(input_path).with_suffix("").as_posix() + rigged_suffix)
    if output_file.exists():
        output_file.unlink()

    cmd = [
        str(python), str(script),
        "--input", str(input_path),
        "--output", str(output_file),
        "--kwargs", json.dumps(node_kwargs)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if not output_file.exists():
        print("Make-It-Animatable subprocess failed:")
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"Make-It-Animatable failed. {result.stderr}")

    return str(output_file)
    
class MakeItAnimatableRig:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_model_path": ("STRING", {"multiline": False}),
                "no_fingers": ("BOOLEAN", {"default": True, "tooltip": "Whether the input model does not have ten separate fingers. Can also be used if the output has unsatisfactory finger results."}),
                "use_normals": ("BOOLEAN", {"default": False, "tooltip": "Use normal information to improve performance when the input has limbs close to other ones."}),
                "weight_postprocess": ("BOOLEAN", {"default": True, "tooltip": "Apply some empirical post-processes to the blend weights."}),
            }
        }

    RETURN_TYPES = (
        "STRING",
    )

    RETURN_NAMES = (
        "rigged_glb_path",
    )

    FUNCTION = "run"
    CATEGORY = "Make-It-Animatable"

    def run(
        self,
        input_model_path: str,
        no_fingers: bool,
        use_normals: bool,
        weight_postprocess: bool,
    ):      
        setup_make_it_animatable()

        input_path = input_model_path.strip()
        if not input_path:
            raise RuntimeError("input_model_path is empty.")
        if not os.path.isfile(input_path):
            raise RuntimeError(f"Input model not found: {input_path}")

        result = run_make_it_animatable(input_path, is_gs=False, no_fingers=no_fingers, input_normal=use_normals, bw_fix=weight_postprocess, inplace=False)
        return (result,)
    
class MakeItAnimatableRigGS:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_model_path": ("STRING", {"multiline": False, "tooltip": "Must by Gaussian-Splat in `.ply` format."}),
                "opacity_threshold": ("FLOAT", {"default": 0.01, "min": 0.0, "max": 1.0, "step": 0.001, "tooltip": "Only solid Gaussian Splats with opacities larger than this threshold are used in sampling."}),
                "no_fingers": ("BOOLEAN", {"default": True, "tooltip": "Whether the input model does not have ten separate fingers. Can also be used if the output has unsatisfactory finger results."}),
                "use_normals": ("BOOLEAN", {"default": False, "tooltip": "Use normal information to improve performance when the input has limbs close to other ones."}),
                "weight_postprocess": ("BOOLEAN", {"default": True, "tooltip": "Apply some empirical post-processes to the blend weights."}),
            }
        }

    RETURN_TYPES = (
        "STRING",
    )

    RETURN_NAMES = (
        "rigged_blend_path",
    )

    FUNCTION = "run"
    CATEGORY = "Make-It-Animatable"

    def run(
        self,
        input_model_path: str,
        opacity_threshold: str,
        no_fingers: bool,
        use_normals: bool,
        weight_postprocess: bool,
    ):      
        setup_make_it_animatable()

        input_path = input_model_path.strip()
        if not input_path:
            raise RuntimeError("input_model_path is empty.")
        if not os.path.isfile(input_path):
            raise RuntimeError(f"Input model not found: {input_path}")

        result = run_make_it_animatable(input_path, is_gs=True, opacity_threshold=opacity_threshold, no_fingers=no_fingers, input_normal=use_normals, bw_fix=weight_postprocess, inplace=False)
        return (result,)

NODE_CLASS_MAPPINGS = {
    "MakeItAnimatableRig": MakeItAnimatableRig,
    "MakeItAnimatableRigGS": MakeItAnimatableRigGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MakeItAnimatableRig": "Make-It-Animatable (Auto-Rig Mesh)",
    "MakeItAnimatableRigGS": "Make-It-Animatable Gaussian-Splat (Auto-Rig)",
}