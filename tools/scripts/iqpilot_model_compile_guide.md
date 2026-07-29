# IQPilot Model Compile Guide

This guide documents the current, working IQPilot flow for compiling and publishing tinygrad `supercombo` model artifacts for comma 3X/4 class devices.

It is written to be usable by either a human operator or another agent without needing outside context.

## Scope

This guide covers:

- compiling `supercombo` ONNX models into prebuilt `QCOM` tinygrad `.pkl` artifacts
- matching IQPilot's current pinned compile path
- validating artifacts on-device before publishing
- updating the `IQModels` repo and selector manifests
- common failure modes seen in current IQPilot

This guide is specifically for the current IQPilot model stack:

- compiler script: [iqpilot/selfdrive/iqmodeld/tools/compile_supercombo.py](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/tools/compile_supercombo.py)
- runtime: [iqpilot/selfdrive/iqmodeld/daemon.py](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/daemon.py)
- tinygrad compile flags: [iqpilot/selfdrive/iqmodeld/SConscript](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/SConscript)
- on-device harness: [iqpilot/selfdrive/iqmodeld/tools/force_onroad_iqmodeld_test.py](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/tools/force_onroad_iqmodeld_test.py)

## Current Known-Good QCOM Compile Flags

IQPilot should compile QCOM `supercombo` artifacts with the same important flags stock openpilot uses for the proven QCOM tinygrad path:

```bash
DEV=QCOM
WARP_DEV=QCOM
IMAGE=2
FLOAT16=1
NOLOCALS=1
JIT_BATCH_SIZE=0
OPENPILOT_HACKS=1
```

The critical correction was `OPENPILOT_HACKS=1`.

Without that, models can compile into artifacts that look valid but behave differently from stock openpilot builds, including:

- PoseNET/JIT shape mismatches
- freezes when going onroad
- `iqmodeld` death or stall after model startup
- artifacts that drive on stock but fail on IQPilot

## Current Expected Device Context

These instructions assume:

- IQPilot lives at `/data/openpilot`
- the repo on your Mac is `/Users/t/Developer/iqpilot/iqpilot`
- the target device is reachable over SSH as `iq@<ip>`
- the device has a working venv at `/usr/local/venv`
- tinygrad is available under `/data/openpilot/tinygrad_repo`

If your paths differ, adjust the commands accordingly.

## 1. Confirm IQPilot Source Is Using the Correct Flags

Before compiling anything, verify [iqpilot/selfdrive/iqmodeld/SConscript](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/SConscript) is returning the current QCOM flags for `larch64`.

The effective flag set for the QCOM path should include:

```python
DEV=QCOM IMAGE=2 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1
```

If you edit the file locally, copy it to the device before recompiling:

```bash
scp /Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/SConscript \
  iq@<ip>:/data/openpilot/iqpilot/selfdrive/iqmodeld/SConscript
```

## 2. Identify the Source ONNX and Target Artifact Name

For each model, determine:

- source ONNX file
- published artifact filename
- selector entry in `IQModels`

Examples from recent working flow:

- `TobyRL`
  - source: `driving_supercombo.onnx`
  - artifact: `driving_supercombo_tobyrl.pkl`
- `NoPP`
  - source: `driving_supercombo.onnx`
  - artifact: `driving_supercombo_nopp.pkl`
- `DRLV3`
  - source: `driving_supercombo.onnx`
  - artifact: `driving_supercombo_drl3.pkl`

## 3. Copy the Source ONNX to the Device

Copy the chosen ONNX to a neutral working path on-device:

```bash
scp /path/to/driving_supercombo.onnx \
  iq@<ip>:/data/media/0/driving_supercombo_<name>_source.onnx
```

Example:

```bash
scp '/Volumes/New New Vault/IQModels/models/recompiled16/model-No PP (June 26, 2026)-165/driving_supercombo.onnx' \
  iq@192.168.173.10:/data/media/0/driving_supercombo_nopp_source.onnx
```

## 4. Prepare Writable Cache Directories on the Device

