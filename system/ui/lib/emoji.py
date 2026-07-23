import io
import re

from PIL import Image, ImageDraw, ImageFont
import pyray as rl

from openpilot.system.ui.lib.application import FONT_DIR

_emoji_font: ImageFont.FreeTypeFont | None = None
_cache: dict[str, rl.Texture] = {}

EMOJI_REGEX = re.compile(
"""[\U0001F600-\U0001F64F
\U0001F300-\U0001F5FF
\U0001F680-\U0001F6FF
\U0001F1E0-\U0001F1FF
\U00002700-\U000027BF
\U0001F900-\U0001F9FF
\U00002600-\U000026FF
\U00002300-\U000023FF
\U00002B00-\U00002BFF
\U0001FA70-\U0001FAFF
\U0001F700-\U0001F77F
\u2640-\u2642
\u2600-\u2B55
\u200d
\u23cf
\u23e9
\u231a
\ufe0f
\u3030
]+""".replace("\n", ""),
  flags=re.UNICODE
)

_emoji_font_loaded = False

def _load_emoji_font() -> ImageFont.FreeTypeFont | None:
  global _emoji_font, _emoji_font_loaded
  if not _emoji_font_loaded:
    _emoji_font_loaded = True
    try:
      # FONT_DIR is an importlib.resources path. Inside the setup zipapp it points into the archive,
      # so str() yields a path through the .zip that PIL can't open ("cannot open resource"). Read
      # the bytes and hand PIL a file object so it works both on disk and inside the zipapp.
      _emoji_font = ImageFont.truetype(io.BytesIO(FONT_DIR.joinpath("NotoColorEmoji.ttf").read_bytes()), 109)
    except Exception:
      _emoji_font = None  # never crash the whole UI over an emoji glyph
  return _emoji_font

def find_emoji(text):
  return [(m.start(), m.end(), m.group()) for m in EMOJI_REGEX.finditer(text)]

def emoji_tex(emoji):
  if emoji not in _cache:
    font = _load_emoji_font()
    if font is None:
      return None
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((0, 0), emoji, font=font, embedded_color=True)
    with io.BytesIO() as buffer:
      img.save(buffer, format="PNG")
      l = buffer.tell()
      buffer.seek(0)
      _cache[emoji] = rl.load_texture_from_image(rl.load_image_from_memory(".png", buffer.getvalue(), l))
  return _cache.get(emoji)
