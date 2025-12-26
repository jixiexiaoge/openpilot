"""
Copyright (c) 2025, Rick Lan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, and/or sublicense, 
for non-commercial purposes only, subject to the following conditions:

- The above copyright notice and this permission notice shall be included in 
  all copies or substantial portions of the Software.
- Commercial use (e.g. use in a product, service, or activity intended to 
  generate revenue) is prohibited without explicit written permission from 
  the copyright holder.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

#!/usr/bin/env python3

import argparse
# import asyncio
# import json
import os
import logging
from datetime import datetime
from urllib.parse import quote
# import socket
# import sys

from aiohttp import web

from openpilot.common.params import Params
from openpilot.system.hardware import PC


# --- File Browser Settings ---
DEFAULT_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), '..') if PC else '/data/media/0/realdata')
WEB_DIST_PATH = os.path.join(os.path.dirname(__file__), "..", "web", "dist")

def get_safe_path(requested_path):
    """Ensures the requested path is within DEFAULT_DIR, preventing arbitrary file access"""
    combined_path = os.path.join(DEFAULT_DIR, requested_path.lstrip('/'))
    safe_path = os.path.realpath(combined_path)
    if os.path.commonpath((safe_path, DEFAULT_DIR)) == DEFAULT_DIR:
        return safe_path
    return None

async def list_files_api(request):
    """API endpoint to list files and folders"""
    try:
        path_param = request.query.get('path', '/')
        safe_path = get_safe_path(path_param)
        if not safe_path or not os.path.isdir(safe_path):
            return web.json_response({'error': 'Invalid or Not Found Path'}, status=404)
        items = []
        for entry in os.listdir(safe_path):
            full_path = os.path.join(safe_path, entry)
            try:
                stat = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                items.append({
                    'name': entry,
                    'is_dir': is_dir,
                    'mtime': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                    'size': stat.st_size if not is_dir else 0
                })
            except FileNotFoundError:
                continue
        directories = sorted([item for item in items if item['is_dir']], key=lambda x: x['mtime'], reverse=True)
        files = sorted([item for item in items if not item['is_dir']], key=lambda x: x['mtime'], reverse=True)
        items = directories + files
        relative_path = os.path.relpath(safe_path, DEFAULT_DIR)
        if relative_path == '.':
            relative_path = ''
        return web.json_response({'path': relative_path, 'files': items})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def serve_player_api(request):
    """API endpoint to serve the HLS player page"""
    file_path = request.query.get('file')
    if not file_path:
        return web.Response(text="File parameter is required.", status=400)

    player_html_path = os.path.join(WEB_DIST_PATH, 'pages', 'player.html')
    try:
        with open(player_html_path, 'r') as f:
            html_template = f.read()
    except FileNotFoundError:
        return web.Response(text="Player HTML not found.", status=500)

    encoded_path = quote(file_path)
    html = html_template.replace('{{FILE_PATH}}', encoded_path)
    return web.Response(text=html, content_type='text/html')

async def serve_manifest_api(request):
    """API endpoint to dynamically generate m3u8 playlist"""
    file_path = request.query.get('file').lstrip('/')
    if not file_path:
        return web.Response(text="File parameter is required.", status=400)
    encoded_path = quote(file_path)
    manifest = f"""#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:60\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:60.0,\n/media/{encoded_path}\n#EXT-X-ENDLIST\n"""
    return web.Response(text=manifest, content_type='application/vnd.apple.mpegurl')

