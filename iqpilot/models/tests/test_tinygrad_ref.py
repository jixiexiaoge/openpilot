"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import requests

from openpilot.iqpilot.models.tinygrad_ref import get_tinygrad_ref
from openpilot.iqpilot.models.fetcher import ModelFetcher
from openpilot.iqpilot.models.git_auth import get_requests_auth


def fetch_tinygrad_ref():
  response = requests.get(ModelFetcher.get_model_urls()[0], timeout=10, auth=get_requests_auth())
  response.raise_for_status()
  json_data = response.json()
  return json_data.get("tinygrad_ref")


def test_tinygrad_ref():
  current_ref = get_tinygrad_ref()
  remote_ref = fetch_tinygrad_ref()
  assert remote_ref == current_ref, (
    f"""tinygrad_repo ref does not match remote tinygrad_ref of current compiled driving models json.
  Current: {current_ref}
  Remote: {remote_ref}
  Please run build-all workflow to update models."""
  )
  print("tinygrad_repo ref matches current compiled driving models json ref.")
