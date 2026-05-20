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
void err_fun(double *nom_x, double *delta_x, double *out_9016254589228640214) {
   out_9016254589228640214[0] = delta_x[0] + nom_x[0];
   out_9016254589228640214[1] = delta_x[1] + nom_x[1];
   out_9016254589228640214[2] = delta_x[2] + nom_x[2];
   out_9016254589228640214[3] = delta_x[3] + nom_x[3];
   out_9016254589228640214[4] = delta_x[4] + nom_x[4];
   out_9016254589228640214[5] = delta_x[5] + nom_x[5];
   out_9016254589228640214[6] = delta_x[6] + nom_x[6];
   out_9016254589228640214[7] = delta_x[7] + nom_x[7];
   out_9016254589228640214[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_4697937183045647733) {
   out_4697937183045647733[0] = -nom_x[0] + true_x[0];
   out_4697937183045647733[1] = -nom_x[1] + true_x[1];
   out_4697937183045647733[2] = -nom_x[2] + true_x[2];
   out_4697937183045647733[3] = -nom_x[3] + true_x[3];
   out_4697937183045647733[4] = -nom_x[4] + true_x[4];
   out_4697937183045647733[5] = -nom_x[5] + true_x[5];
   out_4697937183045647733[6] = -nom_x[6] + true_x[6];
   out_4697937183045647733[7] = -nom_x[7] + true_x[7];
   out_4697937183045647733[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_3400705068091435252) {
   out_3400705068091435252[0] = 1.0;
   out_3400705068091435252[1] = 0.0;
   out_3400705068091435252[2] = 0.0;
   out_3400705068091435252[3] = 0.0;
   out_3400705068091435252[4] = 0.0;
   out_3400705068091435252[5] = 0.0;
   out_3400705068091435252[6] = 0.0;
   out_3400705068091435252[7] = 0.0;
   out_3400705068091435252[8] = 0.0;
   out_3400705068091435252[9] = 0.0;
   out_3400705068091435252[10] = 1.0;
   out_3400705068091435252[11] = 0.0;
   out_3400705068091435252[12] = 0.0;
   out_3400705068091435252[13] = 0.0;
   out_3400705068091435252[14] = 0.0;
   out_3400705068091435252[15] = 0.0;
   out_3400705068091435252[16] = 0.0;
   out_3400705068091435252[17] = 0.0;
   out_3400705068091435252[18] = 0.0;
   out_3400705068091435252[19] = 0.0;
   out_3400705068091435252[20] = 1.0;
   out_3400705068091435252[21] = 0.0;
   out_3400705068091435252[22] = 0.0;
   out_3400705068091435252[23] = 0.0;
   out_3400705068091435252[24] = 0.0;
   out_3400705068091435252[25] = 0.0;
   out_3400705068091435252[26] = 0.0;
   out_3400705068091435252[27] = 0.0;
   out_3400705068091435252[28] = 0.0;
   out_3400705068091435252[29] = 0.0;
   out_3400705068091435252[30] = 1.0;
   out_3400705068091435252[31] = 0.0;
   out_3400705068091435252[32] = 0.0;
   out_3400705068091435252[33] = 0.0;
   out_3400705068091435252[34] = 0.0;
   out_3400705068091435252[35] = 0.0;
   out_3400705068091435252[36] = 0.0;
   out_3400705068091435252[37] = 0.0;
   out_3400705068091435252[38] = 0.0;
   out_3400705068091435252[39] = 0.0;
   out_3400705068091435252[40] = 1.0;
   out_3400705068091435252[41] = 0.0;
   out_3400705068091435252[42] = 0.0;
   out_3400705068091435252[43] = 0.0;
   out_3400705068091435252[44] = 0.0;
   out_3400705068091435252[45] = 0.0;
   out_3400705068091435252[46] = 0.0;
   out_3400705068091435252[47] = 0.0;
   out_3400705068091435252[48] = 0.0;
   out_3400705068091435252[49] = 0.0;
   out_3400705068091435252[50] = 1.0;
   out_3400705068091435252[51] = 0.0;
   out_3400705068091435252[52] = 0.0;
   out_3400705068091435252[53] = 0.0;
   out_3400705068091435252[54] = 0.0;
   out_3400705068091435252[55] = 0.0;
   out_3400705068091435252[56] = 0.0;
   out_3400705068091435252[57] = 0.0;
   out_3400705068091435252[58] = 0.0;
   out_3400705068091435252[59] = 0.0;
   out_3400705068091435252[60] = 1.0;
   out_3400705068091435252[61] = 0.0;
   out_3400705068091435252[62] = 0.0;
   out_3400705068091435252[63] = 0.0;
   out_3400705068091435252[64] = 0.0;
   out_3400705068091435252[65] = 0.0;
   out_3400705068091435252[66] = 0.0;
   out_3400705068091435252[67] = 0.0;
   out_3400705068091435252[68] = 0.0;
   out_3400705068091435252[69] = 0.0;
   out_3400705068091435252[70] = 1.0;
   out_3400705068091435252[71] = 0.0;
   out_3400705068091435252[72] = 0.0;
   out_3400705068091435252[73] = 0.0;
   out_3400705068091435252[74] = 0.0;
   out_3400705068091435252[75] = 0.0;
   out_3400705068091435252[76] = 0.0;
   out_3400705068091435252[77] = 0.0;
   out_3400705068091435252[78] = 0.0;
   out_3400705068091435252[79] = 0.0;
   out_3400705068091435252[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_6008551621691627816) {
   out_6008551621691627816[0] = state[0];
   out_6008551621691627816[1] = state[1];
   out_6008551621691627816[2] = state[2];
   out_6008551621691627816[3] = state[3];
   out_6008551621691627816[4] = state[4];
   out_6008551621691627816[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_6008551621691627816[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_6008551621691627816[7] = state[7];
   out_6008551621691627816[8] = state[8];
}
void F_fun(double *state, double dt, double *out_4522750073813051013) {
   out_4522750073813051013[0] = 1;
   out_4522750073813051013[1] = 0;
   out_4522750073813051013[2] = 0;
   out_4522750073813051013[3] = 0;
   out_4522750073813051013[4] = 0;
   out_4522750073813051013[5] = 0;
   out_4522750073813051013[6] = 0;
   out_4522750073813051013[7] = 0;
   out_4522750073813051013[8] = 0;
   out_4522750073813051013[9] = 0;
   out_4522750073813051013[10] = 1;
   out_4522750073813051013[11] = 0;
   out_4522750073813051013[12] = 0;
   out_4522750073813051013[13] = 0;
   out_4522750073813051013[14] = 0;
   out_4522750073813051013[15] = 0;
   out_4522750073813051013[16] = 0;
   out_4522750073813051013[17] = 0;
   out_4522750073813051013[18] = 0;
   out_4522750073813051013[19] = 0;
   out_4522750073813051013[20] = 1;
   out_4522750073813051013[21] = 0;
   out_4522750073813051013[22] = 0;
   out_4522750073813051013[23] = 0;
   out_4522750073813051013[24] = 0;
   out_4522750073813051013[25] = 0;
   out_4522750073813051013[26] = 0;
   out_4522750073813051013[27] = 0;
   out_4522750073813051013[28] = 0;
   out_4522750073813051013[29] = 0;
   out_4522750073813051013[30] = 1;
   out_4522750073813051013[31] = 0;
   out_4522750073813051013[32] = 0;
   out_4522750073813051013[33] = 0;
   out_4522750073813051013[34] = 0;
   out_4522750073813051013[35] = 0;
   out_4522750073813051013[36] = 0;
   out_4522750073813051013[37] = 0;
   out_4522750073813051013[38] = 0;
   out_4522750073813051013[39] = 0;
   out_4522750073813051013[40] = 1;
   out_4522750073813051013[41] = 0;
   out_4522750073813051013[42] = 0;
   out_4522750073813051013[43] = 0;
   out_4522750073813051013[44] = 0;
   out_4522750073813051013[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_4522750073813051013[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_4522750073813051013[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4522750073813051013[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_4522750073813051013[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_4522750073813051013[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_4522750073813051013[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_4522750073813051013[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_4522750073813051013[53] = -9.8100000000000005*dt;
   out_4522750073813051013[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_4522750073813051013[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_4522750073813051013[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4522750073813051013[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4522750073813051013[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_4522750073813051013[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_4522750073813051013[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_4522750073813051013[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_4522750073813051013[62] = 0;
   out_4522750073813051013[63] = 0;
   out_4522750073813051013[64] = 0;
   out_4522750073813051013[65] = 0;
   out_4522750073813051013[66] = 0;
   out_4522750073813051013[67] = 0;
   out_4522750073813051013[68] = 0;
   out_4522750073813051013[69] = 0;
   out_4522750073813051013[70] = 1;
   out_4522750073813051013[71] = 0;
   out_4522750073813051013[72] = 0;
   out_4522750073813051013[73] = 0;
   out_4522750073813051013[74] = 0;
   out_4522750073813051013[75] = 0;
   out_4522750073813051013[76] = 0;
   out_4522750073813051013[77] = 0;
   out_4522750073813051013[78] = 0;
   out_4522750073813051013[79] = 0;
   out_4522750073813051013[80] = 1;
}
void h_25(double *state, double *unused, double *out_6124024965867150436) {
   out_6124024965867150436[0] = state[6];
}
void H_25(double *state, double *unused, double *out_8195535911019304361) {
   out_8195535911019304361[0] = 0;
   out_8195535911019304361[1] = 0;
   out_8195535911019304361[2] = 0;
   out_8195535911019304361[3] = 0;
   out_8195535911019304361[4] = 0;
   out_8195535911019304361[5] = 0;
   out_8195535911019304361[6] = 1;
   out_8195535911019304361[7] = 0;
   out_8195535911019304361[8] = 0;
}
void h_24(double *state, double *unused, double *out_6288293339984186401) {
   out_6288293339984186401[0] = state[4];
   out_6288293339984186401[1] = state[5];
}
void H_24(double *state, double *unused, double *out_5939687835895486732) {
   out_5939687835895486732[0] = 0;
   out_5939687835895486732[1] = 0;
   out_5939687835895486732[2] = 0;
   out_5939687835895486732[3] = 0;
   out_5939687835895486732[4] = 1;
   out_5939687835895486732[5] = 0;
   out_5939687835895486732[6] = 0;
   out_5939687835895486732[7] = 0;
   out_5939687835895486732[8] = 0;
   out_5939687835895486732[9] = 0;
   out_5939687835895486732[10] = 0;
   out_5939687835895486732[11] = 0;
   out_5939687835895486732[12] = 0;
   out_5939687835895486732[13] = 0;
   out_5939687835895486732[14] = 1;
   out_5939687835895486732[15] = 0;
   out_5939687835895486732[16] = 0;
   out_5939687835895486732[17] = 0;
}
void h_30(double *state, double *unused, double *out_4441446457088351995) {
   out_4441446457088351995[0] = state[4];
}
void H_30(double *state, double *unused, double *out_5723511832562639057) {
   out_5723511832562639057[0] = 0;
   out_5723511832562639057[1] = 0;
   out_5723511832562639057[2] = 0;
   out_5723511832562639057[3] = 0;
   out_5723511832562639057[4] = 1;
   out_5723511832562639057[5] = 0;
   out_5723511832562639057[6] = 0;
   out_5723511832562639057[7] = 0;
   out_5723511832562639057[8] = 0;
}
void h_26(double *state, double *unused, double *out_3497936604186689560) {
   out_3497936604186689560[0] = state[7];
}
void H_26(double *state, double *unused, double *out_6509704843816191031) {
   out_6509704843816191031[0] = 0;
   out_6509704843816191031[1] = 0;
   out_6509704843816191031[2] = 0;
   out_6509704843816191031[3] = 0;
   out_6509704843816191031[4] = 0;
   out_6509704843816191031[5] = 0;
   out_6509704843816191031[6] = 0;
   out_6509704843816191031[7] = 1;
   out_6509704843816191031[8] = 0;
}
void h_27(double *state, double *unused, double *out_275016551546698710) {
   out_275016551546698710[0] = state[3];
}
void H_27(double *state, double *unused, double *out_3548748520762214146) {
   out_3548748520762214146[0] = 0;
   out_3548748520762214146[1] = 0;
   out_3548748520762214146[2] = 0;
   out_3548748520762214146[3] = 1;
   out_3548748520762214146[4] = 0;
   out_3548748520762214146[5] = 0;
   out_3548748520762214146[6] = 0;
   out_3548748520762214146[7] = 0;
   out_3548748520762214146[8] = 0;
}
void h_29(double *state, double *unused, double *out_7045851777897049646) {
   out_7045851777897049646[0] = state[1];
}
void H_29(double *state, double *unused, double *out_6233743176877031241) {
   out_6233743176877031241[0] = 0;
   out_6233743176877031241[1] = 1;
   out_6233743176877031241[2] = 0;
   out_6233743176877031241[3] = 0;
   out_6233743176877031241[4] = 0;
   out_6233743176877031241[5] = 0;
   out_6233743176877031241[6] = 0;
   out_6233743176877031241[7] = 0;
   out_6233743176877031241[8] = 0;
}
void h_28(double *state, double *unused, double *out_328299333129778807) {
   out_328299333129778807[0] = state[0];
}
void H_28(double *state, double *unused, double *out_1151344159807500667) {
   out_1151344159807500667[0] = 1;
   out_1151344159807500667[1] = 0;
   out_1151344159807500667[2] = 0;
   out_1151344159807500667[3] = 0;
   out_1151344159807500667[4] = 0;
   out_1151344159807500667[5] = 0;
   out_1151344159807500667[6] = 0;
   out_1151344159807500667[7] = 0;
   out_1151344159807500667[8] = 0;
}
void h_31(double *state, double *unused, double *out_8224415809563029316) {
   out_8224415809563029316[0] = state[8];
}
void H_31(double *state, double *unused, double *out_5883496741582839555) {
   out_5883496741582839555[0] = 0;
   out_5883496741582839555[1] = 0;
   out_5883496741582839555[2] = 0;
   out_5883496741582839555[3] = 0;
   out_5883496741582839555[4] = 0;
   out_5883496741582839555[5] = 0;
   out_5883496741582839555[6] = 0;
   out_5883496741582839555[7] = 0;
   out_5883496741582839555[8] = 1;
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
void car_err_fun(double *nom_x, double *delta_x, double *out_9016254589228640214) {
  err_fun(nom_x, delta_x, out_9016254589228640214);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4697937183045647733) {
  inv_err_fun(nom_x, true_x, out_4697937183045647733);
}
void car_H_mod_fun(double *state, double *out_3400705068091435252) {
  H_mod_fun(state, out_3400705068091435252);
}
void car_f_fun(double *state, double dt, double *out_6008551621691627816) {
  f_fun(state,  dt, out_6008551621691627816);
}
void car_F_fun(double *state, double dt, double *out_4522750073813051013) {
  F_fun(state,  dt, out_4522750073813051013);
}
void car_h_25(double *state, double *unused, double *out_6124024965867150436) {
  h_25(state, unused, out_6124024965867150436);
}
void car_H_25(double *state, double *unused, double *out_8195535911019304361) {
  H_25(state, unused, out_8195535911019304361);
}
void car_h_24(double *state, double *unused, double *out_6288293339984186401) {
  h_24(state, unused, out_6288293339984186401);
}
void car_H_24(double *state, double *unused, double *out_5939687835895486732) {
  H_24(state, unused, out_5939687835895486732);
}
void car_h_30(double *state, double *unused, double *out_4441446457088351995) {
  h_30(state, unused, out_4441446457088351995);
}
void car_H_30(double *state, double *unused, double *out_5723511832562639057) {
  H_30(state, unused, out_5723511832562639057);
}
void car_h_26(double *state, double *unused, double *out_3497936604186689560) {
  h_26(state, unused, out_3497936604186689560);
}
void car_H_26(double *state, double *unused, double *out_6509704843816191031) {
  H_26(state, unused, out_6509704843816191031);
}
void car_h_27(double *state, double *unused, double *out_275016551546698710) {
  h_27(state, unused, out_275016551546698710);
}
void car_H_27(double *state, double *unused, double *out_3548748520762214146) {
  H_27(state, unused, out_3548748520762214146);
}
void car_h_29(double *state, double *unused, double *out_7045851777897049646) {
  h_29(state, unused, out_7045851777897049646);
}
void car_H_29(double *state, double *unused, double *out_6233743176877031241) {
  H_29(state, unused, out_6233743176877031241);
}
void car_h_28(double *state, double *unused, double *out_328299333129778807) {
  h_28(state, unused, out_328299333129778807);
}
void car_H_28(double *state, double *unused, double *out_1151344159807500667) {
  H_28(state, unused, out_1151344159807500667);
}
void car_h_31(double *state, double *unused, double *out_8224415809563029316) {
  h_31(state, unused, out_8224415809563029316);
}
void car_H_31(double *state, double *unused, double *out_5883496741582839555) {
  H_31(state, unused, out_5883496741582839555);
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