async def save_settings_api(request):
    """API endpoint to receive and save settings"""
    try:
        data = await request.json()
        logging.getLogger("web_ui").info(f"Received settings to save: {data}")
        return web.json_response({'status': 'success', 'message': 'Settings saved successfully!'})
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error saving settings: {e}")
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def get_settings_config_api(request):
    """API endpoint to get the settings configuration from settings.py"""
    try:
        # Import settings.py from dragonpilot
        import sys
        import os
        dp_path = os.path.join(os.path.dirname(__file__), '..', '..', 'dragonpilot')
        if dp_path not in sys.path:
            sys.path.insert(0, dp_path)

        from dragonpilot.settings import SETTINGS
        from openpilot.system.ui.lib.multilang import multilang as base_multilang

        # Get current values from Params
        params = Params()

        # Sync language from params (server is separate process, doesn't see UI language changes)
        current_lang = params.get("LanguageSetting")
        if current_lang:
            lang_str = current_lang.decode() if isinstance(current_lang, bytes) else str(current_lang)
            lang_str = lang_str.removeprefix("main_")
            if lang_str != base_multilang.language and lang_str in base_multilang.languages.values():
                base_multilang._language = lang_str
                base_multilang.setup()

        # Helper function to evaluate conditions
        def eval_condition(condition, context):
            if not condition:
                return True
            try:
                return eval(condition, {"__builtins__": {}}, context)
            except Exception as e:
                logging.getLogger("web_ui").debug(f"Condition evaluation failed: {condition}, error: {e}")
                return False

        # Build context for condition evaluation
        # Get car brand and longitudinal control from CarParams
        brand = ""
        openpilot_longitudinal_control = False

        try:
            # Try to get CarParams from params
            car_params_bytes = params.get("CarParams")
            if car_params_bytes:
                # Import CarParams protobuf from cereal
                from cereal import car

                # Parse the CarParams message using context manager
                with car.CarParams.from_bytes(car_params_bytes) as cp:
                    brand = cp.brand
                    openpilot_longitudinal_control = cp.openpilotLongitudinalControl
                    logging.getLogger("web_ui").info(f"Got CarParams: brand={brand}, openpilotLongitudinalControl={openpilot_longitudinal_control}")
        except Exception as e:
            logging.getLogger("web_ui").warning(f"Could not parse CarParams: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to showing all settings if we can't get CarParams
            pass

        # Check for LITE and MICI
        lite = os.getenv("LITE") is not None

        # Check for MICI device type
        mici = False
        try:
            from openpilot.system.hardware import HARDWARE
            mici = HARDWARE.get_device_type() == "mici"
        except Exception as e:
            logging.getLogger("web_ui").debug(f"Could not check MICI device type: {e}")

        context = {
            'brand': brand,
            'openpilotLongitudinalControl': openpilot_longitudinal_control,
            'LITE': lite,
            'MICI': mici
        }

        logging.getLogger("web_ui").info(f"Settings context: {context}")

        # Helper to resolve callable values (lambdas) for JSON serialization
        def resolve_value(value):
            return value() if callable(value) else value

        # Process settings and add current values
        settings_with_values = []
        for section in SETTINGS:
            # Check section condition (e.g., brand == 'toyota')
            if not eval_condition(section.get('condition'), context):
                continue

            section_copy = section.copy()
            settings_list = []

            for setting in section.get('settings', []):
                # Check setting-level condition if it exists
                if not eval_condition(setting.get('condition'), context):
                    continue
                setting_copy = setting.copy()
                key = setting['key']

                # Resolve callable values for JSON serialization
                for field in ['title', 'description', 'suffix', 'special_value_text']:
                    if field in setting_copy:
                        setting_copy[field] = resolve_value(setting_copy[field])
                if 'options' in setting_copy:
                    setting_copy['options'] = [resolve_value(opt) for opt in setting_copy['options']]

                # Debug: Log the setting properties
                if key == 'dp_lat_lca_speed':
                    logging.getLogger("web_ui").info(f"Setting {key}: min_val={setting_copy.get('min_val')}, max_val={setting_copy.get('max_val')}, step={setting_copy.get('step')}")

                try:
                    # Get current value from Params based on type
                    if setting['type'] == 'toggle_item':
                        setting_copy['current_value'] = params.get_bool(key)
                    elif setting['type'] == 'spin_button_item':
                        value = params.get(key)
                        try:
                            setting_copy['current_value'] = int(value) if value is not None else setting.get('default', 0)
                        except:
                            setting_copy['current_value'] = setting.get('default', 0)
                    elif setting['type'] == 'double_spin_button_item':
                        value = params.get(key)
                        try:
                            setting_copy['current_value'] = float(value) if value is not None else setting.get('default', 0.0)
                        except:
                            setting_copy['current_value'] = setting.get('default', 0.0)
                    elif setting['type'] == 'text_spin_button_item':
                        value = params.get(key)
                        try:
                            setting_copy['current_value'] = int(value) if value is not None else setting.get('default', 0)
                        except:
                            setting_copy['current_value'] = setting.get('default', 0)
                except Exception as e:
                    logging.getLogger("web_ui").warning(f"Error getting value for {key}: {e}")
                    # Use default value if we can't get current value
                    if setting['type'] == 'toggle_item':
                        setting_copy['current_value'] = False
                    elif setting['type'] in ['spin_button_item', 'text_spin_button_item']:
                        setting_copy['current_value'] = setting.get('default', 0)
                    elif setting['type'] == 'double_spin_button_item':
                        setting_copy['current_value'] = setting.get('default', 0.0)

                settings_list.append(setting_copy)

            # Only add the section if it has settings
            if settings_list:
                section_copy['settings'] = settings_list
                settings_with_values.append(section_copy)

        return web.json_response({'settings': settings_with_values})
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error fetching settings config: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({'error': f"Error fetching settings config: {e}"}, status=500)

async def save_settings_values_api(request):
    """API endpoint to save settings values to Params"""
    try:
        data = await request.json()
        params = Params()

        for key, value in data.items():
            try:
                # Get the parameter type from Params
                param_type = params.get_type(key)

                # Convert and save based on type
                if param_type == 1:  # BOOL
                    params.put_bool(key, bool(value))
                elif param_type == 2:  # INT
                    params.put(key, int(value))
                elif param_type == 3:  # FLOAT
                    params.put(key, float(value))
                else:  # STRING, BYTES, JSON, TIME, or unknown
                    if isinstance(value, bool):
                        params.put_bool(key, value)
                    elif isinstance(value, (int, float)):
                        params.put(key, str(value))
                    else:
                        params.put(key, str(value))

                logging.getLogger("web_ui").debug(f"Saved {key}={value} (type={param_type})")
            except Exception as e:
                logging.getLogger("web_ui").error(f"Error saving param {key}={value}: {e}")
                raise

        logging.getLogger("web_ui").info(f"Settings saved successfully: {list(data.keys())}")
        return web.json_response({'status': 'success', 'message': 'Settings saved successfully!'})
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error saving settings: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def get_model_list_api(request):
    """API endpoint to get the model list and current selection."""
    try:
        params = Params()
        import json

        # Get model list from dp_dev_model_list
        model_list = {}
        try:
            model_list_raw = params.get("dp_dev_model_list")
            if model_list_raw:
                model_list = json.loads(model_list_raw)
        except Exception as e:
            logging.getLogger("web_ui").debug(f"Could not parse dp_dev_model_list: {e}")

        # Get current selection from dp_dev_model_selected
        selected_model = ""
        try:
            selected_raw = params.get("dp_dev_model_selected")
            if selected_raw:
                selected_model = selected_raw.decode('utf-8') if isinstance(selected_raw, bytes) else str(selected_raw)
        except Exception as e:
            logging.getLogger("web_ui").debug(f"Could not get dp_dev_model_selected: {e}")

        return web.json_response({
            'model_list': model_list,
            'selected_model': selected_model
        })
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error fetching model list: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def save_model_selection_api(request):
    """API endpoint to save the selected model."""
    try:
        data = await request.json()
        params = Params()

        selected_model = data.get('selected_model', '')

        # If empty or "[AUTO]", clear the param
        if not selected_model or selected_model == "[AUTO]":
            params.put("dp_dev_model_selected", "")
            logging.getLogger("web_ui").info("Model selection cleared (AUTO mode)")
        else:
            params.put("dp_dev_model_selected", selected_model)
            logging.getLogger("web_ui").info(f"Model selection saved: {selected_model}")

        return web.json_response({'status': 'success'})
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error saving model selection: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def init_api(request):
    """API endpoint to provide initial data to the client."""
    try:
        params = Params()

        # Get openpilotLongitudinalControl from CarParams
        openpilot_longitudinal_control = False
        try:
            car_params_bytes = params.get("CarParams")
            if car_params_bytes:
                from cereal import car
                with car.CarParams.from_bytes(car_params_bytes) as cp:
                    openpilot_longitudinal_control = cp.openpilotLongitudinalControl
        except Exception as e:
            logging.getLogger("web_ui").debug(f"Could not parse CarParams: {e}")

        # dp_dev_dashy may not exist on all devices, default to True
        try:
            dp_dev_dashy = params.get_bool("dp_dev_dashy")
        except Exception:
            dp_dev_dashy = True

        return web.json_response({
            'is_metric': params.get_bool("IsMetric"),
            'dp_dev_dashy': dp_dev_dashy,
            'openpilot_longitudinal_control': openpilot_longitudinal_control,
        })
    except Exception as e:
        logging.getLogger("web_ui").error(f"Error fetching initial data: {e}")
        return web.json_response({'error': f"Error fetching initial data: {e}"}, status=500)

async def on_startup(app):
    logging.getLogger("web_ui").info("Web UI application starting up...")

async def on_cleanup(app):
    logging.getLogger("web_ui").info("Web UI application shutting down...")

# --- CORS Middleware ---
@web.middleware
async def cors_middleware(request, handler):
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

async def handle_cors_preflight(request):
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Max-Age': '86400',
        }
        return web.Response(status=200, headers=headers)
    return await request.app['handler'](request)