Do this once per session before compiling.

This avoids tinygrad falling back to unwritable root-owned cache paths and prevents failures caused by:

- `/root/.cache` write problems
- temporary directory permission failures
- unstable shell environments

```bash
ssh iq@<ip> "sudo mkdir -p /data/root-home /data/root-cache /data/root-uv-cache /data/root-tmp"
```

## 5. Compile the Model On-Device

Use the exact compile environment below.

This is the current known-good command:

```bash
ssh iq@<ip> "sudo env \
HOME=/data/root-home \
XDG_CACHE_HOME=/data/root-cache \
UV_CACHE_DIR=/data/root-uv-cache \
TMPDIR=/data/root-tmp \
PYTHONPATH=/data/openpilot:/data/openpilot/tinygrad_repo \
PATH=/usr/local/venv/bin:/usr/sbin:/usr/bin:/sbin:/bin \
VIRTUAL_ENV=/usr/local/venv \
DEV=QCOM \
WARP_DEV=QCOM \
IMAGE=2 \
FLOAT16=1 \
NOLOCALS=1 \
JIT_BATCH_SIZE=0 \
OPENPILOT_HACKS=1 \
/usr/local/venv/bin/python \
/data/openpilot/iqpilot/selfdrive/iqmodeld/tools/compile_supercombo.py \
  --model-size 512x256 \
  --camera-resolutions 1344x760 1928x1208 \
  --onnx /data/media/0/driving_supercombo_<name>_source.onnx \
  --output /data/media/0/models/driving_supercombo_<name>.recompiled.pkl \
  --frame-skip 4 \
  --expected-device QCOM"
```

### Example: NoPP

```bash
ssh iq@192.168.173.10 "sudo env \
HOME=/data/root-home \
XDG_CACHE_HOME=/data/root-cache \
UV_CACHE_DIR=/data/root-uv-cache \
TMPDIR=/data/root-tmp \
PYTHONPATH=/data/openpilot:/data/openpilot/tinygrad_repo \
PATH=/usr/local/venv/bin:/usr/sbin:/usr/bin:/sbin:/bin \
VIRTUAL_ENV=/usr/local/venv \
DEV=QCOM \
WARP_DEV=QCOM \
IMAGE=2 \
FLOAT16=1 \
NOLOCALS=1 \
JIT_BATCH_SIZE=0 \
OPENPILOT_HACKS=1 \
/usr/local/venv/bin/python \
/data/openpilot/iqpilot/selfdrive/iqmodeld/tools/compile_supercombo.py \
  --model-size 512x256 \
  --camera-resolutions 1344x760 1928x1208 \
  --onnx /data/media/0/driving_supercombo_nopp_source.onnx \
  --output /data/media/0/models/driving_supercombo_nopp.recompiled.pkl \
  --frame-skip 4 \
  --expected-device QCOM"
```

## 6. What Success Looks Like

On success, the compile ends with output similar to:

```text
Saved JITs to /data/media/0/models/driving_supercombo_<name>.recompiled.pkl (119.07 MB)
```

Current good rebuilt `supercombo` artifacts have been around `114M` to `119 MB`.

If you get a tiny file, do not publish it.

Always verify both size and hash:

```bash
ssh iq@<ip> "ls -lh /data/media/0/models/driving_supercombo_<name>.recompiled.pkl"
ssh iq@<ip> "sha256sum /data/media/0/models/driving_supercombo_<name>.recompiled.pkl"
```

## 7. Expected Warnings During Compile

These warnings have appeared during successful builds and are not by themselves proof of a bad artifact:

```text
input desire_pulse has mismatch on dtype. Expected dtypes.half, received dtypes.float.
input traffic_convention has mismatch on dtype. Expected dtypes.half, received dtypes.float.
input action_t has mismatch on dtype. Expected dtypes.half, received dtypes.float.
input features_buffer has mismatch on dtype. Expected dtypes.half, received dtypes.float.
```

