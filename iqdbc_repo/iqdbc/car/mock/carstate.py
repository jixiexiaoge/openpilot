from iqdbc.car import structs
from iqdbc.car.interfaces import CarStateBase


class CarState(CarStateBase):
  def update(self, *_) -> tuple[structs.CarState, structs.IQCarState]:
    return structs.CarState(), structs.IQCarState()
