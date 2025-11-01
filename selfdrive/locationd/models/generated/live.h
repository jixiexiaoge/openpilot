#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void live_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_9(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_12(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_35(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_32(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_update_33(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void live_H(double *in_vec, double *out_260684114864648054);
void live_err_fun(double *nom_x, double *delta_x, double *out_646680912810555239);
void live_inv_err_fun(double *nom_x, double *true_x, double *out_3456649268712699355);
void live_H_mod_fun(double *state, double *out_5388483110772843137);
void live_f_fun(double *state, double dt, double *out_1841217717090853512);
void live_F_fun(double *state, double dt, double *out_5169098944319908009);
void live_h_4(double *state, double *unused, double *out_5803376367265116943);
void live_H_4(double *state, double *unused, double *out_4576061889494230116);
void live_h_9(double *state, double *unused, double *out_281108824852909032);
void live_H_9(double *state, double *unused, double *out_4817251536123820761);
void live_h_10(double *state, double *unused, double *out_4357629749381728714);
void live_H_10(double *state, double *unused, double *out_6042457761732970587);
void live_h_12(double *state, double *unused, double *out_2997417612276614552);
void live_H_12(double *state, double *unused, double *out_8851225776183359705);
void live_h_35(double *state, double *unused, double *out_6027349610005213946);
void live_H_35(double *state, double *unused, double *out_6105662743858345996);
void live_h_32(double *state, double *unused, double *out_5891333279716061506);
void live_H_32(double *state, double *unused, double *out_4164824406525337195);
void live_h_13(double *state, double *unused, double *out_8419927557870810010);
void live_H_13(double *state, double *unused, double *out_6004411560565166518);
void live_h_14(double *state, double *unused, double *out_281108824852909032);
void live_H_14(double *state, double *unused, double *out_4817251536123820761);
void live_h_33(double *state, double *unused, double *out_2476946805241971028);
void live_H_33(double *state, double *unused, double *out_2955105739219488392);
void live_predict(double *in_x, double *in_P, double *in_Q, double dt);
}