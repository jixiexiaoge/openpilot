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
void car_err_fun(double *nom_x, double *delta_x, double *out_5301818556243384592);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_874937939219484055);
void car_H_mod_fun(double *state, double *out_9027911626465654580);
void car_f_fun(double *state, double dt, double *out_3418720271407920669);
void car_F_fun(double *state, double dt, double *out_4010466285712197699);
void car_h_25(double *state, double *unused, double *out_4002942019690782198);
void car_H_25(double *state, double *unused, double *out_4233080783537785471);
void car_h_24(double *state, double *unused, double *out_5158854995226358742);
void car_H_24(double *state, double *unused, double *out_2060431184532285905);
void car_h_30(double *state, double *unused, double *out_2217435163156231771);
void car_H_30(double *state, double *unused, double *out_6751413742045034098);
void car_h_26(double *state, double *unused, double *out_8616476680570080917);
void car_H_26(double *state, double *unused, double *out_491577464663729247);
void car_h_27(double *state, double *unused, double *out_998731247970063447);
void car_H_27(double *state, double *unused, double *out_4576650430244609187);
void car_h_29(double *state, double *unused, double *out_1273925310254569336);
void car_H_29(double *state, double *unused, double *out_7261645086359426282);
void car_h_28(double *state, double *unused, double *out_1605674072838634204);
void car_H_28(double *state, double *unused, double *out_2179246069289895708);
void car_h_31(double *state, double *unused, double *out_7640391547944804548);
void car_H_31(double *state, double *unused, double *out_134630637569622229);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}