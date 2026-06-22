#!/usr/bin/env python3
import os
from openpilot.common.basedir import BASEDIR
from dragonpilot.system.ui.lib.multilang import TRANSLATIONS_DIR, multilang

LANGUAGES_FILE = os.path.join(str(TRANSLATIONS_DIR), "languages.json")
POT_FILE = os.path.join(str(TRANSLATIONS_DIR), "dragonpilot.pot")


def update_translations():
  files = []
  for root, _, filenames in os.walk(os.path.join(BASEDIR, "dragonpilot")):
    for filename in filenames:
      if filename.endswith(".py"):
        files.append(os.path.relpath(os.path.join(root, filename), BASEDIR))

  # Create main translation file
  cmd = ("xgettext -L Python --keyword=tr --keyword=trn:1,2 --keyword=tr_noop --from-code=UTF-8 " +
         "--flag=tr:1:python-brace-format --flag=trn:1:python-brace-format --flag=trn:2:python-brace-format " +
         f"-D {BASEDIR} -o {POT_FILE} {' '.join(files)}")

  ret = os.system(cmd)
  assert ret == 0

  # Generate/update translation files for each language
  for name in multilang.languages.values():
    po_file = os.path.join(TRANSLATIONS_DIR, f"dragonpilot_{name}.po")
    mo_file = os.path.join(TRANSLATIONS_DIR, f"dragonpilot_{name}.mo")

    if os.path.exists(po_file):
      cmd = f"msgmerge --update --no-fuzzy-matching --backup=none --sort-output {po_file} {POT_FILE}"
      ret = os.system(cmd)
      assert ret == 0
    else:
      cmd = f"msginit -l {name} --no-translator --input {POT_FILE} --output-file {po_file}"
      ret = os.system(cmd)
      assert ret == 0

    # Compile .po to .mo
    cmd = f"msgfmt {po_file} -o {mo_file}"
    ret = os.system(cmd)
    assert ret == 0


if __name__ == "__main__":
  update_translations()