def setup_aiohttp_app(host: str, port: int, debug: bool):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logging.getLogger("web_ui").setLevel(logging.DEBUG if debug else logging.INFO)

    app = web.Application(middlewares=[cors_middleware])
    app['port'] = port

    # Register API endpoints
    app.router.add_get("/api/init", init_api)
    app.router.add_get("/api/files", list_files_api)
    app.router.add_get("/api/play", serve_player_api)
    app.router.add_get("/api/manifest.m3u8", serve_manifest_api)
    app.router.add_get("/api/settings/config", get_settings_config_api)
    app.router.add_post("/api/settings/save", save_settings_values_api)
    app.router.add_get("/api/models", get_model_list_api)
    app.router.add_post("/api/models/select", save_model_selection_api)

    # Static files
    app.router.add_static('/media', path=DEFAULT_DIR, name='media', show_index=False, follow_symlinks=False)
    app.router.add_static('/download', path=DEFAULT_DIR, name='download', show_index=False, follow_symlinks=False)
    app.router.add_get("/", lambda r: web.FileResponse(os.path.join(WEB_DIST_PATH, "index.html")))
    app.router.add_static("/", path=WEB_DIST_PATH)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    # Add CORS preflight handler
    app.router.add_route('OPTIONS', '/{tail:.*}', handle_cors_preflight)

    return app

def main():
    # rick - may need "sudo ufw allow 5088" to allow port access
    parser = argparse.ArgumentParser(description="Dashy Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to listen on")
    parser.add_argument("--port", type=int, default=5088, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = setup_aiohttp_app(args.host, args.port, args.debug)
    web.run_app(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
