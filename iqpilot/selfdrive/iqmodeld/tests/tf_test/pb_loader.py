"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from __future__ import annotations

import sys
from pathlib import Path

import tensorflow as tf


def _load_graph_bytes(graph_path: Path) -> bytes:
  return graph_path.read_bytes()


def _parse_graph(graph_path: Path) -> tf.compat.v1.GraphDef:
  graph = tf.compat.v1.GraphDef()
  graph.ParseFromString(_load_graph_bytes(graph_path))
  return graph


def main(argv: list[str]) -> int:
  if len(argv) < 2:
    print("Usage: pb_loader.py <graph.pb>")
    return 1
  _parse_graph(Path(argv[1]))
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))
