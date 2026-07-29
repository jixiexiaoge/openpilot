"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""


import os
from openpilot.common.api.base import BaseApi
API_HOST = os.getenv('KONN3KT_API_HOST', 'https://api-iqlabs.konn3kt.com')

class Konn3ktApi(BaseApi):

  def __init__(self, dongle_id):
    super().__init__(dongle_id, API_HOST)
    self.user_agent = "konn3kt-device-"

  def get_token(self, expiry_hours=1):
    return super()._get_token(expiry_hours=expiry_hours)
