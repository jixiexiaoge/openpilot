import csv


def max_limit_check(val, max_val, min_val):
  return (val > max_val) or (val < min_val)


def rt_rate_limit_check(val, val_last, rt_delta):
  highest_val = max(val_last, 0) + rt_delta
  lowest_val = min(val_last, 0) - rt_delta
  # print("{}, {}, {}".format(val, highest_val, lowest_val))
  return max_limit_check(val, highest_val, lowest_val)


def rt_rate_limit_check_debug(val, val_last, rt_delta):
  highest_val = max(val_last, 0) + rt_delta
  lowest_val = min(val_last, 0) - rt_delta
  print("{}, {}, {}".format(val, highest_val, lowest_val))


lkas_requests = []
# Open the CSV file
with open('/mnt/r/0000013b--a0429d8b1c_CAM_LKAS.csv', 'r') as csvfile:
  reader = csv.DictReader(csvfile)
  # Get the column names from the first row
  column_names = next(reader).keys()
  # Find and extract the LKAS_REQUEST column
  lkas_requests = [row['LKAS_REQUEST'] for row in reader]

rt_torque_last = 0

for i, torque_str in enumerate(lkas_requests):
  torque = int(torque_str)
  violation = rt_rate_limit_check(torque, rt_torque_last, 300)

  if violation:
    print("Violation @ {}".format(i))
    rt_rate_limit_check_debug(torque, rt_torque_last, 300)

  if i % 25 == 0:
    rt_torque_last = torque


timestamps = []
with open('/mnt/r/0000013b--a0429d8b1c_CAM_LKAS.csv', 'r') as csvfile:
  reader = csv.DictReader(csvfile)
  # Get the column names from the first row
  column_names = next(reader).keys()
  # Find and extract the LKAS_REQUEST column
  timestamps = [row['time'] for row in reader]


last_timestamp = 0.0
for i, tsstr in enumerate(timestamps):
  timestamp = float(tsstr)
  if (timestamp - last_timestamp) >= 0.03:
    print("violate at: {}".format(timestamp))
  last_timestamp = timestamp
