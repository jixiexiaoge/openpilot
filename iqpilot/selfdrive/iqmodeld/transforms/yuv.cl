/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
*/
#define UV_SIZE ((TRANSFORMED_WIDTH/2)*(TRANSFORMED_HEIGHT/2))

__kernel void packLumaHalves(__global uchar8 const * const in_luma,
                             __global uchar * out_frame,
                             int out_offset)
{
  const int gid = get_global_id(0);
  const int output_index_start = gid * 8;
  const int row = output_index_start / TRANSFORMED_WIDTH;
  const int col = output_index_start % TRANSFORMED_WIDTH;
  const uchar8 luma_block = in_luma[gid];

  __global uchar *top_or_left;
  __global uchar *bottom_or_right;
  if ((row & 1) == 0) {
    top_or_left = out_frame + out_offset;
    bottom_or_right = out_frame + out_offset + UV_SIZE * 2;
  } else {
    top_or_left = out_frame + out_offset + UV_SIZE;
    bottom_or_right = out_frame + out_offset + UV_SIZE * 3;
  }

  const int row_stride = (row / 2) * (TRANSFORMED_WIDTH / 2) + col / 2;
  vstore4(luma_block.s0246, 0, top_or_left + row_stride);
  vstore4(luma_block.s1357, 0, bottom_or_right + row_stride);
}

__kernel void packChromaPlane(__global uchar8 const * const in_plane,
                              __global uchar8 * out_frame,
                              int out_offset)
{
  const int gid = get_global_id(0);
  out_frame[gid + out_offset / 8] = in_plane[gid];
}

__kernel void copyPlaneBytes(__global uchar8 * in_plane,
                             __global uchar8 * out_plane,
                             int in_offset,
                             int out_offset)
{
  const int gid = get_global_id(0);
  out_plane[gid + out_offset / 8] = in_plane[gid + in_offset / 8];
}
