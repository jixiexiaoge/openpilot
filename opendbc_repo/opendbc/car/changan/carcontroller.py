
from opendbc.car import structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.changan import changancan
from opendbc.can.packer import CANPacker
from opendbc.car import Bus

class CarController(CarControllerBase):
    def __init__(self, dbc_names, CP):
        super().__init__(dbc_names, CP)
        self.packer = CANPacker(dbc_names[Bus.pt])
        self.counter_1ba = 0
        self.counter_244 = 0
        self.counter_307 = 0
        self.counter_31a = 0
        self.frame = 0

    def update(self, CC, CS, now_nanos):
        can_sends = []
        if CC.latActive:
            apply_angle = CC.actuators.steeringAngleDeg
            can_sends.append(changancan.create_1BA_command(self.packer, CS.sigs1ba, apply_angle, 1, self.counter_1ba))
        if CC.longActive:
            accel = CC.actuators.accel
            can_sends.append(changancan.create_244_command(self.packer, CS.sigs244, accel, self.counter_244, True, 0, CS.out.vEgoRaw))
        if self.frame % 10 == 0:
            can_sends.append(changancan.create_307_command(self.packer, CS.sigs307, self.counter_307, CS.out.cruiseState.speedCluster))
            can_sends.append(changancan.create_31A_command(self.packer, CS.sigs31a, self.counter_31a, CC.longActive, CS.out.steeringPressed))
            self.counter_307 = (self.counter_307 + 1) % 16
            self.counter_31a = (self.counter_31a + 1) % 16
        self.counter_1ba = (self.counter_1ba + 1) % 16
        self.counter_244 = (self.counter_244 + 1) % 16
        self.frame += 1
        return CC.actuators.as_builder(), can_sends



















