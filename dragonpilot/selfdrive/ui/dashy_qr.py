import socket
import time

import pyray as rl
import qrcode
import numpy as np
from openpilot.common.swaglog import cloudlog

IP_REFRESH_INTERVAL = 5  # seconds


class DashyQR:
  """Shared QR code generator for dashy web UI."""

  def __init__(self):
    self._qr_texture: rl.Texture | None = None
    self._last_qr_url: str | None = None
    self._last_ip_check: float = 0

  @property
  def texture(self):
    return self._qr_texture

  @property
  def url(self) -> str | None:
    return self._last_qr_url

  @staticmethod
  def get_local_ip() -> str | None:
    try:
      s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      s.connect(("8.8.8.8", 80))
      ip = s.getsockname()[0]
      s.close()
      return ip
    except Exception:
      return None

  @staticmethod
  def get_web_ui_url() -> str:
    ip = DashyQR.get_local_ip()
    return f"http://{ip if ip else 'localhost'}:5088"

  def _generate_qr_code(self, url: str) -> None:
    try:
      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=0)
      qr.add_data(url)
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="white", back_color="black").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      if self._qr_texture and self._qr_texture.id != 0:
        rl.unload_texture(self._qr_texture)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      self._qr_texture = rl.load_texture_from_image(rl_image)
      self._last_qr_url = url
    except Exception as e:
      cloudlog.warning(f"QR code generation failed: {e}")
      self._qr_texture = None

  def update(self, force: bool = False) -> bool:
    """Update QR code if needed. Returns True if updated."""
    now = time.monotonic()
    if not force and now - self._last_ip_check < IP_REFRESH_INTERVAL and self._qr_texture:
      return False

    self._last_ip_check = now
    url = self.get_web_ui_url()
    if url != self._last_qr_url:
      self._generate_qr_code(url)
      return True
    return False

  def force_update(self):
    """Force immediate IP check and QR regeneration."""
    self._last_ip_check = 0

  def cleanup(self):
    """Unload texture resources."""
    if self._qr_texture and self._qr_texture.id != 0:
      rl.unload_texture(self._qr_texture)
      self._qr_texture = None

  def __del__(self):
    self.cleanup()