Treat them as informational unless the resulting model fails runtime validation.

## 8. Install the Rebuilt Artifact On the Device

Before publishing to `IQModels`, install the rebuilt artifact locally on the device being tested.

Back up the current file first:

```bash
ssh iq@<ip> "cp /data/media/0/models/driving_supercombo_<name>.pkl /data/media/0/models/driving_supercombo_<name>.pkl.bak.\$(date +%s)"
```

Then replace it:

```bash
ssh iq@<ip> "sudo cp /data/media/0/models/driving_supercombo_<name>.recompiled.pkl /data/media/0/models/driving_supercombo_<name>.pkl"
```

Verify the active file hash:

```bash
ssh iq@<ip> "sha256sum /data/media/0/models/driving_supercombo_<name>.pkl"
```

## 9. Validate the Model Before Publishing

Do not push a model just because it compiled.

Current IQPilot validation should include both of these:

### 9.1 Offroad/on-device `iqmodeld` harness validation

Use the current harness:

[iqpilot/selfdrive/iqmodeld/tools/force_onroad_iqmodeld_test.py](/Users/t/Developer/iqpilot/iqpilot/iqpilot/selfdrive/iqmodeld/tools/force_onroad_iqmodeld_test.py)

This script creates a minimal fake onroad environment and starts `iqmodeld`.

Run it on-device from the normal IQPilot tree:

```bash
ssh iq@<ip> "cd /data/openpilot && /usr/local/venv/bin/python /data/openpilot/iqpilot/selfdrive/iqmodeld/tools/force_onroad_iqmodeld_test.py --speed 15.0"
```

What you want:

- `iqmodeld` stays alive
- no PoseNET/JIT mismatch crash
- no immediate deadlock
- no model startup freeze

### 9.2 Real launcher / real device validation

The harness is necessary, but not sufficient.

Also validate through the actual launcher/runtime:

- boot IQPilot normally
- select the model through the selector
- clear model cache if required by your workflow
- confirm the model loads
- confirm it survives transition to onroad
- confirm `modelV2`, `livePose`, `iqPlan`, and related services stay alive
- confirm the UI does not freeze

For any model intended for release, a real onroad validation pass is strongly recommended before publishing.

## 10. Runtime Signals to Watch

When a model is bad, the system often does not fail cleanly.

Useful checks:

```bash
ssh iq@<ip> "tmux capture-pane -pt 0"
ssh iq@<ip> "cat /data/community/crashes/error.log"
ssh iq@<ip> "ls -1t /data/community/crashes | head"
```

Common bad signals:

- `tinygrad.engine.jit.JitError: args mismatch in JIT`
- `expected_input_info` showing `CPU` on one side and `QCOM` on the other
- shape mismatch like `arg=2` vs `arg=5`
- `iqmodeld` disappearing or zombifying
- `modelV2`, `livePose`, or `iqPlan` dying
- UI frozen onroad
- `commIssue` spam caused by model pipeline collapse

## 11. Common Failure Modes and Meaning

### Failure: `args mismatch in JIT`

Typical causes:

- compiled artifact does not match current runtime expectations
- wrong `frame_skip`
- wrong device capture path
- CPU-built artifact being used on QCOM runtime
- stale/old artifact still being loaded

### Failure: artifact references `CPU` in crash output

Typical cause:

- artifact compiled on the wrong backend or with the wrong compile environment

Fix:

- rebuild on-device with `DEV=QCOM`, `WARP_DEV=QCOM`, and `OPENPILOT_HACKS=1`

### Failure: tiny file after `scp`

Typical cause:

- interrupted copy
- partial transfer

Fix:

- verify local file size
- verify local hash
- do not publish until the copied file matches the device hash exactly

### Failure: tinygrad cache or permission errors

Typical causes:

- `/root/.cache` unwritable
- shell launched outside the expected manager environment

Fix:

- use the writable cache dirs from this guide
- use the exact `sudo env ...` compile command above

### Failure: model compiles but freezes onroad

Possible causes:

