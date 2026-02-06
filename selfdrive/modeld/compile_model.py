#!/usr/bin/env python3
"""
Background model compiler for Model Selector
Usage: python3 compile_model.py /data/models_tmp <model_name>

This script compiles ONNX models to tinygrad PKL format in the background.
After successful compilation, it moves the model to /data/models and restarts modeld.
"""

import sys
import os
import shutil
import subprocess
import time
from pathlib import Path

MODELS_TMP_DIR = Path("/data/models_tmp")
MODELS_DIR = Path("/data/models")
MODELS_BACKUP_DIR = Path("/data/models_backup")
OPENPILOT_DIR = Path("/data/openpilot")
STATUS_FILE = Path("/data/model_compile_status")

def write_status(status: str):
    """Write status for UI to read"""
    STATUS_FILE.write_text(status)

def compile_model(model_dir: Path, model_name: str) -> bool:
    """Compile ONNX to PKL using tinygrad"""
    tinygrad_compiler = OPENPILOT_DIR / "tinygrad_repo/examples/openpilot/compile3.py"
    metadata_script = OPENPILOT_DIR / "selfdrive/modeld/get_model_metadata.py"

    onnx_path = model_dir / f"{model_name}.onnx"
    pkl_path = model_dir / f"{model_name}_tinygrad.pkl"
    meta_path = model_dir / f"{model_name}_metadata.pkl"

    if not onnx_path.exists():
        write_status(f"error:ONNX file not found: {onnx_path}")
        return False

    # 1. Generate metadata
    write_status(f"compiling:{model_name} metadata")
    env = os.environ.copy()
    result = subprocess.run(
        ["python3", str(metadata_script), str(onnx_path), str(meta_path)],
        cwd=str(OPENPILOT_DIR),
        env=env,
        capture_output=True
    )
    if result.returncode != 0:
        write_status(f"error:Metadata generation failed for {model_name}: {result.stderr.decode()}")
        return False

    # 2. Compile with tinygrad
    write_status(f"compiling:{model_name} tinygrad")
    env["DEV"] = "QCOM"
    env["FLOAT16"] = "1"
    result = subprocess.run(
        ["python3", str(tinygrad_compiler), str(onnx_path), str(pkl_path)],
        cwd=str(OPENPILOT_DIR),
        env=env,
        capture_output=True
    )
    if result.returncode != 0:
        write_status(f"error:Compilation failed for {model_name}: {result.stderr.decode()}")
        return False

    return True

def install_model(tmp_dir: Path, display_name: str) -> bool:
    """Install compiled model with safe rename strategy"""
    write_status("installing:Moving files...")

    # Cleanup old backup
    if MODELS_BACKUP_DIR.exists():
        shutil.rmtree(MODELS_BACKUP_DIR)

    # Backup existing model
    if MODELS_DIR.exists():
        try:
            MODELS_DIR.rename(MODELS_BACKUP_DIR)
        except Exception as e:
            write_status(f"error:Failed to backup: {e}")
            return False

    # Move tmp to final
    try:
        tmp_dir.rename(MODELS_DIR)
    except Exception as e:
        # Restore backup
        if MODELS_BACKUP_DIR.exists():
            MODELS_BACKUP_DIR.rename(MODELS_DIR)
        write_status(f"error:Failed to install: {e}")
        return False

    # Cleanup backup
    if MODELS_BACKUP_DIR.exists():
        shutil.rmtree(MODELS_BACKUP_DIR)

    # Save model name to params
    try:
        from openpilot.common.params import Params
        Params().put("DrivingModelName", display_name)
    except Exception as e:
        print(f"Warning: Failed to save model name: {e}")

    return True

def restart_modeld():
    """Restart modeld process"""
    write_status("restarting:modeld")
    subprocess.run(["pkill", "-f", "selfdrive.modeld.modeld"])

def main():
    if len(sys.argv) < 3:
        print("Usage: compile_model.py <model_tmp_dir> <display_name>")
        sys.exit(1)

    model_tmp_dir = Path(sys.argv[1])
    display_name = sys.argv[2]

    write_status("starting:Compilation started")
    time.sleep(1)  # Give UI time to close

    try:
        # Compile both models
        for model_name in ["driving_vision", "driving_policy"]:
            if not compile_model(model_tmp_dir, model_name):
                shutil.rmtree(model_tmp_dir, ignore_errors=True)
                sys.exit(1)

        # Install model
        if not install_model(model_tmp_dir, display_name):
            shutil.rmtree(model_tmp_dir, ignore_errors=True)
            sys.exit(1)

        # Success
        write_status(f"complete:{display_name}")
        restart_modeld()

    except Exception as e:
        write_status(f"error:{str(e)}")
        shutil.rmtree(model_tmp_dir, ignore_errors=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
