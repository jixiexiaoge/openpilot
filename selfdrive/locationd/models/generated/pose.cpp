#include "pose.h"

namespace {
#define DIM 18
#define EDIM 18
#define MEDIM 18
typedef void (*Hfun)(double *, double *, double *);
const static double MAHA_THRESH_4 = 7.814727903251177;
const static double MAHA_THRESH_10 = 7.814727903251177;
const static double MAHA_THRESH_13 = 7.814727903251177;
const static double MAHA_THRESH_14 = 7.814727903251177;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_8003140298768285729) {
   out_8003140298768285729[0] = delta_x[0] + nom_x[0];
   out_8003140298768285729[1] = delta_x[1] + nom_x[1];
   out_8003140298768285729[2] = delta_x[2] + nom_x[2];
   out_8003140298768285729[3] = delta_x[3] + nom_x[3];
   out_8003140298768285729[4] = delta_x[4] + nom_x[4];
   out_8003140298768285729[5] = delta_x[5] + nom_x[5];
   out_8003140298768285729[6] = delta_x[6] + nom_x[6];
   out_8003140298768285729[7] = delta_x[7] + nom_x[7];
   out_8003140298768285729[8] = delta_x[8] + nom_x[8];
   out_8003140298768285729[9] = delta_x[9] + nom_x[9];
   out_8003140298768285729[10] = delta_x[10] + nom_x[10];
   out_8003140298768285729[11] = delta_x[11] + nom_x[11];
   out_8003140298768285729[12] = delta_x[12] + nom_x[12];
   out_8003140298768285729[13] = delta_x[13] + nom_x[13];
   out_8003140298768285729[14] = delta_x[14] + nom_x[14];
   out_8003140298768285729[15] = delta_x[15] + nom_x[15];
   out_8003140298768285729[16] = delta_x[16] + nom_x[16];
   out_8003140298768285729[17] = delta_x[17] + nom_x[17];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_1585615485350566282) {
   out_1585615485350566282[0] = -nom_x[0] + true_x[0];
   out_1585615485350566282[1] = -nom_x[1] + true_x[1];
   out_1585615485350566282[2] = -nom_x[2] + true_x[2];
   out_1585615485350566282[3] = -nom_x[3] + true_x[3];
   out_1585615485350566282[4] = -nom_x[4] + true_x[4];
   out_1585615485350566282[5] = -nom_x[5] + true_x[5];
   out_1585615485350566282[6] = -nom_x[6] + true_x[6];
   out_1585615485350566282[7] = -nom_x[7] + true_x[7];
   out_1585615485350566282[8] = -nom_x[8] + true_x[8];
   out_1585615485350566282[9] = -nom_x[9] + true_x[9];
   out_1585615485350566282[10] = -nom_x[10] + true_x[10];
   out_1585615485350566282[11] = -nom_x[11] + true_x[11];
   out_1585615485350566282[12] = -nom_x[12] + true_x[12];
   out_1585615485350566282[13] = -nom_x[13] + true_x[13];
   out_1585615485350566282[14] = -nom_x[14] + true_x[14];
   out_1585615485350566282[15] = -nom_x[15] + true_x[15];
   out_1585615485350566282[16] = -nom_x[16] + true_x[16];
   out_1585615485350566282[17] = -nom_x[17] + true_x[17];
}
void H_mod_fun(double *state, double *out_6339119660772184359) {
   out_6339119660772184359[0] = 1.0;
   out_6339119660772184359[1] = 0.0;
   out_6339119660772184359[2] = 0.0;
   out_6339119660772184359[3] = 0.0;
   out_6339119660772184359[4] = 0.0;
   out_6339119660772184359[5] = 0.0;
   out_6339119660772184359[6] = 0.0;
   out_6339119660772184359[7] = 0.0;
   out_6339119660772184359[8] = 0.0;
   out_6339119660772184359[9] = 0.0;
   out_6339119660772184359[10] = 0.0;
   out_6339119660772184359[11] = 0.0;
   out_6339119660772184359[12] = 0.0;
   out_6339119660772184359[13] = 0.0;
   out_6339119660772184359[14] = 0.0;
   out_6339119660772184359[15] = 0.0;
   out_6339119660772184359[16] = 0.0;
   out_6339119660772184359[17] = 0.0;
   out_6339119660772184359[18] = 0.0;
   out_6339119660772184359[19] = 1.0;
   out_6339119660772184359[20] = 0.0;
   out_6339119660772184359[21] = 0.0;
   out_6339119660772184359[22] = 0.0;
   out_6339119660772184359[23] = 0.0;
   out_6339119660772184359[24] = 0.0;
   out_6339119660772184359[25] = 0.0;
   out_6339119660772184359[26] = 0.0;
   out_6339119660772184359[27] = 0.0;
   out_6339119660772184359[28] = 0.0;
   out_6339119660772184359[29] = 0.0;
   out_6339119660772184359[30] = 0.0;
   out_6339119660772184359[31] = 0.0;
   out_6339119660772184359[32] = 0.0;
   out_6339119660772184359[33] = 0.0;
   out_6339119660772184359[34] = 0.0;
   out_6339119660772184359[35] = 0.0;
   out_6339119660772184359[36] = 0.0;
   out_6339119660772184359[37] = 0.0;
   out_6339119660772184359[38] = 1.0;
   out_6339119660772184359[39] = 0.0;
   out_6339119660772184359[40] = 0.0;
   out_6339119660772184359[41] = 0.0;
   out_6339119660772184359[42] = 0.0;
   out_6339119660772184359[43] = 0.0;
   out_6339119660772184359[44] = 0.0;
   out_6339119660772184359[45] = 0.0;
   out_6339119660772184359[46] = 0.0;
   out_6339119660772184359[47] = 0.0;
   out_6339119660772184359[48] = 0.0;
   out_6339119660772184359[49] = 0.0;
   out_6339119660772184359[50] = 0.0;
   out_6339119660772184359[51] = 0.0;
   out_6339119660772184359[52] = 0.0;
   out_6339119660772184359[53] = 0.0;
   out_6339119660772184359[54] = 0.0;
   out_6339119660772184359[55] = 0.0;
   out_6339119660772184359[56] = 0.0;
   out_6339119660772184359[57] = 1.0;
   out_6339119660772184359[58] = 0.0;
   out_6339119660772184359[59] = 0.0;
   out_6339119660772184359[60] = 0.0;
   out_6339119660772184359[61] = 0.0;
   out_6339119660772184359[62] = 0.0;
   out_6339119660772184359[63] = 0.0;
   out_6339119660772184359[64] = 0.0;
   out_6339119660772184359[65] = 0.0;
   out_6339119660772184359[66] = 0.0;
   out_6339119660772184359[67] = 0.0;
   out_6339119660772184359[68] = 0.0;
   out_6339119660772184359[69] = 0.0;
   out_6339119660772184359[70] = 0.0;
   out_6339119660772184359[71] = 0.0;
   out_6339119660772184359[72] = 0.0;
   out_6339119660772184359[73] = 0.0;
   out_6339119660772184359[74] = 0.0;
   out_6339119660772184359[75] = 0.0;
   out_6339119660772184359[76] = 1.0;
   out_6339119660772184359[77] = 0.0;
   out_6339119660772184359[78] = 0.0;
   out_6339119660772184359[79] = 0.0;
   out_6339119660772184359[80] = 0.0;
   out_6339119660772184359[81] = 0.0;
   out_6339119660772184359[82] = 0.0;
   out_6339119660772184359[83] = 0.0;
   out_6339119660772184359[84] = 0.0;
   out_6339119660772184359[85] = 0.0;
   out_6339119660772184359[86] = 0.0;
   out_6339119660772184359[87] = 0.0;
   out_6339119660772184359[88] = 0.0;
   out_6339119660772184359[89] = 0.0;
   out_6339119660772184359[90] = 0.0;
   out_6339119660772184359[91] = 0.0;
   out_6339119660772184359[92] = 0.0;
   out_6339119660772184359[93] = 0.0;
   out_6339119660772184359[94] = 0.0;
   out_6339119660772184359[95] = 1.0;
   out_6339119660772184359[96] = 0.0;
   out_6339119660772184359[97] = 0.0;
   out_6339119660772184359[98] = 0.0;
   out_6339119660772184359[99] = 0.0;
   out_6339119660772184359[100] = 0.0;
   out_6339119660772184359[101] = 0.0;
   out_6339119660772184359[102] = 0.0;
   out_6339119660772184359[103] = 0.0;
   out_6339119660772184359[104] = 0.0;
   out_6339119660772184359[105] = 0.0;
   out_6339119660772184359[106] = 0.0;
   out_6339119660772184359[107] = 0.0;
   out_6339119660772184359[108] = 0.0;
   out_6339119660772184359[109] = 0.0;
   out_6339119660772184359[110] = 0.0;
   out_6339119660772184359[111] = 0.0;
   out_6339119660772184359[112] = 0.0;
   out_6339119660772184359[113] = 0.0;
   out_6339119660772184359[114] = 1.0;
   out_6339119660772184359[115] = 0.0;
   out_6339119660772184359[116] = 0.0;
   out_6339119660772184359[117] = 0.0;
   out_6339119660772184359[118] = 0.0;
   out_6339119660772184359[119] = 0.0;
   out_6339119660772184359[120] = 0.0;
   out_6339119660772184359[121] = 0.0;
   out_6339119660772184359[122] = 0.0;
   out_6339119660772184359[123] = 0.0;
   out_6339119660772184359[124] = 0.0;
   out_6339119660772184359[125] = 0.0;
   out_6339119660772184359[126] = 0.0;
   out_6339119660772184359[127] = 0.0;
   out_6339119660772184359[128] = 0.0;
   out_6339119660772184359[129] = 0.0;
   out_6339119660772184359[130] = 0.0;
   out_6339119660772184359[131] = 0.0;
   out_6339119660772184359[132] = 0.0;
   out_6339119660772184359[133] = 1.0;
   out_6339119660772184359[134] = 0.0;
   out_6339119660772184359[135] = 0.0;
   out_6339119660772184359[136] = 0.0;
   out_6339119660772184359[137] = 0.0;
   out_6339119660772184359[138] = 0.0;
   out_6339119660772184359[139] = 0.0;
   out_6339119660772184359[140] = 0.0;
   out_6339119660772184359[141] = 0.0;
   out_6339119660772184359[142] = 0.0;
   out_6339119660772184359[143] = 0.0;
   out_6339119660772184359[144] = 0.0;
   out_6339119660772184359[145] = 0.0;
   out_6339119660772184359[146] = 0.0;
   out_6339119660772184359[147] = 0.0;
   out_6339119660772184359[148] = 0.0;
   out_6339119660772184359[149] = 0.0;
   out_6339119660772184359[150] = 0.0;
   out_6339119660772184359[151] = 0.0;
   out_6339119660772184359[152] = 1.0;
   out_6339119660772184359[153] = 0.0;
   out_6339119660772184359[154] = 0.0;
   out_6339119660772184359[155] = 0.0;
   out_6339119660772184359[156] = 0.0;
   out_6339119660772184359[157] = 0.0;
   out_6339119660772184359[158] = 0.0;
   out_6339119660772184359[159] = 0.0;
   out_6339119660772184359[160] = 0.0;
   out_6339119660772184359[161] = 0.0;
   out_6339119660772184359[162] = 0.0;
   out_6339119660772184359[163] = 0.0;
   out_6339119660772184359[164] = 0.0;
   out_6339119660772184359[165] = 0.0;
   out_6339119660772184359[166] = 0.0;
   out_6339119660772184359[167] = 0.0;
   out_6339119660772184359[168] = 0.0;
   out_6339119660772184359[169] = 0.0;
   out_6339119660772184359[170] = 0.0;
   out_6339119660772184359[171] = 1.0;
   out_6339119660772184359[172] = 0.0;
   out_6339119660772184359[173] = 0.0;
   out_6339119660772184359[174] = 0.0;
   out_6339119660772184359[175] = 0.0;
   out_6339119660772184359[176] = 0.0;
   out_6339119660772184359[177] = 0.0;
   out_6339119660772184359[178] = 0.0;
   out_6339119660772184359[179] = 0.0;
   out_6339119660772184359[180] = 0.0;
   out_6339119660772184359[181] = 0.0;
   out_6339119660772184359[182] = 0.0;
   out_6339119660772184359[183] = 0.0;
   out_6339119660772184359[184] = 0.0;
   out_6339119660772184359[185] = 0.0;
   out_6339119660772184359[186] = 0.0;
   out_6339119660772184359[187] = 0.0;
   out_6339119660772184359[188] = 0.0;
   out_6339119660772184359[189] = 0.0;
   out_6339119660772184359[190] = 1.0;
   out_6339119660772184359[191] = 0.0;
   out_6339119660772184359[192] = 0.0;
   out_6339119660772184359[193] = 0.0;
   out_6339119660772184359[194] = 0.0;
   out_6339119660772184359[195] = 0.0;
   out_6339119660772184359[196] = 0.0;
   out_6339119660772184359[197] = 0.0;
   out_6339119660772184359[198] = 0.0;
   out_6339119660772184359[199] = 0.0;
   out_6339119660772184359[200] = 0.0;
   out_6339119660772184359[201] = 0.0;
   out_6339119660772184359[202] = 0.0;
   out_6339119660772184359[203] = 0.0;
   out_6339119660772184359[204] = 0.0;
   out_6339119660772184359[205] = 0.0;
   out_6339119660772184359[206] = 0.0;
   out_6339119660772184359[207] = 0.0;
   out_6339119660772184359[208] = 0.0;
   out_6339119660772184359[209] = 1.0;
   out_6339119660772184359[210] = 0.0;
   out_6339119660772184359[211] = 0.0;
   out_6339119660772184359[212] = 0.0;
   out_6339119660772184359[213] = 0.0;
   out_6339119660772184359[214] = 0.0;
   out_6339119660772184359[215] = 0.0;
   out_6339119660772184359[216] = 0.0;
   out_6339119660772184359[217] = 0.0;
   out_6339119660772184359[218] = 0.0;
   out_6339119660772184359[219] = 0.0;
   out_6339119660772184359[220] = 0.0;
   out_6339119660772184359[221] = 0.0;
   out_6339119660772184359[222] = 0.0;
   out_6339119660772184359[223] = 0.0;
   out_6339119660772184359[224] = 0.0;
   out_6339119660772184359[225] = 0.0;
   out_6339119660772184359[226] = 0.0;
   out_6339119660772184359[227] = 0.0;
   out_6339119660772184359[228] = 1.0;
   out_6339119660772184359[229] = 0.0;
   out_6339119660772184359[230] = 0.0;
   out_6339119660772184359[231] = 0.0;
   out_6339119660772184359[232] = 0.0;
   out_6339119660772184359[233] = 0.0;
   out_6339119660772184359[234] = 0.0;
   out_6339119660772184359[235] = 0.0;
   out_6339119660772184359[236] = 0.0;
   out_6339119660772184359[237] = 0.0;
   out_6339119660772184359[238] = 0.0;
   out_6339119660772184359[239] = 0.0;
   out_6339119660772184359[240] = 0.0;
   out_6339119660772184359[241] = 0.0;
   out_6339119660772184359[242] = 0.0;
   out_6339119660772184359[243] = 0.0;
   out_6339119660772184359[244] = 0.0;
   out_6339119660772184359[245] = 0.0;
   out_6339119660772184359[246] = 0.0;
   out_6339119660772184359[247] = 1.0;
   out_6339119660772184359[248] = 0.0;
   out_6339119660772184359[249] = 0.0;
   out_6339119660772184359[250] = 0.0;
   out_6339119660772184359[251] = 0.0;
   out_6339119660772184359[252] = 0.0;
   out_6339119660772184359[253] = 0.0;
   out_6339119660772184359[254] = 0.0;
   out_6339119660772184359[255] = 0.0;
   out_6339119660772184359[256] = 0.0;
   out_6339119660772184359[257] = 0.0;
   out_6339119660772184359[258] = 0.0;
   out_6339119660772184359[259] = 0.0;
   out_6339119660772184359[260] = 0.0;
   out_6339119660772184359[261] = 0.0;
   out_6339119660772184359[262] = 0.0;
   out_6339119660772184359[263] = 0.0;
   out_6339119660772184359[264] = 0.0;
   out_6339119660772184359[265] = 0.0;
   out_6339119660772184359[266] = 1.0;
   out_6339119660772184359[267] = 0.0;
   out_6339119660772184359[268] = 0.0;
   out_6339119660772184359[269] = 0.0;
   out_6339119660772184359[270] = 0.0;
   out_6339119660772184359[271] = 0.0;
   out_6339119660772184359[272] = 0.0;
   out_6339119660772184359[273] = 0.0;
   out_6339119660772184359[274] = 0.0;
   out_6339119660772184359[275] = 0.0;
   out_6339119660772184359[276] = 0.0;
   out_6339119660772184359[277] = 0.0;
   out_6339119660772184359[278] = 0.0;
   out_6339119660772184359[279] = 0.0;
   out_6339119660772184359[280] = 0.0;
   out_6339119660772184359[281] = 0.0;
   out_6339119660772184359[282] = 0.0;
   out_6339119660772184359[283] = 0.0;
   out_6339119660772184359[284] = 0.0;
   out_6339119660772184359[285] = 1.0;
   out_6339119660772184359[286] = 0.0;
   out_6339119660772184359[287] = 0.0;
   out_6339119660772184359[288] = 0.0;
   out_6339119660772184359[289] = 0.0;
   out_6339119660772184359[290] = 0.0;
   out_6339119660772184359[291] = 0.0;
   out_6339119660772184359[292] = 0.0;
   out_6339119660772184359[293] = 0.0;
   out_6339119660772184359[294] = 0.0;
   out_6339119660772184359[295] = 0.0;
   out_6339119660772184359[296] = 0.0;
   out_6339119660772184359[297] = 0.0;
   out_6339119660772184359[298] = 0.0;
   out_6339119660772184359[299] = 0.0;
   out_6339119660772184359[300] = 0.0;
   out_6339119660772184359[301] = 0.0;
   out_6339119660772184359[302] = 0.0;
   out_6339119660772184359[303] = 0.0;
   out_6339119660772184359[304] = 1.0;
   out_6339119660772184359[305] = 0.0;
   out_6339119660772184359[306] = 0.0;
   out_6339119660772184359[307] = 0.0;
   out_6339119660772184359[308] = 0.0;
   out_6339119660772184359[309] = 0.0;
   out_6339119660772184359[310] = 0.0;
   out_6339119660772184359[311] = 0.0;
   out_6339119660772184359[312] = 0.0;
   out_6339119660772184359[313] = 0.0;
   out_6339119660772184359[314] = 0.0;
   out_6339119660772184359[315] = 0.0;
   out_6339119660772184359[316] = 0.0;
   out_6339119660772184359[317] = 0.0;
   out_6339119660772184359[318] = 0.0;
   out_6339119660772184359[319] = 0.0;
   out_6339119660772184359[320] = 0.0;
   out_6339119660772184359[321] = 0.0;
   out_6339119660772184359[322] = 0.0;
   out_6339119660772184359[323] = 1.0;
}
void f_fun(double *state, double dt, double *out_8814312762725343776) {
   out_8814312762725343776[0] = atan2((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), -(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]));
   out_8814312762725343776[1] = asin(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]));
   out_8814312762725343776[2] = atan2(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), -(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]));
   out_8814312762725343776[3] = dt*state[12] + state[3];
   out_8814312762725343776[4] = dt*state[13] + state[4];
   out_8814312762725343776[5] = dt*state[14] + state[5];
   out_8814312762725343776[6] = state[6];
   out_8814312762725343776[7] = state[7];
   out_8814312762725343776[8] = state[8];
   out_8814312762725343776[9] = state[9];
   out_8814312762725343776[10] = state[10];
   out_8814312762725343776[11] = state[11];
   out_8814312762725343776[12] = state[12];
   out_8814312762725343776[13] = state[13];
   out_8814312762725343776[14] = state[14];
   out_8814312762725343776[15] = state[15];
   out_8814312762725343776[16] = state[16];
   out_8814312762725343776[17] = state[17];
}
void F_fun(double *state, double dt, double *out_3190594136445709051) {
   out_3190594136445709051[0] = ((-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*cos(state[0])*cos(state[1]) - sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*cos(state[0])*cos(state[1]) - sin(dt*state[6])*sin(state[0])*cos(dt*state[7])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3190594136445709051[1] = ((-sin(dt*state[6])*sin(dt*state[8]) - sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*cos(state[1]) - (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*sin(state[1]) - sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(state[0]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*sin(state[1]) + (-sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) + sin(dt*state[8])*cos(dt*state[6]))*cos(state[1]) - sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(state[0]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3190594136445709051[2] = 0;
   out_3190594136445709051[3] = 0;
   out_3190594136445709051[4] = 0;
   out_3190594136445709051[5] = 0;
   out_3190594136445709051[6] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(dt*cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) - dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3190594136445709051[7] = (-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[6])*sin(dt*state[7])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[6])*sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) - dt*sin(dt*state[6])*sin(state[1])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + (-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))*(-dt*sin(dt*state[7])*cos(dt*state[6])*cos(state[0])*cos(state[1]) + dt*sin(dt*state[8])*sin(state[0])*cos(dt*state[6])*cos(dt*state[7])*cos(state[1]) - dt*sin(state[1])*cos(dt*state[6])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3190594136445709051[8] = ((dt*sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + dt*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (dt*sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]))*(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2)) + ((dt*sin(dt*state[6])*sin(dt*state[8]) + dt*sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (-dt*sin(dt*state[6])*cos(dt*state[8]) + dt*sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]))*(-(sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) + (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) - sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/(pow(-(sin(dt*state[6])*sin(dt*state[8]) + sin(dt*state[7])*cos(dt*state[6])*cos(dt*state[8]))*sin(state[1]) + (-sin(dt*state[6])*cos(dt*state[8]) + sin(dt*state[7])*sin(dt*state[8])*cos(dt*state[6]))*sin(state[0])*cos(state[1]) + cos(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2) + pow((sin(dt*state[6])*sin(dt*state[7])*sin(dt*state[8]) + cos(dt*state[6])*cos(dt*state[8]))*sin(state[0])*cos(state[1]) - (sin(dt*state[6])*sin(dt*state[7])*cos(dt*state[8]) - sin(dt*state[8])*cos(dt*state[6]))*sin(state[1]) + sin(dt*state[6])*cos(dt*state[7])*cos(state[0])*cos(state[1]), 2));
   out_3190594136445709051[9] = 0;
   out_3190594136445709051[10] = 0;
   out_3190594136445709051[11] = 0;
   out_3190594136445709051[12] = 0;
   out_3190594136445709051[13] = 0;
   out_3190594136445709051[14] = 0;
   out_3190594136445709051[15] = 0;
   out_3190594136445709051[16] = 0;
   out_3190594136445709051[17] = 0;
   out_3190594136445709051[18] = (-sin(dt*state[7])*sin(state[0])*cos(state[1]) - sin(dt*state[8])*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3190594136445709051[19] = (-sin(dt*state[7])*sin(state[1])*cos(state[0]) + sin(dt*state[8])*sin(state[0])*sin(state[1])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3190594136445709051[20] = 0;
   out_3190594136445709051[21] = 0;
   out_3190594136445709051[22] = 0;
   out_3190594136445709051[23] = 0;
   out_3190594136445709051[24] = 0;
   out_3190594136445709051[25] = (dt*sin(dt*state[7])*sin(dt*state[8])*sin(state[0])*cos(state[1]) - dt*sin(dt*state[7])*sin(state[1])*cos(dt*state[8]) + dt*cos(dt*state[7])*cos(state[0])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3190594136445709051[26] = (-dt*sin(dt*state[8])*sin(state[1])*cos(dt*state[7]) - dt*sin(state[0])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/sqrt(1 - pow(sin(dt*state[7])*cos(state[0])*cos(state[1]) - sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1]) + sin(state[1])*cos(dt*state[7])*cos(dt*state[8]), 2));
   out_3190594136445709051[27] = 0;
   out_3190594136445709051[28] = 0;
   out_3190594136445709051[29] = 0;
   out_3190594136445709051[30] = 0;
   out_3190594136445709051[31] = 0;
   out_3190594136445709051[32] = 0;
   out_3190594136445709051[33] = 0;
   out_3190594136445709051[34] = 0;
   out_3190594136445709051[35] = 0;
   out_3190594136445709051[36] = ((sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3190594136445709051[37] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-sin(dt*state[7])*sin(state[2])*cos(state[0])*cos(state[1]) + sin(dt*state[8])*sin(state[0])*sin(state[2])*cos(dt*state[7])*cos(state[1]) - sin(state[1])*sin(state[2])*cos(dt*state[7])*cos(dt*state[8]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(-sin(dt*state[7])*cos(state[0])*cos(state[1])*cos(state[2]) + sin(dt*state[8])*sin(state[0])*cos(dt*state[7])*cos(state[1])*cos(state[2]) - sin(state[1])*cos(dt*state[7])*cos(dt*state[8])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3190594136445709051[38] = ((-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (-sin(state[0])*sin(state[1])*sin(state[2]) - cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3190594136445709051[39] = 0;
   out_3190594136445709051[40] = 0;
   out_3190594136445709051[41] = 0;
   out_3190594136445709051[42] = 0;
   out_3190594136445709051[43] = (-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))*(dt*(sin(state[0])*cos(state[2]) - sin(state[1])*sin(state[2])*cos(state[0]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*sin(state[2])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + ((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))*(dt*(-sin(state[0])*sin(state[2]) - sin(state[1])*cos(state[0])*cos(state[2]))*cos(dt*state[7]) - dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[7])*sin(dt*state[8]) - dt*sin(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3190594136445709051[44] = (dt*(sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*sin(state[2])*cos(dt*state[7])*cos(state[1]))*(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2)) + (dt*(sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*cos(dt*state[7])*cos(dt*state[8]) - dt*sin(dt*state[8])*cos(dt*state[7])*cos(state[1])*cos(state[2]))*((-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) - (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) - sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]))/(pow(-(sin(state[0])*sin(state[2]) + sin(state[1])*cos(state[0])*cos(state[2]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*cos(state[2]) - sin(state[2])*cos(state[0]))*sin(dt*state[8])*cos(dt*state[7]) + cos(dt*state[7])*cos(dt*state[8])*cos(state[1])*cos(state[2]), 2) + pow(-(-sin(state[0])*cos(state[2]) + sin(state[1])*sin(state[2])*cos(state[0]))*sin(dt*state[7]) + (sin(state[0])*sin(state[1])*sin(state[2]) + cos(state[0])*cos(state[2]))*sin(dt*state[8])*cos(dt*state[7]) + sin(state[2])*cos(dt*state[7])*cos(dt*state[8])*cos(state[1]), 2));
   out_3190594136445709051[45] = 0;
   out_3190594136445709051[46] = 0;
   out_3190594136445709051[47] = 0;
   out_3190594136445709051[48] = 0;
   out_3190594136445709051[49] = 0;
   out_3190594136445709051[50] = 0;
   out_3190594136445709051[51] = 0;
   out_3190594136445709051[52] = 0;
   out_3190594136445709051[53] = 0;
   out_3190594136445709051[54] = 0;
   out_3190594136445709051[55] = 0;
   out_3190594136445709051[56] = 0;
   out_3190594136445709051[57] = 1;
   out_3190594136445709051[58] = 0;
   out_3190594136445709051[59] = 0;
   out_3190594136445709051[60] = 0;
   out_3190594136445709051[61] = 0;
   out_3190594136445709051[62] = 0;
   out_3190594136445709051[63] = 0;
   out_3190594136445709051[64] = 0;
   out_3190594136445709051[65] = 0;
   out_3190594136445709051[66] = dt;
   out_3190594136445709051[67] = 0;
   out_3190594136445709051[68] = 0;
   out_3190594136445709051[69] = 0;
   out_3190594136445709051[70] = 0;
   out_3190594136445709051[71] = 0;
   out_3190594136445709051[72] = 0;
   out_3190594136445709051[73] = 0;
   out_3190594136445709051[74] = 0;
   out_3190594136445709051[75] = 0;
   out_3190594136445709051[76] = 1;
   out_3190594136445709051[77] = 0;
   out_3190594136445709051[78] = 0;
   out_3190594136445709051[79] = 0;
   out_3190594136445709051[80] = 0;
   out_3190594136445709051[81] = 0;
   out_3190594136445709051[82] = 0;
   out_3190594136445709051[83] = 0;
   out_3190594136445709051[84] = 0;
   out_3190594136445709051[85] = dt;
   out_3190594136445709051[86] = 0;
   out_3190594136445709051[87] = 0;
   out_3190594136445709051[88] = 0;
   out_3190594136445709051[89] = 0;
   out_3190594136445709051[90] = 0;
   out_3190594136445709051[91] = 0;
   out_3190594136445709051[92] = 0;
   out_3190594136445709051[93] = 0;
   out_3190594136445709051[94] = 0;
   out_3190594136445709051[95] = 1;
   out_3190594136445709051[96] = 0;
   out_3190594136445709051[97] = 0;
   out_3190594136445709051[98] = 0;
   out_3190594136445709051[99] = 0;
   out_3190594136445709051[100] = 0;
   out_3190594136445709051[101] = 0;
   out_3190594136445709051[102] = 0;
   out_3190594136445709051[103] = 0;
   out_3190594136445709051[104] = dt;
   out_3190594136445709051[105] = 0;
   out_3190594136445709051[106] = 0;
   out_3190594136445709051[107] = 0;
   out_3190594136445709051[108] = 0;
   out_3190594136445709051[109] = 0;
   out_3190594136445709051[110] = 0;
   out_3190594136445709051[111] = 0;
   out_3190594136445709051[112] = 0;
   out_3190594136445709051[113] = 0;
   out_3190594136445709051[114] = 1;
   out_3190594136445709051[115] = 0;
   out_3190594136445709051[116] = 0;
   out_3190594136445709051[117] = 0;
   out_3190594136445709051[118] = 0;
   out_3190594136445709051[119] = 0;
   out_3190594136445709051[120] = 0;
   out_3190594136445709051[121] = 0;
   out_3190594136445709051[122] = 0;
   out_3190594136445709051[123] = 0;
   out_3190594136445709051[124] = 0;
   out_3190594136445709051[125] = 0;
   out_3190594136445709051[126] = 0;
   out_3190594136445709051[127] = 0;
   out_3190594136445709051[128] = 0;
   out_3190594136445709051[129] = 0;
   out_3190594136445709051[130] = 0;
   out_3190594136445709051[131] = 0;
   out_3190594136445709051[132] = 0;
   out_3190594136445709051[133] = 1;
   out_3190594136445709051[134] = 0;
   out_3190594136445709051[135] = 0;
   out_3190594136445709051[136] = 0;
   out_3190594136445709051[137] = 0;
   out_3190594136445709051[138] = 0;
   out_3190594136445709051[139] = 0;
   out_3190594136445709051[140] = 0;
   out_3190594136445709051[141] = 0;
   out_3190594136445709051[142] = 0;
   out_3190594136445709051[143] = 0;
   out_3190594136445709051[144] = 0;
   out_3190594136445709051[145] = 0;
   out_3190594136445709051[146] = 0;
   out_3190594136445709051[147] = 0;
   out_3190594136445709051[148] = 0;
   out_3190594136445709051[149] = 0;
   out_3190594136445709051[150] = 0;
   out_3190594136445709051[151] = 0;
   out_3190594136445709051[152] = 1;
   out_3190594136445709051[153] = 0;
   out_3190594136445709051[154] = 0;
   out_3190594136445709051[155] = 0;
   out_3190594136445709051[156] = 0;
   out_3190594136445709051[157] = 0;
   out_3190594136445709051[158] = 0;
   out_3190594136445709051[159] = 0;
   out_3190594136445709051[160] = 0;
   out_3190594136445709051[161] = 0;
   out_3190594136445709051[162] = 0;
   out_3190594136445709051[163] = 0;
   out_3190594136445709051[164] = 0;
   out_3190594136445709051[165] = 0;
   out_3190594136445709051[166] = 0;
   out_3190594136445709051[167] = 0;
   out_3190594136445709051[168] = 0;
   out_3190594136445709051[169] = 0;
   out_3190594136445709051[170] = 0;
   out_3190594136445709051[171] = 1;
   out_3190594136445709051[172] = 0;
   out_3190594136445709051[173] = 0;
   out_3190594136445709051[174] = 0;
   out_3190594136445709051[175] = 0;
   out_3190594136445709051[176] = 0;
   out_3190594136445709051[177] = 0;
   out_3190594136445709051[178] = 0;
   out_3190594136445709051[179] = 0;
   out_3190594136445709051[180] = 0;
   out_3190594136445709051[181] = 0;
   out_3190594136445709051[182] = 0;
   out_3190594136445709051[183] = 0;
   out_3190594136445709051[184] = 0;
   out_3190594136445709051[185] = 0;
   out_3190594136445709051[186] = 0;
   out_3190594136445709051[187] = 0;
   out_3190594136445709051[188] = 0;
   out_3190594136445709051[189] = 0;
   out_3190594136445709051[190] = 1;
   out_3190594136445709051[191] = 0;
   out_3190594136445709051[192] = 0;
   out_3190594136445709051[193] = 0;
   out_3190594136445709051[194] = 0;
   out_3190594136445709051[195] = 0;
   out_3190594136445709051[196] = 0;
   out_3190594136445709051[197] = 0;
   out_3190594136445709051[198] = 0;
   out_3190594136445709051[199] = 0;
   out_3190594136445709051[200] = 0;
   out_3190594136445709051[201] = 0;
   out_3190594136445709051[202] = 0;
   out_3190594136445709051[203] = 0;
   out_3190594136445709051[204] = 0;
   out_3190594136445709051[205] = 0;
   out_3190594136445709051[206] = 0;
   out_3190594136445709051[207] = 0;
   out_3190594136445709051[208] = 0;
   out_3190594136445709051[209] = 1;
   out_3190594136445709051[210] = 0;
   out_3190594136445709051[211] = 0;
   out_3190594136445709051[212] = 0;
   out_3190594136445709051[213] = 0;
   out_3190594136445709051[214] = 0;
   out_3190594136445709051[215] = 0;
   out_3190594136445709051[216] = 0;
   out_3190594136445709051[217] = 0;
   out_3190594136445709051[218] = 0;
   out_3190594136445709051[219] = 0;
   out_3190594136445709051[220] = 0;
   out_3190594136445709051[221] = 0;
   out_3190594136445709051[222] = 0;
   out_3190594136445709051[223] = 0;
   out_3190594136445709051[224] = 0;
   out_3190594136445709051[225] = 0;
   out_3190594136445709051[226] = 0;
   out_3190594136445709051[227] = 0;
   out_3190594136445709051[228] = 1;
   out_3190594136445709051[229] = 0;
   out_3190594136445709051[230] = 0;
   out_3190594136445709051[231] = 0;
   out_3190594136445709051[232] = 0;
   out_3190594136445709051[233] = 0;
   out_3190594136445709051[234] = 0;
   out_3190594136445709051[235] = 0;
   out_3190594136445709051[236] = 0;
   out_3190594136445709051[237] = 0;
   out_3190594136445709051[238] = 0;
   out_3190594136445709051[239] = 0;
   out_3190594136445709051[240] = 0;
   out_3190594136445709051[241] = 0;
   out_3190594136445709051[242] = 0;
   out_3190594136445709051[243] = 0;
   out_3190594136445709051[244] = 0;
   out_3190594136445709051[245] = 0;
   out_3190594136445709051[246] = 0;
   out_3190594136445709051[247] = 1;
   out_3190594136445709051[248] = 0;
   out_3190594136445709051[249] = 0;
   out_3190594136445709051[250] = 0;
   out_3190594136445709051[251] = 0;
   out_3190594136445709051[252] = 0;
   out_3190594136445709051[253] = 0;
   out_3190594136445709051[254] = 0;
   out_3190594136445709051[255] = 0;
   out_3190594136445709051[256] = 0;
   out_3190594136445709051[257] = 0;
   out_3190594136445709051[258] = 0;
   out_3190594136445709051[259] = 0;
   out_3190594136445709051[260] = 0;
   out_3190594136445709051[261] = 0;
   out_3190594136445709051[262] = 0;
   out_3190594136445709051[263] = 0;
   out_3190594136445709051[264] = 0;
   out_3190594136445709051[265] = 0;
   out_3190594136445709051[266] = 1;
   out_3190594136445709051[267] = 0;
   out_3190594136445709051[268] = 0;
   out_3190594136445709051[269] = 0;
   out_3190594136445709051[270] = 0;
   out_3190594136445709051[271] = 0;
   out_3190594136445709051[272] = 0;
   out_3190594136445709051[273] = 0;
   out_3190594136445709051[274] = 0;
   out_3190594136445709051[275] = 0;
   out_3190594136445709051[276] = 0;
   out_3190594136445709051[277] = 0;
   out_3190594136445709051[278] = 0;
   out_3190594136445709051[279] = 0;
   out_3190594136445709051[280] = 0;
   out_3190594136445709051[281] = 0;
   out_3190594136445709051[282] = 0;
   out_3190594136445709051[283] = 0;
   out_3190594136445709051[284] = 0;
   out_3190594136445709051[285] = 1;
   out_3190594136445709051[286] = 0;
   out_3190594136445709051[287] = 0;
   out_3190594136445709051[288] = 0;
   out_3190594136445709051[289] = 0;
   out_3190594136445709051[290] = 0;
   out_3190594136445709051[291] = 0;
   out_3190594136445709051[292] = 0;
   out_3190594136445709051[293] = 0;
   out_3190594136445709051[294] = 0;
   out_3190594136445709051[295] = 0;
   out_3190594136445709051[296] = 0;
   out_3190594136445709051[297] = 0;
   out_3190594136445709051[298] = 0;
   out_3190594136445709051[299] = 0;
   out_3190594136445709051[300] = 0;
   out_3190594136445709051[301] = 0;
   out_3190594136445709051[302] = 0;
   out_3190594136445709051[303] = 0;
   out_3190594136445709051[304] = 1;
   out_3190594136445709051[305] = 0;
   out_3190594136445709051[306] = 0;
   out_3190594136445709051[307] = 0;
   out_3190594136445709051[308] = 0;
   out_3190594136445709051[309] = 0;
   out_3190594136445709051[310] = 0;
   out_3190594136445709051[311] = 0;
   out_3190594136445709051[312] = 0;
   out_3190594136445709051[313] = 0;
   out_3190594136445709051[314] = 0;
   out_3190594136445709051[315] = 0;
   out_3190594136445709051[316] = 0;
   out_3190594136445709051[317] = 0;
   out_3190594136445709051[318] = 0;
   out_3190594136445709051[319] = 0;
   out_3190594136445709051[320] = 0;
   out_3190594136445709051[321] = 0;
   out_3190594136445709051[322] = 0;
   out_3190594136445709051[323] = 1;
}
void h_4(double *state, double *unused, double *out_1691227165262288451) {
   out_1691227165262288451[0] = state[6] + state[9];
   out_1691227165262288451[1] = state[7] + state[10];
   out_1691227165262288451[2] = state[8] + state[11];
}
void H_4(double *state, double *unused, double *out_8335817203093459685) {
   out_8335817203093459685[0] = 0;
   out_8335817203093459685[1] = 0;
   out_8335817203093459685[2] = 0;
   out_8335817203093459685[3] = 0;
   out_8335817203093459685[4] = 0;
   out_8335817203093459685[5] = 0;
   out_8335817203093459685[6] = 1;
   out_8335817203093459685[7] = 0;
   out_8335817203093459685[8] = 0;
   out_8335817203093459685[9] = 1;
   out_8335817203093459685[10] = 0;
   out_8335817203093459685[11] = 0;
   out_8335817203093459685[12] = 0;
   out_8335817203093459685[13] = 0;
   out_8335817203093459685[14] = 0;
   out_8335817203093459685[15] = 0;
   out_8335817203093459685[16] = 0;
   out_8335817203093459685[17] = 0;
   out_8335817203093459685[18] = 0;
   out_8335817203093459685[19] = 0;
   out_8335817203093459685[20] = 0;
   out_8335817203093459685[21] = 0;
   out_8335817203093459685[22] = 0;
   out_8335817203093459685[23] = 0;
   out_8335817203093459685[24] = 0;
   out_8335817203093459685[25] = 1;
   out_8335817203093459685[26] = 0;
   out_8335817203093459685[27] = 0;
   out_8335817203093459685[28] = 1;
   out_8335817203093459685[29] = 0;
   out_8335817203093459685[30] = 0;
   out_8335817203093459685[31] = 0;
   out_8335817203093459685[32] = 0;
   out_8335817203093459685[33] = 0;
   out_8335817203093459685[34] = 0;
   out_8335817203093459685[35] = 0;
   out_8335817203093459685[36] = 0;
   out_8335817203093459685[37] = 0;
   out_8335817203093459685[38] = 0;
   out_8335817203093459685[39] = 0;
   out_8335817203093459685[40] = 0;
   out_8335817203093459685[41] = 0;
   out_8335817203093459685[42] = 0;
   out_8335817203093459685[43] = 0;
   out_8335817203093459685[44] = 1;
   out_8335817203093459685[45] = 0;
   out_8335817203093459685[46] = 0;
   out_8335817203093459685[47] = 1;
   out_8335817203093459685[48] = 0;
   out_8335817203093459685[49] = 0;
   out_8335817203093459685[50] = 0;
   out_8335817203093459685[51] = 0;
   out_8335817203093459685[52] = 0;
   out_8335817203093459685[53] = 0;
}
void h_10(double *state, double *unused, double *out_2403183795320234102) {
   out_2403183795320234102[0] = 9.8100000000000005*sin(state[1]) - state[4]*state[8] + state[5]*state[7] + state[12] + state[15];
   out_2403183795320234102[1] = -9.8100000000000005*sin(state[0])*cos(state[1]) + state[3]*state[8] - state[5]*state[6] + state[13] + state[16];
   out_2403183795320234102[2] = -9.8100000000000005*cos(state[0])*cos(state[1]) - state[3]*state[7] + state[4]*state[6] + state[14] + state[17];
}
void H_10(double *state, double *unused, double *out_1717861992756499185) {
   out_1717861992756499185[0] = 0;
   out_1717861992756499185[1] = 9.8100000000000005*cos(state[1]);
   out_1717861992756499185[2] = 0;
   out_1717861992756499185[3] = 0;
   out_1717861992756499185[4] = -state[8];
   out_1717861992756499185[5] = state[7];
   out_1717861992756499185[6] = 0;
   out_1717861992756499185[7] = state[5];
   out_1717861992756499185[8] = -state[4];
   out_1717861992756499185[9] = 0;
   out_1717861992756499185[10] = 0;
   out_1717861992756499185[11] = 0;
   out_1717861992756499185[12] = 1;
   out_1717861992756499185[13] = 0;
   out_1717861992756499185[14] = 0;
   out_1717861992756499185[15] = 1;
   out_1717861992756499185[16] = 0;
   out_1717861992756499185[17] = 0;
   out_1717861992756499185[18] = -9.8100000000000005*cos(state[0])*cos(state[1]);
   out_1717861992756499185[19] = 9.8100000000000005*sin(state[0])*sin(state[1]);
   out_1717861992756499185[20] = 0;
   out_1717861992756499185[21] = state[8];
   out_1717861992756499185[22] = 0;
   out_1717861992756499185[23] = -state[6];
   out_1717861992756499185[24] = -state[5];
   out_1717861992756499185[25] = 0;
   out_1717861992756499185[26] = state[3];
   out_1717861992756499185[27] = 0;
   out_1717861992756499185[28] = 0;
   out_1717861992756499185[29] = 0;
   out_1717861992756499185[30] = 0;
   out_1717861992756499185[31] = 1;
   out_1717861992756499185[32] = 0;
   out_1717861992756499185[33] = 0;
   out_1717861992756499185[34] = 1;
   out_1717861992756499185[35] = 0;
   out_1717861992756499185[36] = 9.8100000000000005*sin(state[0])*cos(state[1]);
   out_1717861992756499185[37] = 9.8100000000000005*sin(state[1])*cos(state[0]);
   out_1717861992756499185[38] = 0;
   out_1717861992756499185[39] = -state[7];
   out_1717861992756499185[40] = state[6];
   out_1717861992756499185[41] = 0;
   out_1717861992756499185[42] = state[4];
   out_1717861992756499185[43] = -state[3];
   out_1717861992756499185[44] = 0;
   out_1717861992756499185[45] = 0;
   out_1717861992756499185[46] = 0;
   out_1717861992756499185[47] = 0;
   out_1717861992756499185[48] = 0;
   out_1717861992756499185[49] = 0;
   out_1717861992756499185[50] = 1;
   out_1717861992756499185[51] = 0;
   out_1717861992756499185[52] = 0;
   out_1717861992756499185[53] = 1;
}
void h_13(double *state, double *unused, double *out_5614817628718297389) {
   out_5614817628718297389[0] = state[3];
   out_5614817628718297389[1] = state[4];
   out_5614817628718297389[2] = state[5];
}
void H_13(double *state, double *unused, double *out_5123543377761126884) {
   out_5123543377761126884[0] = 0;
   out_5123543377761126884[1] = 0;
   out_5123543377761126884[2] = 0;
   out_5123543377761126884[3] = 1;
   out_5123543377761126884[4] = 0;
   out_5123543377761126884[5] = 0;
   out_5123543377761126884[6] = 0;
   out_5123543377761126884[7] = 0;
   out_5123543377761126884[8] = 0;
   out_5123543377761126884[9] = 0;
   out_5123543377761126884[10] = 0;
   out_5123543377761126884[11] = 0;
   out_5123543377761126884[12] = 0;
   out_5123543377761126884[13] = 0;
   out_5123543377761126884[14] = 0;
   out_5123543377761126884[15] = 0;
   out_5123543377761126884[16] = 0;
   out_5123543377761126884[17] = 0;
   out_5123543377761126884[18] = 0;
   out_5123543377761126884[19] = 0;
   out_5123543377761126884[20] = 0;
   out_5123543377761126884[21] = 0;
   out_5123543377761126884[22] = 1;
   out_5123543377761126884[23] = 0;
   out_5123543377761126884[24] = 0;
   out_5123543377761126884[25] = 0;
   out_5123543377761126884[26] = 0;
   out_5123543377761126884[27] = 0;
   out_5123543377761126884[28] = 0;
   out_5123543377761126884[29] = 0;
   out_5123543377761126884[30] = 0;
   out_5123543377761126884[31] = 0;
   out_5123543377761126884[32] = 0;
   out_5123543377761126884[33] = 0;
   out_5123543377761126884[34] = 0;
   out_5123543377761126884[35] = 0;
   out_5123543377761126884[36] = 0;
   out_5123543377761126884[37] = 0;
   out_5123543377761126884[38] = 0;
   out_5123543377761126884[39] = 0;
   out_5123543377761126884[40] = 0;
   out_5123543377761126884[41] = 1;
   out_5123543377761126884[42] = 0;
   out_5123543377761126884[43] = 0;
   out_5123543377761126884[44] = 0;
   out_5123543377761126884[45] = 0;
   out_5123543377761126884[46] = 0;
   out_5123543377761126884[47] = 0;
   out_5123543377761126884[48] = 0;
   out_5123543377761126884[49] = 0;
   out_5123543377761126884[50] = 0;
   out_5123543377761126884[51] = 0;
   out_5123543377761126884[52] = 0;
   out_5123543377761126884[53] = 0;
}
void h_14(double *state, double *unused, double *out_1705218014260526043) {
   out_1705218014260526043[0] = state[6];
   out_1705218014260526043[1] = state[7];
   out_1705218014260526043[2] = state[8];
}
void H_14(double *state, double *unused, double *out_7028138438320719635) {
   out_7028138438320719635[0] = 0;
   out_7028138438320719635[1] = 0;
   out_7028138438320719635[2] = 0;
   out_7028138438320719635[3] = 0;
   out_7028138438320719635[4] = 0;
   out_7028138438320719635[5] = 0;
   out_7028138438320719635[6] = 1;
   out_7028138438320719635[7] = 0;
   out_7028138438320719635[8] = 0;
   out_7028138438320719635[9] = 0;
   out_7028138438320719635[10] = 0;
   out_7028138438320719635[11] = 0;
   out_7028138438320719635[12] = 0;
   out_7028138438320719635[13] = 0;
   out_7028138438320719635[14] = 0;
   out_7028138438320719635[15] = 0;
   out_7028138438320719635[16] = 0;
   out_7028138438320719635[17] = 0;
   out_7028138438320719635[18] = 0;
   out_7028138438320719635[19] = 0;
   out_7028138438320719635[20] = 0;
   out_7028138438320719635[21] = 0;
   out_7028138438320719635[22] = 0;
   out_7028138438320719635[23] = 0;
   out_7028138438320719635[24] = 0;
   out_7028138438320719635[25] = 1;
   out_7028138438320719635[26] = 0;
   out_7028138438320719635[27] = 0;
   out_7028138438320719635[28] = 0;
   out_7028138438320719635[29] = 0;
   out_7028138438320719635[30] = 0;
   out_7028138438320719635[31] = 0;
   out_7028138438320719635[32] = 0;
   out_7028138438320719635[33] = 0;
   out_7028138438320719635[34] = 0;
   out_7028138438320719635[35] = 0;
   out_7028138438320719635[36] = 0;
   out_7028138438320719635[37] = 0;
   out_7028138438320719635[38] = 0;
   out_7028138438320719635[39] = 0;
   out_7028138438320719635[40] = 0;
   out_7028138438320719635[41] = 0;
   out_7028138438320719635[42] = 0;
   out_7028138438320719635[43] = 0;
   out_7028138438320719635[44] = 1;
   out_7028138438320719635[45] = 0;
   out_7028138438320719635[46] = 0;
   out_7028138438320719635[47] = 0;
   out_7028138438320719635[48] = 0;
   out_7028138438320719635[49] = 0;
   out_7028138438320719635[50] = 0;
   out_7028138438320719635[51] = 0;
   out_7028138438320719635[52] = 0;
   out_7028138438320719635[53] = 0;
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

void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_4, H_4, NULL, in_z, in_R, in_ea, MAHA_THRESH_4);
}
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_10, H_10, NULL, in_z, in_R, in_ea, MAHA_THRESH_10);
}
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_13, H_13, NULL, in_z, in_R, in_ea, MAHA_THRESH_13);
}
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<3, 3, 0>(in_x, in_P, h_14, H_14, NULL, in_z, in_R, in_ea, MAHA_THRESH_14);
}
void pose_err_fun(double *nom_x, double *delta_x, double *out_8003140298768285729) {
  err_fun(nom_x, delta_x, out_8003140298768285729);
}
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_1585615485350566282) {
  inv_err_fun(nom_x, true_x, out_1585615485350566282);
}
void pose_H_mod_fun(double *state, double *out_6339119660772184359) {
  H_mod_fun(state, out_6339119660772184359);
}
void pose_f_fun(double *state, double dt, double *out_8814312762725343776) {
  f_fun(state,  dt, out_8814312762725343776);
}
void pose_F_fun(double *state, double dt, double *out_3190594136445709051) {
  F_fun(state,  dt, out_3190594136445709051);
}
void pose_h_4(double *state, double *unused, double *out_1691227165262288451) {
  h_4(state, unused, out_1691227165262288451);
}
void pose_H_4(double *state, double *unused, double *out_8335817203093459685) {
  H_4(state, unused, out_8335817203093459685);
}
void pose_h_10(double *state, double *unused, double *out_2403183795320234102) {
  h_10(state, unused, out_2403183795320234102);
}
void pose_H_10(double *state, double *unused, double *out_1717861992756499185) {
  H_10(state, unused, out_1717861992756499185);
}
void pose_h_13(double *state, double *unused, double *out_5614817628718297389) {
  h_13(state, unused, out_5614817628718297389);
}
void pose_H_13(double *state, double *unused, double *out_5123543377761126884) {
  H_13(state, unused, out_5123543377761126884);
}
void pose_h_14(double *state, double *unused, double *out_1705218014260526043) {
  h_14(state, unused, out_1705218014260526043);
}
void pose_H_14(double *state, double *unused, double *out_7028138438320719635) {
  H_14(state, unused, out_7028138438320719635);
}
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
}

const EKF pose = {
  .name = "pose",
  .kinds = { 4, 10, 13, 14 },
  .feature_kinds = {  },
  .f_fun = pose_f_fun,
  .F_fun = pose_F_fun,
  .err_fun = pose_err_fun,
  .inv_err_fun = pose_inv_err_fun,
  .H_mod_fun = pose_H_mod_fun,
  .predict = pose_predict,
  .hs = {
    { 4, pose_h_4 },
    { 10, pose_h_10 },
    { 13, pose_h_13 },
    { 14, pose_h_14 },
  },
  .Hs = {
    { 4, pose_H_4 },
    { 10, pose_H_10 },
    { 13, pose_H_13 },
    { 14, pose_H_14 },
  },
  .updates = {
    { 4, pose_update_4 },
    { 10, pose_update_10 },
    { 13, pose_update_13 },
    { 14, pose_update_14 },
  },
  .Hes = {
  },
  .sets = {
  },
  .extra_routines = {
  },
};

ekf_lib_init(pose)
