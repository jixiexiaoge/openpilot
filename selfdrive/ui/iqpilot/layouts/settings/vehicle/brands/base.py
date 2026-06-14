"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import abc


class BrandSettings(abc.ABC):
  def __init__(self):
    self.items = []

  @abc.abstractmethod
  def update_settings(self) -> None:
    """Update the settings based on the current vehicle brand."""
