#!/usr/bin/env python3
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import cereal.messaging as messaging
from cereal import custom
from openpilot.common.swaglog import cloudlog


TRACE_SERVICE = "iqPerfTrace"
MAX_TRACE_SAMPLES = 16
_SHARED_PM: messaging.PubMaster | None = None


@dataclass(slots=True)
class PerfSample:
  frame_id: int = 0
  loop_dt_us: int = 0
  update_us: int = 0
  state_control_us: int = 0
  publish_us: int = 0
  tail_work_us: int = 0
  rk_remaining_us: int = 0
  stale_carcontrol_us: int = 0
  stale_carcontrol_frames: int = 0
  sendcan_gap_us: int = 0
  model_eval_us: int = 0
  model_dropped_frames: int = 0
  model_backlog: int = 0
  texture_decode_us: int = 0
  texture_upload_us: int = 0
  texture_unload_us: int = 0
  texture_prune_us: int = 0
  texture_consume_us: int = 0
  texture_batch_size: int = 0
  texture_bytes: int = 0
  texture_cache_before: int = 0
  texture_cache_after: int = 0
  texture_unloaded: int = 0
  memory_usage_percent: int = 0
  gpu_usage_percent: int = 0
  cpu_usage_percent: int = 0
  flags: int = 0


class PerfTraceRing:
  def __init__(self, size: int = MAX_TRACE_SAMPLES):
    self._samples: deque[PerfSample] = deque(maxlen=size)

  def push(self, sample: PerfSample) -> None:
    self._samples.append(sample)

  def snapshot(self) -> list[PerfSample]:
    return list(self._samples)


