#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_2229253592220784796);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_8758496889644692282);
void car_H_mod_fun(double *state, double *out_8711803353026157689);
void car_f_fun(double *state, double dt, double *out_4199840031629318215);
void car_F_fun(double *state, double dt, double *out_1980461025500558356);
void car_h_25(double *state, double *unused, double *out_3619972370828301387);
void car_H_25(double *state, double *unused, double *out_5188754714380792541);
void car_h_24(double *state, double *unused, double *out_3935146291291123111);
void car_H_24(double *state, double *unused, double *out_8746680313183115677);
void car_h_30(double *state, double *unused, double *out_4876688310435438605);
void car_H_30(double *state, double *unused, double *out_7707087672888041168);
void car_h_26(double *state, double *unused, double *out_2897076540518924503);
void car_H_26(double *state, double *unused, double *out_8493280684141593142);
void car_h_27(double *state, double *unused, double *out_6030462238615253089);
void car_H_27(double *state, double *unused, double *out_8516062329637567231);
void car_h_29(double *state, double *unused, double *out_7171014245860263865);
void car_H_29(double *state, double *unused, double *out_8217319017202433352);
void car_h_28(double *state, double *unused, double *out_4981138400665597714);
void car_H_28(double *state, double *unused, double *out_3134920000132902778);
void car_h_31(double *state, double *unused, double *out_4261300279925747798);
void car_H_31(double *state, double *unused, double *out_6181314108816941822);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}