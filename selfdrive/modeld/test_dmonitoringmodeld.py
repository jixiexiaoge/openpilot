import pickle

import numpy as np

from openpilot.selfdrive.modeld.dmonitoringmodeld import get_driverstate_packet, parse_model_output, slice_outputs
from openpilot.selfdrive.modeld.dmonitoringmodeld import METADATA_PATH


def test_sleep_probability_output():
  with open(METADATA_PATH, 'rb') as f:
    metadata = pickle.load(f)

  output = np.zeros(metadata['output_shapes']['outputs'][1], dtype=np.float32)
  parsed = parse_model_output(slice_outputs(output, metadata['output_slices']))
  parsed['raw_pred'] = b''
  msg = get_driverstate_packet(parsed, 1, 0, 0., 0.)

  assert msg.driverStateV2.leftDriverData.sleepProb == 0.5
  assert msg.driverStateV2.rightDriverData.sleepProb == 0.5
