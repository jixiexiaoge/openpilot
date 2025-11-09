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
void live_H(double *in_vec, double *out_6391744612992699665);
void live_err_fun(double *nom_x, double *delta_x, double *out_4370336855068244963);
void live_inv_err_fun(double *nom_x, double *true_x, double *out_1979710598727292215);
void live_H_mod_fun(double *state, double *out_7957641107850769609);
void live_f_fun(double *state, double dt, double *out_1380903670696870859);
void live_F_fun(double *state, double dt, double *out_6491840944087407978);
void live_h_4(double *state, double *unused, double *out_8839260273042393167);
void live_H_4(double *state, double *unused, double *out_4335329159080063812);
void live_h_9(double *state, double *unused, double *out_5314044586629085300);
void live_H_9(double *state, double *unused, double *out_7224190711360143154);
void live_h_10(double *state, double *unused, double *out_2031541365128224368);
void live_H_10(double *state, double *unused, double *out_7592821323481883133);
void live_h_12(double *state, double *unused, double *out_6189720006213956232);
void live_H_12(double *state, double *unused, double *out_6444286600947037312);
void live_h_35(double *state, double *unused, double *out_4149760098500831618);
void live_H_35(double *state, double *unused, double *out_3698723568622023603);
void live_h_32(double *state, double *unused, double *out_5323436800250228517);
void live_H_32(double *state, double *unused, double *out_2102580803585588955);
void live_h_13(double *state, double *unused, double *out_3455248493936798835);
void live_H_13(double *state, double *unused, double *out_4435412411480511170);
void live_h_14(double *state, double *unused, double *out_5314044586629085300);
void live_H_14(double *state, double *unused, double *out_7224190711360143154);
void live_h_33(double *state, double *unused, double *out_6034162314148674616);
void live_H_33(double *state, double *unused, double *out_548166563983165999);
void live_predict(double *in_x, double *in_P, double *in_Q, double dt);
}