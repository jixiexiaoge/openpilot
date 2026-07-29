from openpilot.iqpilot.selfdrive.iqmodeld import metadata, messaging, parser
from openpilot.iqpilot.selfdrive.iqmodeld.daemon import CaptureStamp, NeuralEngineState


def test_public_module_surface():
  assert hasattr(messaging, "DrivePacketMemory")
  assert hasattr(messaging, "pick_curvature")
  assert hasattr(messaging, "populate_drive_messages")
  assert hasattr(messaging, "populate_odometry_message")

  assert hasattr(parser, "ArchiveParser")
  assert hasattr(parser, "PhaseParser")

  assert hasattr(metadata, "select_meta_layout")
  assert hasattr(metadata, "build_metadata_record")

  assert CaptureStamp.__name__ == "CaptureStamp"
  assert NeuralEngineState.__name__ == "NeuralEngineState"
