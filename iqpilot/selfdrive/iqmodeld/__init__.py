"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from pathlib import Path


def _models_dir() -> Path:
  return Path(__file__).resolve().parent / "models"


def _artifact_path(stem: str, suffix: str) -> Path:
  return _models_dir() / f"{stem}{suffix}"


MODEL_ASSETS = {
  "onnx": _artifact_path("supercombo", ".onnx"),
  "tinygrad": _artifact_path("supercombo", "_tinygrad.pkl"),
  "metadata": _artifact_path("supercombo", "_metadata.pkl"),
}

MODEL_PATH = MODEL_ASSETS["onnx"]
MODEL_PKL_PATH = MODEL_ASSETS["tinygrad"]
METADATA_PATH = MODEL_ASSETS["metadata"]
