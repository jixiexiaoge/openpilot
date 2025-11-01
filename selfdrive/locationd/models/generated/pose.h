#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_7073107002944959153);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_786074686772967659);
void pose_H_mod_fun(double *state, double *out_697652429142743383);
void pose_f_fun(double *state, double dt, double *out_3774661386476087020);
void pose_F_fun(double *state, double dt, double *out_1884976403670791797);
void pose_h_4(double *state, double *unused, double *out_6884445182252047765);
void pose_H_4(double *state, double *unused, double *out_2639656693110238062);
void pose_h_10(double *state, double *unused, double *out_1633730535306024295);
void pose_H_10(double *state, double *unused, double *out_7172126253024250418);
void pose_h_13(double *state, double *unused, double *out_3626471298505881547);
void pose_H_13(double *state, double *unused, double *out_4970974515206462867);
void pose_h_14(double *state, double *unused, double *out_1559882867818069008);
void pose_H_14(double *state, double *unused, double *out_1323584163229246467);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}