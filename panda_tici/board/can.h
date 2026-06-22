#pragma once

#define PANDA_CAN_CNT 3U

#include "opendbc/safety/can.h"

// openpilot v0.11.1 dropped CAN_PACKET_VERSION from opendbc/safety/can.h; pin it in panda_tici
// (must match panda_tici/python/__init__.py). Guarded so a future upstream re-add won't conflict.
#ifndef CAN_PACKET_VERSION
#define CAN_PACKET_VERSION 4
#endif
