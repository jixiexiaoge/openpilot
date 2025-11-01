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
void car_err_fun(double *nom_x, double *delta_x, double *out_4487415744468818219);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4654232448943638459);
void car_H_mod_fun(double *state, double *out_7206443341681641242);
void car_f_fun(double *state, double dt, double *out_4421835825047252240);
void car_F_fun(double *state, double dt, double *out_3196915420679384976);
void car_h_25(double *state, double *unused, double *out_7861803971085835388);
void car_H_25(double *state, double *unused, double *out_714894691292218563);
void car_h_24(double *state, double *unused, double *out_6157903483363920680);
void car_H_24(double *state, double *unused, double *out_4031614635674290471);
void car_h_30(double *state, double *unused, double *out_1641426788238821419);
void car_H_30(double *state, double *unused, double *out_3233227649799467190);
void car_h_26(double *state, double *unused, double *out_6643100055899667064);
void car_H_26(double *state, double *unused, double *out_3026608627581837661);
void car_h_27(double *state, double *unused, double *out_2860130703424989743);
void car_H_27(double *state, double *unused, double *out_1589207567651446418);
void car_h_29(double *state, double *unused, double *out_2584936641140483854);
void car_H_29(double *state, double *unused, double *out_3302570294520997451);
void car_h_28(double *state, double *unused, double *out_2256814818748512226);
void car_H_28(double *state, double *unused, double *out_1338940022955671200);
void car_h_31(double *state, double *unused, double *out_7637214112268231267);
void car_H_31(double *state, double *unused, double *out_3652816729815189137);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}