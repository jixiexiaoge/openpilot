#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double mass;

void set_mass(double x){ mass = x;}

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_5858318062734378393) {
   out_5858318062734378393[0] = delta_x[0] + nom_x[0];
   out_5858318062734378393[1] = delta_x[1] + nom_x[1];
   out_5858318062734378393[2] = delta_x[2] + nom_x[2];
   out_5858318062734378393[3] = delta_x[3] + nom_x[3];
   out_5858318062734378393[4] = delta_x[4] + nom_x[4];
   out_5858318062734378393[5] = delta_x[5] + nom_x[5];
   out_5858318062734378393[6] = delta_x[6] + nom_x[6];
   out_5858318062734378393[7] = delta_x[7] + nom_x[7];
   out_5858318062734378393[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_1120011554021196593) {
   out_1120011554021196593[0] = -nom_x[0] + true_x[0];
   out_1120011554021196593[1] = -nom_x[1] + true_x[1];
   out_1120011554021196593[2] = -nom_x[2] + true_x[2];
   out_1120011554021196593[3] = -nom_x[3] + true_x[3];
   out_1120011554021196593[4] = -nom_x[4] + true_x[4];
   out_1120011554021196593[5] = -nom_x[5] + true_x[5];
   out_1120011554021196593[6] = -nom_x[6] + true_x[6];
   out_1120011554021196593[7] = -nom_x[7] + true_x[7];
   out_1120011554021196593[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_5913807702640896235) {
   out_5913807702640896235[0] = 1.0;
   out_5913807702640896235[1] = 0.0;
   out_5913807702640896235[2] = 0.0;
   out_5913807702640896235[3] = 0.0;
   out_5913807702640896235[4] = 0.0;
   out_5913807702640896235[5] = 0.0;
   out_5913807702640896235[6] = 0.0;
   out_5913807702640896235[7] = 0.0;
   out_5913807702640896235[8] = 0.0;
   out_5913807702640896235[9] = 0.0;
   out_5913807702640896235[10] = 1.0;
   out_5913807702640896235[11] = 0.0;
   out_5913807702640896235[12] = 0.0;
   out_5913807702640896235[13] = 0.0;
   out_5913807702640896235[14] = 0.0;
   out_5913807702640896235[15] = 0.0;
   out_5913807702640896235[16] = 0.0;
   out_5913807702640896235[17] = 0.0;
   out_5913807702640896235[18] = 0.0;
   out_5913807702640896235[19] = 0.0;
   out_5913807702640896235[20] = 1.0;
   out_5913807702640896235[21] = 0.0;
   out_5913807702640896235[22] = 0.0;
   out_5913807702640896235[23] = 0.0;
   out_5913807702640896235[24] = 0.0;
   out_5913807702640896235[25] = 0.0;
   out_5913807702640896235[26] = 0.0;
   out_5913807702640896235[27] = 0.0;
   out_5913807702640896235[28] = 0.0;
   out_5913807702640896235[29] = 0.0;
   out_5913807702640896235[30] = 1.0;
   out_5913807702640896235[31] = 0.0;
   out_5913807702640896235[32] = 0.0;
   out_5913807702640896235[33] = 0.0;
   out_5913807702640896235[34] = 0.0;
   out_5913807702640896235[35] = 0.0;
   out_5913807702640896235[36] = 0.0;
   out_5913807702640896235[37] = 0.0;
   out_5913807702640896235[38] = 0.0;
   out_5913807702640896235[39] = 0.0;
   out_5913807702640896235[40] = 1.0;
   out_5913807702640896235[41] = 0.0;
   out_5913807702640896235[42] = 0.0;
   out_5913807702640896235[43] = 0.0;
   out_5913807702640896235[44] = 0.0;
   out_5913807702640896235[45] = 0.0;
   out_5913807702640896235[46] = 0.0;
   out_5913807702640896235[47] = 0.0;
   out_5913807702640896235[48] = 0.0;
   out_5913807702640896235[49] = 0.0;
   out_5913807702640896235[50] = 1.0;
   out_5913807702640896235[51] = 0.0;
   out_5913807702640896235[52] = 0.0;
   out_5913807702640896235[53] = 0.0;
   out_5913807702640896235[54] = 0.0;
   out_5913807702640896235[55] = 0.0;
   out_5913807702640896235[56] = 0.0;
   out_5913807702640896235[57] = 0.0;
   out_5913807702640896235[58] = 0.0;
   out_5913807702640896235[59] = 0.0;
   out_5913807702640896235[60] = 1.0;
   out_5913807702640896235[61] = 0.0;
   out_5913807702640896235[62] = 0.0;
   out_5913807702640896235[63] = 0.0;
   out_5913807702640896235[64] = 0.0;
   out_5913807702640896235[65] = 0.0;
   out_5913807702640896235[66] = 0.0;
   out_5913807702640896235[67] = 0.0;
   out_5913807702640896235[68] = 0.0;
   out_5913807702640896235[69] = 0.0;
   out_5913807702640896235[70] = 1.0;
   out_5913807702640896235[71] = 0.0;
   out_5913807702640896235[72] = 0.0;
   out_5913807702640896235[73] = 0.0;
   out_5913807702640896235[74] = 0.0;
   out_5913807702640896235[75] = 0.0;
   out_5913807702640896235[76] = 0.0;
   out_5913807702640896235[77] = 0.0;
   out_5913807702640896235[78] = 0.0;
   out_5913807702640896235[79] = 0.0;
   out_5913807702640896235[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_7958033707240532768) {
   out_7958033707240532768[0] = state[0];
   out_7958033707240532768[1] = state[1];
   out_7958033707240532768[2] = state[2];
   out_7958033707240532768[3] = state[3];
   out_7958033707240532768[4] = state[4];
   out_7958033707240532768[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8000000000000007*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_7958033707240532768[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_7958033707240532768[7] = state[7];
   out_7958033707240532768[8] = state[8];
}
void F_fun(double *state, double dt, double *out_8168186131598064680) {
   out_8168186131598064680[0] = 1;
   out_8168186131598064680[1] = 0;
   out_8168186131598064680[2] = 0;
   out_8168186131598064680[3] = 0;
   out_8168186131598064680[4] = 0;
   out_8168186131598064680[5] = 0;
   out_8168186131598064680[6] = 0;
   out_8168186131598064680[7] = 0;
   out_8168186131598064680[8] = 0;
   out_8168186131598064680[9] = 0;
   out_8168186131598064680[10] = 1;
   out_8168186131598064680[11] = 0;
   out_8168186131598064680[12] = 0;
   out_8168186131598064680[13] = 0;
   out_8168186131598064680[14] = 0;
   out_8168186131598064680[15] = 0;
   out_8168186131598064680[16] = 0;
   out_8168186131598064680[17] = 0;
   out_8168186131598064680[18] = 0;
   out_8168186131598064680[19] = 0;
   out_8168186131598064680[20] = 1;
   out_8168186131598064680[21] = 0;
   out_8168186131598064680[22] = 0;
   out_8168186131598064680[23] = 0;
   out_8168186131598064680[24] = 0;
   out_8168186131598064680[25] = 0;
   out_8168186131598064680[26] = 0;
   out_8168186131598064680[27] = 0;
   out_8168186131598064680[28] = 0;
   out_8168186131598064680[29] = 0;
   out_8168186131598064680[30] = 1;
   out_8168186131598064680[31] = 0;
   out_8168186131598064680[32] = 0;
   out_8168186131598064680[33] = 0;
   out_8168186131598064680[34] = 0;
   out_8168186131598064680[35] = 0;
   out_8168186131598064680[36] = 0;
   out_8168186131598064680[37] = 0;
   out_8168186131598064680[38] = 0;
   out_8168186131598064680[39] = 0;
   out_8168186131598064680[40] = 1;
   out_8168186131598064680[41] = 0;
   out_8168186131598064680[42] = 0;
   out_8168186131598064680[43] = 0;
   out_8168186131598064680[44] = 0;
   out_8168186131598064680[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_8168186131598064680[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_8168186131598064680[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8168186131598064680[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_8168186131598064680[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_8168186131598064680[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_8168186131598064680[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_8168186131598064680[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_8168186131598064680[53] = -9.8000000000000007*dt;
   out_8168186131598064680[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_8168186131598064680[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_8168186131598064680[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8168186131598064680[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8168186131598064680[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_8168186131598064680[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_8168186131598064680[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_8168186131598064680[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_8168186131598064680[62] = 0;
   out_8168186131598064680[63] = 0;
   out_8168186131598064680[64] = 0;
   out_8168186131598064680[65] = 0;
   out_8168186131598064680[66] = 0;
   out_8168186131598064680[67] = 0;
   out_8168186131598064680[68] = 0;
   out_8168186131598064680[69] = 0;
   out_8168186131598064680[70] = 1;
   out_8168186131598064680[71] = 0;
   out_8168186131598064680[72] = 0;
   out_8168186131598064680[73] = 0;
   out_8168186131598064680[74] = 0;
   out_8168186131598064680[75] = 0;
   out_8168186131598064680[76] = 0;
   out_8168186131598064680[77] = 0;
   out_8168186131598064680[78] = 0;
   out_8168186131598064680[79] = 0;
   out_8168186131598064680[80] = 1;
}
void h_25(double *state, double *unused, double *out_2750561240669363395) {
   out_2750561240669363395[0] = state[6];
}
void H_25(double *state, double *unused, double *out_2390827052651404558) {
   out_2390827052651404558[0] = 0;
   out_2390827052651404558[1] = 0;
   out_2390827052651404558[2] = 0;
   out_2390827052651404558[3] = 0;
   out_2390827052651404558[4] = 0;
   out_2390827052651404558[5] = 0;
   out_2390827052651404558[6] = 1;
   out_2390827052651404558[7] = 0;
   out_2390827052651404558[8] = 0;
}
void h_24(double *state, double *unused, double *out_2442631200344176539) {
   out_2442631200344176539[0] = state[4];
   out_2442631200344176539[1] = state[5];
}
void H_24(double *state, double *unused, double *out_1167098546150918578) {
   out_1167098546150918578[0] = 0;
   out_1167098546150918578[1] = 0;
   out_1167098546150918578[2] = 0;
   out_1167098546150918578[3] = 0;
   out_1167098546150918578[4] = 1;
   out_1167098546150918578[5] = 0;
   out_1167098546150918578[6] = 0;
   out_1167098546150918578[7] = 0;
   out_1167098546150918578[8] = 0;
   out_1167098546150918578[9] = 0;
   out_1167098546150918578[10] = 0;
   out_1167098546150918578[11] = 0;
   out_1167098546150918578[12] = 0;
   out_1167098546150918578[13] = 0;
   out_1167098546150918578[14] = 1;
   out_1167098546150918578[15] = 0;
   out_1167098546150918578[16] = 0;
   out_1167098546150918578[17] = 0;
}
void h_30(double *state, double *unused, double *out_8925347606689837285) {
   out_8925347606689837285[0] = state[4];
}
void H_30(double *state, double *unused, double *out_127505905855844069) {
   out_127505905855844069[0] = 0;
   out_127505905855844069[1] = 0;
   out_127505905855844069[2] = 0;
   out_127505905855844069[3] = 0;
   out_127505905855844069[4] = 1;
   out_127505905855844069[5] = 0;
   out_127505905855844069[6] = 0;
   out_127505905855844069[7] = 0;
   out_127505905855844069[8] = 0;
}
void h_26(double *state, double *unused, double *out_3923674339028991640) {
   out_3923674339028991640[0] = state[7];
}
void H_26(double *state, double *unused, double *out_6132330371525460782) {
   out_6132330371525460782[0] = 0;
   out_6132330371525460782[1] = 0;
   out_6132330371525460782[2] = 0;
   out_6132330371525460782[3] = 0;
   out_6132330371525460782[4] = 0;
   out_6132330371525460782[5] = 0;
   out_6132330371525460782[6] = 0;
   out_6132330371525460782[7] = 1;
   out_6132330371525460782[8] = 0;
}
void h_27(double *state, double *unused, double *out_2251112026991482250) {
   out_2251112026991482250[0] = state[3];
}
void H_27(double *state, double *unused, double *out_2351099977039787286) {
   out_2351099977039787286[0] = 0;
   out_2351099977039787286[1] = 0;
   out_2351099977039787286[2] = 0;
   out_2351099977039787286[3] = 1;
   out_2351099977039787286[4] = 0;
   out_2351099977039787286[5] = 0;
   out_2351099977039787286[6] = 0;
   out_2351099977039787286[7] = 0;
   out_2351099977039787286[8] = 0;
}
void h_29(double *state, double *unused, double *out_6112795503419983902) {
   out_6112795503419983902[0] = state[1];
}
void H_29(double *state, double *unused, double *out_637737250170236253) {
   out_637737250170236253[0] = 0;
   out_637737250170236253[1] = 1;
   out_637737250170236253[2] = 0;
   out_637737250170236253[3] = 0;
   out_637737250170236253[4] = 0;
   out_637737250170236253[5] = 0;
   out_637737250170236253[6] = 0;
   out_637737250170236253[7] = 0;
   out_637737250170236253[8] = 0;
}
void h_28(double *state, double *unused, double *out_1307602174089819815) {
   out_1307602174089819815[0] = state[0];
}
void H_28(double *state, double *unused, double *out_4444661766899294321) {
   out_4444661766899294321[0] = 1;
   out_4444661766899294321[1] = 0;
   out_4444661766899294321[2] = 0;
   out_4444661766899294321[3] = 0;
   out_4444661766899294321[4] = 0;
   out_4444661766899294321[5] = 0;
   out_4444661766899294321[6] = 0;
   out_4444661766899294321[7] = 0;
   out_4444661766899294321[8] = 0;
}
void h_31(double *state, double *unused, double *out_5012704016151309046) {
   out_5012704016151309046[0] = state[8];
}
void H_31(double *state, double *unused, double *out_2360181090774444130) {
   out_2360181090774444130[0] = 0;
   out_2360181090774444130[1] = 0;
   out_2360181090774444130[2] = 0;
   out_2360181090774444130[3] = 0;
   out_2360181090774444130[4] = 0;
   out_2360181090774444130[5] = 0;
   out_2360181090774444130[6] = 0;
   out_2360181090774444130[7] = 0;
   out_2360181090774444130[8] = 1;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_5858318062734378393) {
  err_fun(nom_x, delta_x, out_5858318062734378393);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_1120011554021196593) {
  inv_err_fun(nom_x, true_x, out_1120011554021196593);
}
void car_H_mod_fun(double *state, double *out_5913807702640896235) {
  H_mod_fun(state, out_5913807702640896235);
}
void car_f_fun(double *state, double dt, double *out_7958033707240532768) {
  f_fun(state,  dt, out_7958033707240532768);
}
void car_F_fun(double *state, double dt, double *out_8168186131598064680) {
  F_fun(state,  dt, out_8168186131598064680);
}
void car_h_25(double *state, double *unused, double *out_2750561240669363395) {
  h_25(state, unused, out_2750561240669363395);
}
void car_H_25(double *state, double *unused, double *out_2390827052651404558) {
  H_25(state, unused, out_2390827052651404558);
}
void car_h_24(double *state, double *unused, double *out_2442631200344176539) {
  h_24(state, unused, out_2442631200344176539);
}
void car_H_24(double *state, double *unused, double *out_1167098546150918578) {
  H_24(state, unused, out_1167098546150918578);
}
void car_h_30(double *state, double *unused, double *out_8925347606689837285) {
  h_30(state, unused, out_8925347606689837285);
}
void car_H_30(double *state, double *unused, double *out_127505905855844069) {
  H_30(state, unused, out_127505905855844069);
}
void car_h_26(double *state, double *unused, double *out_3923674339028991640) {
  h_26(state, unused, out_3923674339028991640);
}
void car_H_26(double *state, double *unused, double *out_6132330371525460782) {
  H_26(state, unused, out_6132330371525460782);
}
void car_h_27(double *state, double *unused, double *out_2251112026991482250) {
  h_27(state, unused, out_2251112026991482250);
}
void car_H_27(double *state, double *unused, double *out_2351099977039787286) {
  H_27(state, unused, out_2351099977039787286);
}
void car_h_29(double *state, double *unused, double *out_6112795503419983902) {
  h_29(state, unused, out_6112795503419983902);
}
void car_H_29(double *state, double *unused, double *out_637737250170236253) {
  H_29(state, unused, out_637737250170236253);
}
void car_h_28(double *state, double *unused, double *out_1307602174089819815) {
  h_28(state, unused, out_1307602174089819815);
}
void car_H_28(double *state, double *unused, double *out_4444661766899294321) {
  H_28(state, unused, out_4444661766899294321);
}
void car_h_31(double *state, double *unused, double *out_5012704016151309046) {
  h_31(state, unused, out_5012704016151309046);
}
void car_H_31(double *state, double *unused, double *out_2360181090774444130) {
  H_31(state, unused, out_2360181090774444130);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_mass(double x) {
  set_mass(x);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "mass", car_set_mass },
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
