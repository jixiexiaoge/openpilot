"""
Copyright (c) 2025 Rick Lan

This software is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (CC BY-NC-SA 4.0).
You are free to share and adapt this work for non-commercial purposes, provided you give appropriate credit and distribute any modifications under the same license.

To view a copy of this license, visit:
http://creativecommons.org/licenses/by-nc-sa/4.0/

---

**Commercial Licensing:**
Use of this software for commercial purposes is strictly prohibited without a separate, paid license.
To purchase a commercial license, please contact ricklan@gmail.com.
"""

import os
import importlib
import json
from openpilot.common.basedir import BASEDIR
# from openpilot.common.params import Params


class VehicleModelCollector:
  def __init__(self):
    self.base_package = "opendbc.car"
    self.base_path = f"{BASEDIR}/opendbc/car"
    self.exclude_brands = ['body', 'mock']

    # Define the lookup dictionary for brand-to-group mappings
    self.brand_to_group_map = {
      "chrysler": [
        {"prefix": "DODGE_", "group": "Chrysler"},
        {"prefix": "RAM_", "group": "Chrysler"},
        {"prefix": "JEEP_", "group": "Chrysler"},
      ],
      "gm": [
        {"prefix": "BUICK_", "group": "GM"},
        {"prefix": "CADILLAC_", "group": "GM"},
        {"prefix": "CHEVROLET_", "group": "GM"},
        {"prefix": "HOLDEN_", "group": "GM"},
      ],
      "honda": {"prefix": "ACURA_", "group": "Honda"},
      "toyota": {"prefix": "LEXUS_", "group": "Toyota"},
      "hyundai": [
        {"prefix": "KIA_", "group": "Hyundai"},
        {"prefix": "GENESIS_", "group": "Hyundai"}
      ],
      "volkswagen": [
        {"prefix": "AUDI_", "group": "Volkswagen"},
        {"prefix": "SKODA_", "group": "Volkswagen"},
        {"prefix": "SEAT_", "group": "Volkswagen"}
      ]
    }

    # Define exceptions for group names
    self.group_name_exceptions = {
      "gm": "GM",
    }

  @staticmethod
  def is_car_model(car_class, attr):
    """Check if the attribute is a car model (not callable and not a dunder attribute)"""
    return not callable(getattr(car_class, attr)) and not attr.startswith("__")

  @staticmethod
  def move_to_proper_group(models, prefix):
    """
    Moves models with a certain prefix to their respective group.
    Example: Models starting with 'LEXUS_' should go to 'Lexus' group.
    """
    moved_models = []
    for model in models[:]:  # Iterate over a copy to avoid modifying during iteration
      if model.startswith(prefix):
        moved_models.append(model)
        models.remove(model)  # Remove from the original group
    return moved_models

  def format_group_name(self, group_name):
    """
    Formats group names according to the exceptions dictionary.
    Groups in the exceptions dictionary are returned in all caps, others are title cased.
    """
    return self.group_name_exceptions.get(group_name, group_name.title())

  def collect_models(self):
    """Collect all car models and organize them by brand/group"""
    # List all subdirectories (car brands)
    car_brands = sorted([
      name for name in os.listdir(self.base_path)
      if os.path.isdir(os.path.join(self.base_path, name)) and not name.startswith("__")
    ])

    grouped_models = {}

    # Import CAR from each subdirectory and group models by brand
    for brand in car_brands:
      if brand in self.exclude_brands:
        continue

      module_name = f"{self.base_package}.{brand}.values"
      try:
        module = importlib.import_module(module_name)
        if hasattr(module, "CAR"):
          car_class = getattr(module, "CAR")
          models = sorted([attr for attr in dir(car_class) if self.is_car_model(car_class, attr)])

          # Check if the brand has a special group in the lookup map
          if brand in self.brand_to_group_map:
            group_info = self.brand_to_group_map[brand]

            if isinstance(group_info, list):  # If multiple prefixes for the brand
              for prefix_info in group_info:
                moved_models = self.move_to_proper_group(models, prefix_info["prefix"])
                if moved_models:
                  if prefix_info["group"] not in grouped_models:
                    grouped_models[prefix_info["group"]] = []
                  grouped_models[prefix_info["group"]].extend(moved_models)
            else:  # Single prefix for the brand
              moved_models = self.move_to_proper_group(models, group_info["prefix"])
              if moved_models:
                if group_info["group"] not in grouped_models:
                  grouped_models[group_info["group"]] = []
                grouped_models[group_info["group"]].extend(moved_models)

          # Add remaining models to the respective brand
          if models:
            grouped_models[brand] = models
      except ModuleNotFoundError:
        pass

    # Merge groups that have the same formatted name (e.g., "chrysler" and "Chrysler")
    merged_grouped_models = {}
    for group_key, models_list in grouped_models.items():
        formatted_group_name = self.format_group_name(group_key)
        if formatted_group_name not in merged_grouped_models:
            merged_grouped_models[formatted_group_name] = []
        merged_grouped_models[formatted_group_name].extend(models_list)

    # Create a new dictionary to hold the sorted models
    sorted_models = {}
    for group_key, models_list in merged_grouped_models.items():
        sorted_models[group_key] = sorted(models_list)

    return sorted_models

  # def save_to_params(self, output=None):
  #   """Save the collected model list to Params"""
  #   if output is None:
  #     output = self.collect_models()
  #   Params().put("dp_dev_model_list", json.dumps(output))
  #   return output
  #
  # def run(self):
  #   """Collect models and save to params"""
  #   models = self.collect_models()
  #   self.save_to_params(models)
  #   return models

  def get_json(self):
    return self.collect_models()

  def get(self):
    return json.dumps(self.collect_models())

# Allow running as a script
if __name__ == "__main__":
  collector = VehicleModelCollector()
  print(collector.get())
