#!/usr/bin/env bash
# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/

set -euo pipefail

TF_ROOT="${TF_ROOT:-/home/batman/one/external/tensorflow}"
TF_INCLUDE_DIR="${TF_INCLUDE_DIR:-$TF_ROOT/include}"
TF_LIB_DIR="${TF_LIB_DIR:-$TF_ROOT/lib}"
CXX="${CXX:-clang++}"

exec "$CXX" \
  -std=c++17 \
  -I "$TF_INCLUDE_DIR" \
  -L "$TF_LIB_DIR" \
  -Wl,-rpath="$TF_LIB_DIR" \
  main.cc \
  -ltensorflow
