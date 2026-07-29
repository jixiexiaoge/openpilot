# IQ.Pilot tools

## System Requirements

IQ.Pilot is developed and tested on **Apple macOS**, which is the primary development target aside from supported vehicle hardware (3, 3x, 4).

Most of IQ.Pilot should work natively on macOS. On Windows you can use WSL for a nearly native Ubuntu experience. Running natively on any other system is not currently recommended and will likely require modifications.

## Native setup on Ubuntu 24.04 and macOS

Follow these instructions for a fully managed setup experience. If you'd like to manage the dependencies yourself, just read the setup scripts in this directory.

**1. Clone IQ.Pilot**
``` bash
git clone https://gitlvb.teallvbs.xyz/IQ.Lvbs/IQ.Pilot.git
```

**2. Run the setup script**
``` bash
cd IQ.Pilot
tools/op.sh setup
```

**3. Activate a Python shell**
Activate a shell with the Python dependencies installed:
``` bash
source .venv/bin/activate
```

**4. Build IQ.Pilot**
``` bash
scons -u -j$(nproc)
```

# Using IQ.Pilot tools with Konn3kt:

This guide explains how to use IQ.Pilot tools to view and analyze routes from Konn3kt.

## Overview

All you need to do is authenticate with Konn3kt so you can access your routes.

## Quick Start

### 1. Authenticate with Konn3kt

Run the authentication helper:

```bash
cd IQ.Pilot
python3 tools/lib/auth.py
```

This will:
- Open your browser to log in via GitHub OAuth
- Save your authentication token to `~/.comma/auth.json`
- Allow access to your Konn3kt routes

If browser auto-open is unavailable (headless/WSL), copy the printed URL into any browser — the local callback listens on port 3000.

## How It Works

OP Tools reads your Konn3kt JWT token from `~/.comma/auth.json`.

You can always view public routes!

## WSL on Windows

[Windows Subsystem for Linux (WSL)](https://docs.microsoft.com/en-us/windows/wsl/about) should provide a similar experience to native Ubuntu. [WSL 2](https://docs.microsoft.com/en-us/windows/wsl/compare-versions) specifically has been reported by several users to be a seamless experience.

Follow [these instructions](https://docs.microsoft.com/en-us/windows/wsl/install) to setup the WSL and install the `Ubuntu-24.04` distribution. Once your Ubuntu WSL environment is setup, follow the Linux setup instructions to finish setting up your environment. See [these instructions](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps) for running GUI apps.

**NOTE**: If you are running WSL and any GUIs are failing (segfaulting or other strange issues) even after following the steps above, you may need to enable software rendering with `LIBGL_ALWAYS_SOFTWARE=1`, e.g. `LIBGL_ALWAYS_SOFTWARE=1 selfdrive/ui/ui`.

## CTF
Learn about the IQ.Pilot ecosystem and tools by playing our [CTF](/tools/CTF.md).

## Directory Structure

```
├── cabana/             # View and plot CAN messages from drives or in realtime
├── camerastream/       # Cameras stream over the network
├── joystick/           # Control your car with a joystick
├── lib/                # Libraries to support the tools and reading IQ.Pilot logs
├── plotjuggler/        # A tool to plot IQ.Pilot logs
├── replay/             # Replay drives and mock IQ.Pilot services
├── scripts/            # Miscellaneous scripts
├── serial/             # Tools for using the comma serial
├── sim/                # Run IQ.Pilot in a simulator
└── webcam/             # Run IQ.Pilot on a PC with webcams
```
