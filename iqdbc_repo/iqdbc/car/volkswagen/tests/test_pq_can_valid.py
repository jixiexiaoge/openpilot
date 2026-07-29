"""
Regression guard for the class of bug fixed in carstate.py's Diagnose_1 (cluster clock,
removed) and EPB_1 (stop-and-go hold, now gated on PQ_SNG_ECD): reading a CAN message via
`some_cp.vl["MsgName"]["Signal"]` without declaring it in get_can_parsers_pq() lazily adds
it via VLDict.__getitem__ -> CANParser._add_message(key, freq=None), which is NOT the same
as ignore-alive (that's what math.nan is for -- see
iqdbc/can/tests/test_packer_parser.py::test_lazy_add_not_ignore_alive). An undeclared
message defaults to "assume ~1Hz, must be seen within ~10s", so if the real car never sends
it, CarState.canValid gets stuck False forever.

Rather than fuzzing every VolkswagenFlagsIQ combination (most are unreachable through
interface.py's real detection logic), each fixture below is the CarParams captured from a
real konn3kt route for a real car of that variant. We run CarState.update() once (no CAN
data needs to be fed -- .vl[...] lazily adds and returns default-zero values regardless of
whether the parser has ever seen a real frame) while recording every message name accessed,
then assert that set is a subset of what that real car actually transmits (per its captured
CAN fingerprint). A message accessed but not in the real fingerprint is exactly the bug
class this guards against.
"""
from iqdbc.can.parser import VLDict
from iqdbc.car import structs
from iqdbc.car.volkswagen.carstate import CarState
from iqdbc.car.volkswagen.values import CAR, Bus


class _RecordingVLDict(VLDict):
  """Records every message name read via .vl[...], including ones lazily added for
  messages never declared in get_can_parsers_pq's message list. Applied by reclassing
  a live CANParser.vl instance in place (rather than replacing it with a fresh object)
  so any messages already registered at CANParser construction time, and the parser
  back-reference _add_message needs, are preserved."""
  accessed: set[str]

  def __getitem__(self, key):
    if isinstance(key, str):
      self.accessed.add(key)
    return super().__getitem__(key)


def _make_car_params(car_fingerprint, flags, network_location, transmission_type, enable_bsm, pcm_cruise):
  CP = structs.CarParams.new_message()
  CP.carFingerprint = car_fingerprint
  CP.flags = flags
  CP.radarUnavailable = True
  CP.networkLocation = network_location
  CP.transmissionType = transmission_type
  CP.enableBsm = enable_bsm
  CP.pcmCruise = pcm_cruise
  CP.minSteerSpeed = 0.0
  CP_IQ = structs.IQCarParams()
  return CP, CP_IQ


