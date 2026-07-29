from typing import get_args
from iqdbc.car.body.values import CAR as BODY
from iqdbc.car.chrysler.values import CAR as CHRYSLER
from iqdbc.car.ford.values import CAR as FORD
from iqdbc.car.gm.values import CAR as GM
from iqdbc.car.honda.values import CAR as HONDA
from iqdbc.car.hyundai.values import CAR as HYUNDAI
from iqdbc.car.mazda.values import CAR as MAZDA
from iqdbc.car.mock.values import CAR as MOCK
from iqdbc.car.nissan.values import CAR as NISSAN
from iqdbc.car.psa.values import CAR as PSA
from iqdbc.car.rivian.values import CAR as RIVIAN
from iqdbc.car.subaru.values import CAR as SUBARU
from iqdbc.car.tesla.values import CAR as TESLA
from iqdbc.car.toyota.values import CAR as TOYOTA
from iqdbc.car.volkswagen.values import CAR as VOLKSWAGEN

Platform = BODY | CHRYSLER | FORD | GM | HONDA | HYUNDAI | MAZDA | MOCK | NISSAN | PSA | RIVIAN | SUBARU | TESLA | TOYOTA | VOLKSWAGEN
BRANDS = get_args(Platform)

PLATFORMS: dict[str, Platform] = {str(platform): platform for brand in BRANDS for platform in brand}
