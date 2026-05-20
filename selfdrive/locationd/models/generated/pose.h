#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_8003140298768285729);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_1585615485350566282);
void pose_H_mod_fun(double *state, double *out_6339119660772184359);
void pose_f_fun(double *state, double dt, double *out_8814312762725343776);
void pose_F_fun(double *state, double dt, double *out_3190594136445709051);
void pose_h_4(double *state, double *unused, double *out_1691227165262288451);
void pose_H_4(double *state, double *unused, double *out_8335817203093459685);
void pose_h_10(double *state, double *unused, double *out_2403183795320234102);
void pose_H_10(double *state, double *unused, double *out_1717861992756499185);
void pose_h_13(double *state, double *unused, double *out_5614817628718297389);
void pose_H_13(double *state, double *unused, double *out_5123543377761126884);
void pose_h_14(double *state, double *unused, double *out_1705218014260526043);
void pose_H_14(double *state, double *unused, double *out_7028138438320719635);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}