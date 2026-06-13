#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "quirc.h"

int iqpilot_decode_qr_gray(const uint8_t *gray, int width, int height, char *out, int out_len) {
  if (gray == NULL || out == NULL || out_len <= 0 || width <= 0 || height <= 0) {
    return -1;
  }

  struct quirc *qr = quirc_new();
  if (qr == NULL) {
    return -2;
  }

  if (quirc_resize(qr, width, height) < 0) {
    quirc_destroy(qr);
    return -3;
  }

  int qw = 0, qh = 0;
  uint8_t *image = quirc_begin(qr, &qw, &qh);
  if (image == NULL || qw != width || qh != height) {
    quirc_destroy(qr);
    return -4;
  }

  memcpy(image, gray, (size_t)(width * height));
  quirc_end(qr);

  int total = quirc_count(qr);
  int decoded_count = 0;
  int write_pos = 0;

  for (int i = 0; i < total; ++i) {
    struct quirc_code code;
    struct quirc_data data;
    quirc_extract(qr, i, &code);

    if (quirc_decode(&code, &data) != QUIRC_SUCCESS || data.payload_len == 0) {
      continue;
    }

    if (write_pos > 0) {
      if (write_pos + 1 >= out_len) {
        break;
      }
      out[write_pos++] = '\n';
    }

    int copy_len = data.payload_len;
    if (copy_len > out_len - write_pos - 1) {
      copy_len = out_len - write_pos - 1;
    }
    if (copy_len <= 0) {
      break;
    }

    memcpy(out + write_pos, data.payload, (size_t)copy_len);
    write_pos += copy_len;
    decoded_count++;
  }

  out[write_pos] = '\0';
  quirc_destroy(qr);
  return decoded_count;
}
