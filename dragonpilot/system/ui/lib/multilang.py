import gettext
from openpilot.system.ui.lib.multilang import (
  multilang as base_multilang,
  TRANSLATIONS_DIR,
  tr_noop,
)


class DpMultilang:
  """Wrapper that syncs with base multilang and adds dragonpilot translations."""

  def __init__(self):
    self._dragon_translation: gettext.NullTranslations | gettext.GNUTranslations = gettext.NullTranslations()
    self._loaded_language: str = ""

  @property
  def languages(self):
    """Delegate to base multilang."""
    return base_multilang.languages

  @property
  def language(self):
    """Delegate to base multilang."""
    return base_multilang.language

  def _ensure_loaded(self):
    """Reload dragon translations if base language changed."""
    current_lang = base_multilang.language
    if current_lang != self._loaded_language:
      self._loaded_language = current_lang
      try:
        with TRANSLATIONS_DIR.joinpath(f'dragonpilot_{current_lang}.mo').open('rb') as fh:
          self._dragon_translation = gettext.GNUTranslations(fh)
      except FileNotFoundError:
        self._dragon_translation = gettext.NullTranslations()

  def tr(self, text: str) -> str:
    self._ensure_loaded()
    result = self._dragon_translation.gettext(text)
    return result if result != text else base_multilang.tr(text)

  def trn(self, singular: str, plural: str, n: int) -> str:
    self._ensure_loaded()
    result = self._dragon_translation.ngettext(singular, plural, n)
    return result if result not in (singular, plural) else base_multilang.trn(singular, plural, n)


multilang = DpMultilang()

tr, trn = multilang.tr, multilang.trn

__all__ = ['multilang', 'tr', 'trn', 'tr_noop', 'TRANSLATIONS_DIR']
