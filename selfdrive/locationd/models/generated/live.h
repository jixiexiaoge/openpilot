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
void live_H(double *in_vec, double *out_3527519890029080135);
void live_err_fun(double *nom_x, double *delta_x, double *out_4778170452105657787);
void live_inv_err_fun(double *nom_x, double *true_x, double *out_7862660130434369918);
void live_H_mod_fun(double *state, double *out_2570725668637353106);
void live_f_fun(double *state, double dt, double *out_584279180406083929);
void live_F_fun(double *state, double dt, double *out_3494481705773101203);
void live_h_4(double *state, double *unused, double *out_1240966830221045020);
void live_H_4(double *state, double *unused, double *out_8558864835306308373);
void live_h_9(double *state, double *unused, double *out_879567894458718227);
void live_H_9(double *state, double *unused, double *out_2600660303138795773);
void live_h_10(double *state, double *unused, double *out_8093442712549843067);
void live_H_10(double *state, double *unused, double *out_4565686567218081543);
void live_h_12(double *state, double *unused, double *out_3519532262786168854);
void live_H_12(double *state, double *unused, double *out_2177606458263575377);
void live_h_35(double *state, double *unused, double *out_1790737629929127197);
void live_H_35(double *state, double *unused, double *out_524812107604220958);
void live_h_32(double *state, double *unused, double *out_228792308309375465);
void live_H_32(double *state, double *unused, double *out_3816192668128885930);
void live_h_13(double *state, double *unused, double *out_2827519061539561519);
void live_H_13(double *state, double *unused, double *out_5540348075104815700);
void live_h_14(double *state, double *unused, double *out_879567894458718227);
void live_H_14(double *state, double *unused, double *out_2600660303138795773);
void live_h_33(double *state, double *unused, double *out_8119509662710566406);
void live_H_33(double *state, double *unused, double *out_3675369112243078562);
void live_predict(double *in_x, double *in_P, double *in_Q, double dt);
}