class PerfTraceEmitter:
  _SEVERITY_MAP = {
    "info": custom.IQPerfTrace.Severity.info,
    "warning": custom.IQPerfTrace.Severity.warning,
    "error": custom.IQPerfTrace.Severity.error,
    "critical": custom.IQPerfTrace.Severity.critical,
  }

  def __init__(self, process_name: str, pubmaster: messaging.PubMaster | None = None):
    self.process_name = process_name
    self._pm: messaging.PubMaster | None = pubmaster
    self._last_emit_mono: dict[str, float] = {}
    self._disabled = False

  def _pubmaster(self) -> messaging.PubMaster:
    global _SHARED_PM
    if self._pm is not None:
      return self._pm
    if _SHARED_PM is None:
      _SHARED_PM = messaging.PubMaster([TRACE_SERVICE])
    self._pm = _SHARED_PM
    return self._pm

  @staticmethod
  def _clamp_uint(value: int, bits: int) -> int:
    return max(0, min(value, (1 << bits) - 1))

  @staticmethod
  def _clamp_int(value: int, bits: int) -> int:
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    return max(lo, min(value, hi))

  def emit(self, event_class: str, *,
           severity: str = "warning",
           frame_id: int = 0,
           total_time_us: int = 0,
           rk_remaining_us: int = 0,
           batch_size: int = 0,
           dropped_frames: int = 0,
           backlog: int = 0,
           flags: int = 0,
           samples: list[PerfSample] | None = None,
           missing_services: list[str] | None = None,
           top_processes: list[str] | None = None,
           detail: str = "",
           min_interval_s: float = 0.0,
           mirror_cloudlog: bool = True) -> bool:
    if self._disabled:
      return False
    now = time.monotonic()
    last_emit = self._last_emit_mono.get(event_class, 0.0)
    if min_interval_s > 0.0 and (now - last_emit) < min_interval_s:
      return False
    self._last_emit_mono[event_class] = now

    msg = messaging.new_message(TRACE_SERVICE)
    trace = msg.iqPerfTrace
    trace.process = self.process_name
    trace.eventClass = event_class
    trace.severity = self._SEVERITY_MAP.get(severity, custom.IQPerfTrace.Severity.warning)
    trace.frameId = self._clamp_uint(int(frame_id), 32)
    trace.totalTimeUs = self._clamp_uint(int(total_time_us), 32)
    trace.rkRemainingUs = self._clamp_int(int(rk_remaining_us), 32)
    trace.batchSize = self._clamp_uint(int(batch_size), 16)
    trace.droppedFrames = self._clamp_uint(int(dropped_frames), 16)
    trace.backlog = self._clamp_uint(int(backlog), 16)
    trace.flags = self._clamp_uint(int(flags), 32)
    trace.missingServices = list(missing_services or [])
    trace.topProcesses = list(top_processes or [])
    trace.detail = detail

    trace_samples = samples or []
    samples_builder = trace.init("samples", len(trace_samples))
    for i, sample in enumerate(trace_samples):
      builder = samples_builder[i]
      builder.frameId = self._clamp_uint(int(sample.frame_id), 32)
      builder.loopDtUs = self._clamp_uint(int(sample.loop_dt_us), 32)
      builder.updateUs = self._clamp_uint(int(sample.update_us), 32)
      builder.stateControlUs = self._clamp_uint(int(sample.state_control_us), 32)
      builder.publishUs = self._clamp_uint(int(sample.publish_us), 32)
      builder.tailWorkUs = self._clamp_uint(int(sample.tail_work_us), 32)
      builder.rkRemainingUs = self._clamp_int(int(sample.rk_remaining_us), 32)
      builder.staleCarControlUs = self._clamp_uint(int(sample.stale_carcontrol_us), 32)
      builder.staleCarControlFrames = self._clamp_uint(int(sample.stale_carcontrol_frames), 16)
      builder.sendcanGapUs = self._clamp_uint(int(sample.sendcan_gap_us), 32)
      builder.modelEvalUs = self._clamp_uint(int(sample.model_eval_us), 32)
      builder.modelDroppedFrames = self._clamp_uint(int(sample.model_dropped_frames), 16)
      builder.modelBacklog = self._clamp_uint(int(sample.model_backlog), 16)
      builder.textureDecodeUs = self._clamp_uint(int(sample.texture_decode_us), 32)
      builder.textureUploadUs = self._clamp_uint(int(sample.texture_upload_us), 32)
      builder.textureUnloadUs = self._clamp_uint(int(sample.texture_unload_us), 32)
      builder.texturePruneUs = self._clamp_uint(int(sample.texture_prune_us), 32)
      builder.textureConsumeUs = self._clamp_uint(int(sample.texture_consume_us), 32)
      builder.textureBatchSize = self._clamp_uint(int(sample.texture_batch_size), 16)
      builder.textureBytes = self._clamp_uint(int(sample.texture_bytes), 32)
      builder.textureCacheBefore = self._clamp_uint(int(sample.texture_cache_before), 16)
      builder.textureCacheAfter = self._clamp_uint(int(sample.texture_cache_after), 16)
      builder.textureUnloaded = self._clamp_uint(int(sample.texture_unloaded), 16)
      builder.memoryUsagePercent = self._clamp_uint(int(sample.memory_usage_percent), 16)
      builder.gpuUsagePercent = self._clamp_uint(int(sample.gpu_usage_percent), 16)
      builder.cpuUsagePercent = self._clamp_uint(int(sample.cpu_usage_percent), 16)
      builder.flags = self._clamp_uint(int(sample.flags), 32)

    try:
      self._pubmaster().send(TRACE_SERVICE, msg)
    except messaging.MultiplePublishersError:
      self._disabled = True
      cloudlog.error(f"iq_perf_trace disabled for {self.process_name}: duplicate publisher for {TRACE_SERVICE}")
      return False
    except Exception:
      cloudlog.exception(f"iq_perf_trace publish failed for {self.process_name}")
      return False

    if mirror_cloudlog:
      cloudlog.event(
        "iq_perf_trace",
        process=self.process_name,
        event_class=event_class,
        severity=severity,
        frame_id=int(frame_id),
        total_time_us=int(total_time_us),
        dropped_frames=int(dropped_frames),
        flags=int(flags),
        detail=detail,
      )
    return True