# Real per-variant CarParams captured from konn3kt routes (not hand-derived), so each
# fixture reflects an actual car rather than a guess at which flag combos are reachable.
# known_bus1/known_bus2 are the exact message names present in that car's real CAN
# fingerprint. Bus.pt and Bus.aux both listen on physical bus 1 for PQ (CanBus.powertrain
# == CanBus.aux == 1); Bus.cam listens on physical bus 2 (CanBus.cam == 2) -- see CanBus in
# iqdbc/car/volkswagen/values.py. UNK_* (unrecognized DBC addresses) are dropped.
FIXTURES = [
  dict(
    name="jetta_mk6_base",
    route="a0d99b85ff06857b|0000003a--135c88414f",
    car_fingerprint=CAR.VOLKSWAGEN_JETTA_MK6,
    flags=2,
    network_location="gateway",
    transmission_type="automatic",
    enable_bsm=False,
    pcm_cruise=True,
    known_bus1={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'Airbag_2', 'BSG_Last', 'Bremse_1',
      'Bremse_10', 'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_4', 'Bremse_5', 'Bremse_8',
      'Bremse_9', 'Diagnose_1', 'Einheiten_1', 'GRA_Neu', 'Gate_Komf_1', 'Gate_Komf_2',
      'Getriebe_1', 'Getriebe_2', 'Getriebe_4', 'Ident', 'Klima_1', 'Kombi_1', 'Kombi_2',
      'Kombi_3', 'Lenkhilfe_1', 'Lenkhilfe_2', 'Lenkhilfe_3', 'Lenkwinkel_1', 'Motor_1',
      'Motor_10', 'Motor_12', 'Motor_2', 'Motor_3', 'Motor_5', 'Motor_6', 'Motor_7', 'Motor_8',
      'Motor_Bremse', 'Motor_Flexia', 'Soll_Verbauliste_neu', 'Systeminfo_1', 'Waehlhebel_1',
    },
    known_bus2={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'BSG_Last', 'Bremse_1', 'Bremse_10',
      'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_5', 'Bremse_8', 'Diagnose_1', 'Einheiten_1',
      'GRA_Neu', 'Gate_Komf_1', 'Gate_Komf_2', 'Getriebe_1', 'Ident', 'Kombi_1', 'Kombi_2',
      'Kombi_3', 'Lenkhilfe_2', 'Lenkhilfe_3', 'Lenkwinkel_1', 'Motor_1', 'Motor_10', 'Motor_2',
      'Motor_3', 'Motor_5', 'Motor_Flexia', 'Soll_Verbauliste_neu', 'Systeminfo_1',
    },
  ),
  dict(
    name="passat_nms_sng_ecd",
    route="0f53129ed44f6920|00000031--0c1aea511e",
    car_fingerprint=CAR.VOLKSWAGEN_PASSAT_NMS,
    flags=524418,  # PQ | IQ_LVBS_ALC_MODULE | IQ_PQ_SNG_ECD
    network_location="gateway",
    transmission_type="automatic",
    enable_bsm=False,
    pcm_cruise=False,
    known_bus1={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'Airbag_2', 'BSG_Last', 'Bremse_1',
      'Bremse_10', 'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_4', 'Bremse_5', 'Bremse_8',
      'Bremse_9', 'Diagnose_1', 'EPB_1', 'EPB_2', 'Einheiten_1', 'GRA_Neu', 'Gate_Komf_1',
      'Gate_Komf_2', 'Getriebe_1', 'Getriebe_2', 'Ident', 'Klima_1', 'Kombi_1', 'Kombi_2',
      'Kombi_3', 'Lenkhilfe_1', 'Lenkhilfe_2', 'Lenkhilfe_3', 'Lenkwinkel_1', 'Motor_1',
      'Motor_10', 'Motor_12', 'Motor_13', 'Motor_2', 'Motor_3', 'Motor_5', 'Motor_6', 'Motor_7',
      'Motor_8', 'Motor_Bremse', 'Motor_Flexia', 'Soll_Verbauliste_neu', 'Systeminfo_1',
    },
    known_bus2={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'BSG_Last', 'Bremse_1', 'Bremse_10',
      'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_5', 'Bremse_8', 'Diagnose_1', 'EPB_1',
      'Einheiten_1', 'GRA_Neu', 'Gate_Komf_1', 'Gate_Komf_2', 'Getriebe_1', 'Ident', 'Kombi_1',
      'Kombi_2', 'Kombi_3', 'Lenkhilfe_2', 'Lenkhilfe_3', 'Lenkwinkel_1', 'Motor_1', 'Motor_10',
      'Motor_2', 'Motor_3', 'Motor_5', 'Motor_Flexia', 'Soll_Verbauliste_neu', 'Systeminfo_1',
    },
  ),
  dict(
    name="passat_b7_acc_fts_epb",
    route="20e3cd4f0d5f39d1|0000008e--274d762bac",
    car_fingerprint=CAR.VOLKSWAGEN_PASSAT_B7,
    flags=262146,  # PQ | IQ_PQ_ACC_FTS_EPB
    network_location="gateway",
    transmission_type="automatic",
    enable_bsm=True,
    pcm_cruise=False,
    known_bus1={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'Airbag_2', 'BSG_Last', 'Bremse_1',
      'Bremse_10', 'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_4', 'Bremse_5', 'Bremse_8',
      'Bremse_9', 'Daempfer_1', 'Diagnose_1', 'EPB_1', 'Einheiten_1', 'GRA_Neu', 'Gate_Komf_1',
      'Gate_Komf_2', 'Getriebe_1', 'Getriebe_2', 'Getriebe_4', 'HCA_1', 'Ident', 'Klima_1',
      'Kombi_1', 'Kombi_2', 'Kombi_3', 'Lenkhilfe_1', 'Lenkhilfe_2', 'Lenkhilfe_3',
      'Lenkwinkel_1', 'Motor_1', 'Motor_10', 'Motor_12', 'Motor_2', 'Motor_3', 'Motor_5',
      'Motor_6', 'Motor_7', 'Motor_8', 'Motor_Bremse', 'Motor_Flexia', 'Parkhilfe_01',
      'Soll_Verbauliste_neu', 'Systeminfo_1', 'Waehlhebel_1',
    },
    known_bus2={
      'ACC_GRA_Anzeige', 'ACC_System', 'AWV', 'Airbag_1', 'BSG_Last', 'Bremse_1', 'Bremse_10',
      'Bremse_11', 'Bremse_2', 'Bremse_3', 'Bremse_5', 'Bremse_8', 'Diagnose_1', 'EPB_1',
      'Einheiten_1', 'GRA_Neu', 'Gate_Komf_1', 'Gate_Komf_2', 'Getriebe_1', 'HCA_1', 'Ident',
      'Kombi_1', 'Kombi_2', 'Kombi_3', 'LDW_Status', 'Lenkhilfe_2', 'Lenkhilfe_3',
      'Lenkwinkel_1', 'Motor_1', 'Motor_10', 'Motor_2', 'Motor_3', 'Motor_5', 'Motor_Flexia',
      'Parkhilfe_01', 'RDK_Status', 'SWA_1', 'Soll_Verbauliste_neu', 'Systeminfo_1',
    },
  ),
]


