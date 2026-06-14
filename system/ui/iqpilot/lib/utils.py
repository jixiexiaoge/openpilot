"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.system.ui.iqpilot.widgets.list_view import IQButtonAction


class NoElideButtonAction(IQButtonAction):
  def get_width_hint(self):
    return super().get_width_hint() + 1
