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
void car_err_fun(double *nom_x, double *delta_x, double *out_9016254589228640214);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4697937183045647733);
void car_H_mod_fun(double *state, double *out_3400705068091435252);
void car_f_fun(double *state, double dt, double *out_6008551621691627816);
void car_F_fun(double *state, double dt, double *out_4522750073813051013);
void car_h_25(double *state, double *unused, double *out_6124024965867150436);
void car_H_25(double *state, double *unused, double *out_8195535911019304361);
void car_h_24(double *state, double *unused, double *out_6288293339984186401);
void car_H_24(double *state, double *unused, double *out_5939687835895486732);
void car_h_30(double *state, double *unused, double *out_4441446457088351995);
void car_H_30(double *state, double *unused, double *out_5723511832562639057);
void car_h_26(double *state, double *unused, double *out_3497936604186689560);
void car_H_26(double *state, double *unused, double *out_6509704843816191031);
void car_h_27(double *state, double *unused, double *out_275016551546698710);
void car_H_27(double *state, double *unused, double *out_3548748520762214146);
void car_h_29(double *state, double *unused, double *out_7045851777897049646);
void car_H_29(double *state, double *unused, double *out_6233743176877031241);
void car_h_28(double *state, double *unused, double *out_328299333129778807);
void car_H_28(double *state, double *unused, double *out_1151344159807500667);
void car_h_31(double *state, double *unused, double *out_8224415809563029316);
void car_H_31(double *state, double *unused, double *out_5883496741582839555);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}