class TestVolkswagenPqCanValid:
  def test_only_reads_messages_the_real_car_sends(self, subtests):
    for fixture in FIXTURES:
      with subtests.test(car=fixture["name"]):
        CP, CP_IQ = _make_car_params(
          fixture["car_fingerprint"], fixture["flags"], fixture["network_location"],
          fixture["transmission_type"], fixture["enable_bsm"], fixture["pcm_cruise"],
        )

        CS = CarState(CP, CP_IQ)
        can_parsers = CS.get_can_parsers(CP, CP_IQ)

        recorders = {}
        for bus, parser in can_parsers.items():
          if parser is None:
            continue
          parser.vl.__class__ = _RecordingVLDict
          parser.vl.accessed = set()
          recorders[bus] = parser.vl

        # no CAN data is fed: .vl[...] lazily adds and returns default-zero values
        # regardless of whether the parser has ever seen a real frame, so this alone
        # is enough to harvest every message name update_pq() touches for this variant
        CS.update(can_parsers)

        accessed_bus1 = recorders[Bus.pt].accessed | recorders[Bus.aux].accessed
        accessed_bus2 = recorders[Bus.cam].accessed

        extra_bus1 = accessed_bus1 - fixture["known_bus1"]
        extra_bus2 = accessed_bus2 - fixture["known_bus2"]

        assert not extra_bus1, (
          f"{fixture['name']}: code reads {sorted(extra_bus1)} on bus 1 (pt/aux) but the "
          f"real car (route {fixture['route']}) never transmits it -- this needs to be "
          f"gated behind whatever flag makes it optional, or declared with math.nan if it's "
          f"genuinely on-demand/rare, not read unconditionally"
        )
        assert not extra_bus2, (
          f"{fixture['name']}: code reads {sorted(extra_bus2)} on bus 2 (cam) but the "
          f"real car (route {fixture['route']}) never transmits it -- this needs to be "
          f"gated behind whatever flag makes it optional, or declared with math.nan if it's "
          f"genuinely on-demand/rare, not read unconditionally"
        )
