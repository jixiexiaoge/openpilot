"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from .base import BrandSettings
from .body import BodySettings
from .chrysler import ChryslerSettings
from .ford import FordSettings
from .gm import GMSettings
from .honda import HondaSettings
from .hyundai import HyundaiSettings
from .mazda import MazdaSettings
from .nissan import NissanSettings
from .psa import PSASettings
from .rivian import RivianSettings
from .subaru import SubaruSettings
from .tesla import TeslaSettings
from .toyota import ToyotaSettings
from .volkswagen import VolkswagenSettings


class BrandSettingsFactory:
  _BRAND_MAP: dict[str, type[BrandSettings]] = {
    "body": BodySettings,
    "chrysler": ChryslerSettings,
    "ford": FordSettings,
    "gm": GMSettings,
    "honda": HondaSettings,
    "hyundai": HyundaiSettings,
    "mazda": MazdaSettings,
    "nissan": NissanSettings,
    "psa": PSASettings,
    "rivian": RivianSettings,
    "subaru": SubaruSettings,
    "tesla": TeslaSettings,
    "toyota": ToyotaSettings,
    "volkswagen": VolkswagenSettings,
  }

  @staticmethod
  def create_brand_settings(brand: str) -> BrandSettings | None:
    cls = BrandSettingsFactory._BRAND_MAP.get(brand)
    return cls() if cls is not None else None
