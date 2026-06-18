# FW query is disabled for MG for now (see values.py): the MG ZS has no captured
# FW versions yet and no CAN fingerprint, so it is identified by forced car
# selection only. Leaving FW_VERSIONS undefined keeps MG out of the FW-query path
# (get_interface_attr uses ignore_none). Restore once we can query FW on the MG ZS:
#
# from opendbc.car.structs import CarParams
# from opendbc.car.mg.values import CAR
#
# Ecu = CarParams.Ecu
#
# FW_VERSIONS = {
#   CAR.MG_ZS: {
#     # populate via tools/car_porting/auto_fingerprint.py once a route with FW
#     # query enabled is captured on the 2025 MG ZS
#   },
# }
