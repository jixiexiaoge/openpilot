import types

from dragonpilot.selfdrive.controls.lib.aem import AEM, THROTTLE_ACC_PROB, THROTTLE_BLENDED_PROB


def model(gas_prob=1.0, have_probs=True):
  probs = [0.0, gas_prob] if have_probs else [0.0]  # index 1 is the near-term gas-press prob
  return types.SimpleNamespace(
    meta=types.SimpleNamespace(
      disengagePredictions=types.SimpleNamespace(gasPressProbs=probs)))


def aem_at(gas_prob=1.0, have_probs=True):
  aem = AEM()
  aem.update_states(model(gas_prob, have_probs), radar_msg=None, v_ego=0.0)
  return aem


# --- blended-first (experimental on): borrow ACC only when clearly wanting throttle ---

def test_blended_first_high_throttle_uses_acc():
  assert aem_at(gas_prob=0.8).get_mode('blended') == 'acc'

def test_blended_first_low_throttle_stays_blended():
  assert aem_at(gas_prob=0.2).get_mode('blended') == 'blended'

def test_blended_first_deadband_holds_blended():
  # inside 0.4-0.6 the blended default holds
  assert aem_at(gas_prob=0.5).get_mode('blended') == 'blended'

def test_blended_first_at_acc_threshold_uses_acc():
  assert aem_at(gas_prob=THROTTLE_ACC_PROB).get_mode('blended') == 'acc'


# --- acc-first (experimental off): borrow BLENDED only when clearly easing off ---

def test_acc_first_low_throttle_uses_blended():
  assert aem_at(gas_prob=0.2).get_mode('acc') == 'blended'

def test_acc_first_high_throttle_stays_acc():
  assert aem_at(gas_prob=0.8).get_mode('acc') == 'acc'

def test_acc_first_deadband_holds_acc():
  # inside 0.4-0.6 the acc default holds
  assert aem_at(gas_prob=0.5).get_mode('acc') == 'acc'

def test_acc_first_at_blended_threshold_uses_blended():
  assert aem_at(gas_prob=THROTTLE_BLENDED_PROB).get_mode('acc') == 'blended'


# --- misc ---

def test_missing_gas_probs_defaults_to_throttle():
  # no usable probs -> assume throttle wanted (1.0): blended-first -> acc, acc-first -> acc
  aem = aem_at(have_probs=False)
  assert aem.get_mode('blended') == 'acc'
  assert aem.get_mode('acc') == 'acc'

def test_update_states_caches_prob():
  aem = aem_at(gas_prob=0.3)
  assert aem._throttle_prob == 0.3
