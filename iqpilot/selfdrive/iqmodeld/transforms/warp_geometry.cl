/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#define INTER_BITS 5
#define INTER_TAB_SIZE (1 << INTER_BITS)
#define INTER_REMAP_COEF_BITS 15
#define INTER_REMAP_COEF_SCALE (1 << INTER_REMAP_COEF_BITS)

__kernel void projectPlaneBilinear(__global const uchar * src,
                                   int src_row_stride, int src_px_stride, int src_offset, int src_rows, int src_cols,
                                   __global uchar * dst,
                                   int dst_row_stride, int dst_offset, int dst_rows, int dst_cols,
                                   __constant float * M)
{
  int dx = get_global_id(0);
  int dy = get_global_id(1);

  if (dx < dst_cols && dy < dst_rows) {
    float x0 = M[0] * dx + M[1] * dy + M[2];
    float y0 = M[3] * dx + M[4] * dy + M[5];
    float w = M[6] * dx + M[7] * dy + M[8];
    w = w != 0.0f ? INTER_TAB_SIZE / w : 0.0f;

    int x = rint(x0 * w);
    int y = rint(y0 * w);
    short sx = convert_short_sat(x >> INTER_BITS);
    short sy = convert_short_sat(y >> INTER_BITS);
    short min_col = (short)0;
    short max_col = convert_short_sat(src_cols - 1);
    short min_row = (short)0;
    short max_row = convert_short_sat(src_rows - 1);

    short sx_clamp = clamp(sx, min_col, max_col);
    short sx_p1_clamp = clamp((short)(sx + 1), min_col, max_col);
    short sy_clamp = clamp(sy, min_row, max_row);
    short sy_p1_clamp = clamp((short)(sy + 1), min_row, max_row);

    int top_left = convert_int(src[mad24(sy_clamp, src_row_stride, src_offset + sx_clamp * src_px_stride)]);
    int top_right = convert_int(src[mad24(sy_clamp, src_row_stride, src_offset + sx_p1_clamp * src_px_stride)]);
    int bottom_left = convert_int(src[mad24(sy_p1_clamp, src_row_stride, src_offset + sx_clamp * src_px_stride)]);
    int bottom_right = convert_int(src[mad24(sy_p1_clamp, src_row_stride, src_offset + sx_p1_clamp * src_px_stride)]);

    short ay = (short)(y & (INTER_TAB_SIZE - 1));
    short ax = (short)(x & (INTER_TAB_SIZE - 1));
    float taby = 1.f / INTER_TAB_SIZE * ay;
    float tabx = 1.f / INTER_TAB_SIZE * ax;

    int coeff0 = convert_short_sat_rte((1.0f - taby) * (1.0f - tabx) * INTER_REMAP_COEF_SCALE);
    int coeff1 = convert_short_sat_rte((1.0f - taby) * tabx * INTER_REMAP_COEF_SCALE);
    int coeff2 = convert_short_sat_rte(taby * (1.0f - tabx) * INTER_REMAP_COEF_SCALE);
    int coeff3 = convert_short_sat_rte(taby * tabx * INTER_REMAP_COEF_SCALE);

    int blended = top_left * coeff0 + top_right * coeff1 + bottom_left * coeff2 + bottom_right * coeff3;
    int dst_index = mad24(dy, dst_row_stride, dst_offset + dx);
    dst[dst_index] = convert_uchar_sat((blended + (1 << (INTER_REMAP_COEF_BITS - 1))) >> INTER_REMAP_COEF_BITS);
  }
}
