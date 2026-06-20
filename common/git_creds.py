import base64
import json
import os
import subprocess

from openpilot.common.params import Params

PARAM = "GitAuthBlob"
KEY_DIR = "/data/konn3kt"
KEY_PATH = os.path.join(KEY_DIR, "git_auth.key")


def _load_or_create_key() -> bytes:
  from cryptography.fernet import Fernet
  try:
    with open(KEY_PATH, "rb") as f:
      return f.read().strip()
  except FileNotFoundError:
    pass
  key = Fernet.generate_key()
  os.makedirs(KEY_DIR, exist_ok=True)
  # write atomically with restrictive perms
  tmp = KEY_PATH + ".tmp"
  fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  with os.fdopen(fd, "wb") as f:
    f.write(key)
  os.replace(tmp, KEY_PATH)
  return key


def set_credentials(username: str, token: str) -> None:
  """Encrypt and store credentials. Empty username AND token clears them."""
  username = (username or "").strip()
  token = (token or "").strip()
  if not username and not token:
    clear_credentials()
    return
  from cryptography.fernet import Fernet
  blob = Fernet(_load_or_create_key()).encrypt(
    json.dumps({"u": username, "t": token}).encode()
  )
  Params().put(PARAM, blob)


def get_credentials() -> tuple[str, str] | None:
  """Return (username, token), or None if unset / unreadable."""
  blob = Params().get(PARAM)
  if not blob:
    return None
  try:
    from cryptography.fernet import Fernet
    data = json.loads(Fernet(_load_or_create_key()).decrypt(blob).decode())
    return data.get("u", ""), data.get("t", "")
  except Exception:
    return None


def clear_credentials() -> None:
  Params().remove(PARAM)


def has_credentials() -> bool:
  return get_credentials() is not None


def _auth_header(username: str, token: str) -> str:
  return "Authorization: Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()


def ssh_to_https(url: str) -> str:
  """Convert an SSH git URL to its HTTPS equivalent. Returns url unchanged if it
  is not an SSH URL. A leading ssh. host label is dropped (ssh.host -> host)."""
  url = url.strip()
  host = path = ""
  if url.startswith("ssh://"):
    rest = url[len("ssh://"):]
    rest = rest.split("@", 1)[-1]          # drop user@
    hostport, _, path = rest.partition("/")
    host = hostport.split(":", 1)[0]       # drop :port
  elif url.startswith("git@") or ("@" in url and ":" in url.split("@", 1)[-1] and "://" not in url):
    rest = url.split("@", 1)[-1]           # host:owner/repo.git
    host, _, path = rest.partition(":")
  else:
    return url  # already https/http or unrecognised
  if host.startswith("ssh."):
    host = host[len("ssh."):]
  return f"https://{host}/{path}"


def configure(repo_dir: str) -> None:
  """Apply on-device credentials to the git repo at repo_dir before a remote op.

  No-op when no credentials are stored. If the origin is an SSH URL it is
  rewritten in-place to the HTTPS equivalent so the Basic-auth header applies.
  The header is injected via GIT_CONFIG_* env (never persisted to .git/config).
  Idempotent."""
  creds = get_credentials()
  if creds is None:
    return
  username, token = creds

  origin = subprocess.run(
    ["git", "-C", repo_dir, "config", "--get", "remote.origin.url"],
    capture_output=True, text=True, check=False,
  ).stdout.strip()
  if not origin:
    return

  https = ssh_to_https(origin)
  if https != origin and https.startswith("https://"):
    subprocess.run(
      ["git", "-C", repo_dir, "config", "remote.origin.url", https],
      check=False, capture_output=True,
    )

  if not https.startswith("https://"):
    return  # header auth only works over https

  # scope to this exact repo URL prefix (trailing slash => component boundary)
  key = https if https.endswith("/") else https + "/"
  os.environ["GIT_CONFIG_COUNT"] = "1"
  os.environ["GIT_CONFIG_KEY_0"] = f"http.{key}.extraHeader"
  os.environ["GIT_CONFIG_VALUE_0"] = _auth_header(username, token)