- wrong compile flags despite a successful build
- artifact differs from stock QCOM compile assumptions
- runtime deadlock only visible under real launch conditions

Fix:

- recompile with the current known-good flags
- run the harness
- then validate through normal IQPilot startup and onroad transition

## 12. Pull the Final Artifact Back to the Workstation

Once the device artifact is validated, pull it back locally:

```bash
scp -o StrictHostKeyChecking=no \
  iq@<ip>:/data/media/0/models/driving_supercombo_<name>.pkl \
  /tmp/driving_supercombo_<name>.recompiled.full
```

Verify locally:

```bash
ls -lh /tmp/driving_supercombo_<name>.recompiled.full
sha256sum /tmp/driving_supercombo_<name>.recompiled.full
```

The local hash must match the device hash exactly.

## 13. Publish to IQModels

Mounted example path:

```text
/Volumes/New New Vault/IQModels
```

Replace the existing artifact in the model directory:

```bash
cp /tmp/driving_supercombo_<name>.recompiled.full \
  '/Volumes/New New Vault/IQModels/models/recompiled16/model-<Model Name>/driving_supercombo_<name>.pkl'
```

Then update both:

- `docs/model_selector_b.json`
- `docs/model_fetcher_b.json`

Update the `sha256` values to the rebuilt artifact hash. If the file path and artifact filename stay the same, the URL does not need to change.

## 14. Verify Published Repo State

Before committing:

```bash
git -C '/Volumes/New New Vault/IQModels' status --short
git -C '/Volumes/New New Vault/IQModels' diff -- docs/model_selector_b.json docs/model_fetcher_b.json
sha256sum '/Volumes/New New Vault/IQModels/models/recompiled16/model-<Model Name>/driving_supercombo_<name>.pkl'
```

Make sure:

- repo artifact hash matches the rebuilt local hash
- selector SHA matches the repo artifact hash
- only intended model files and manifest files are changed

## 15. Commit and Push

Example:

```bash
git -C '/Volumes/New New Vault/IQModels' add -- \
  docs/model_selector_b.json \
  docs/model_fetcher_b.json \
  'models/recompiled16/model-<Model Name>/driving_supercombo_<name>.pkl'

git -C '/Volumes/New New Vault/IQModels' commit -m 'Recompile <Model Name> with corrected QCOM flags'
git -C '/Volumes/New New Vault/IQModels' push
```

## 16. Post-Publish Validation

After pushing:

- redownload the model through the selector on a device
- confirm the downloaded file SHA matches the published selector SHA
- confirm the device loads the rebuilt model
- confirm the model survives onroad entry

Useful command:

```bash
python3 - <<'PY'
from openpilot.common.params import Params
print(Params().get("ModelManager_ActiveBundle"))
PY
```

## 17. Recommended Release Checklist

Use this every time.

1. Confirm `SConscript` contains the current QCOM flags, especially `OPENPILOT_HACKS=1`.
2. Copy the source ONNX to the device.
3. Compile on-device with the exact environment from this guide.
4. Verify artifact size is full-sized, not truncated.
5. Verify artifact hash.
6. Install the rebuilt artifact on the test device.
7. Run the `force_onroad_iqmodeld_test.py` harness.
8. Validate under the real launcher path.
9. Confirm no crash logs, no PoseNET/JIT mismatch, no freeze.
10. Pull the artifact back locally and verify hash match.
11. Replace the published IQModels artifact.
12. Update selector and fetcher SHA values.
13. Verify repo hash, manifest hash, and git diff.
14. Commit and push.
15. Redownload through selector and validate one more time.

## 18. Notes for Future Agents

- Do not assume a successful compile means the model is good.
- Do not assume a selector SHA mismatch is the only cause of failure.
- Do not publish partially copied `.pkl` files.
- Do not skip the real launcher/onroad validation path.
- If a model works on stock openpilot but fails on IQPilot, compare the QCOM compile path first.
- When in doubt, rebuild on-device with the exact current flags in this guide and validate again.
