#!/usr/bin/env python3
"""
Usage::

  usage: auth.py [-h] [{github,jwt}] [jwt]

  Login to your konn3kt account

  positional arguments:
    {github,jwt}
    jwt

  optional arguments:
    -h, --help            show this help message and exit


Examples::

  ./auth.py            # Log in with GitHub
  ./auth.py jwt ey..hw # Log in with a pre-issued JWT (for CI)
"""

import argparse
import sys
import pprint
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode

from openpilot.tools.lib.api import APIError, CommaApi, UnauthorizedError
from openpilot.tools.lib.auth_config import set_token, get_token

PORT = 3000


class ClientRedirectServer(HTTPServer):
  query_params: dict[str, Any] = {}


class ClientRedirectHandler(BaseHTTPRequestHandler):
  def do_GET(self):
    if '?' in self.path:
      query_parsed = parse_qs(self.path.split('?', 1)[1], keep_blank_values=True)
      if 'code' in query_parsed or 'error' in query_parsed:
        self.server.query_params = query_parsed

    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write(b'Return to the CLI to continue')

  def log_message(self, fmt, *fmt_args):
    sys.stderr.write(f"[auth callback] {self.address_string()} {fmt % fmt_args}\n")


def auth_redirect_link(method):
  if method != 'github':
    raise NotImplementedError(f"no redirect implemented for method {method}")

  params = {
    'client_id': 'Ov23lifjMafxJzFatvuB',
    'redirect_uri': 'https://api-iqlabs.konn3kt.com/v2/auth/h/redirect/',
    'state': f'service,localhost:{PORT}',
    'scope': 'read:user',
  }
  return 'https://github.com/login/oauth/authorize?' + urlencode(params)


def login(method):
  oauth_uri = auth_redirect_link(method)

  web_server = ClientRedirectServer(('localhost', PORT), ClientRedirectHandler)
  print(f'To sign in, use your browser and navigate to {oauth_uri}')
  webbrowser.open(oauth_uri, new=2)

  while True:
    web_server.handle_request()
    if 'code' in web_server.query_params:
      break
    elif 'error' in web_server.query_params:
      print('Authentication Error: "{}". Description: "{}" '.format(
        web_server.query_params['error'],
        web_server.query_params.get('error_description')), file=sys.stderr)
      break

  try:
    auth_resp = CommaApi().post('v2/auth/', data={'code': web_server.query_params['code'], 'provider': web_server.query_params['provider']})
    set_token(auth_resp['access_token'])
  except APIError as e:
    print(f'Authentication Error: {e}', file=sys.stderr)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Login to your konn3kt account')
  parser.add_argument('method', default='github', const='github', nargs='?', choices=['github', 'jwt'])
  parser.add_argument('jwt', nargs='?')

  args = parser.parse_args()
  if args.method == 'jwt':
    if args.jwt is None:
      print("method JWT selected, but no JWT was provided")
      exit(1)

    set_token(args.jwt)
  else:
    login(args.method)

  try:
    me = CommaApi(token=get_token()).get('/v1/me')
    print("Authenticated!")
    pprint.pprint(me)
  except UnauthorizedError:
    print("Got invalid JWT")
    exit(1)
