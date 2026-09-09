-- This reservoir simulation deck is made available under the Open Database
-- License: http://opendatacommons.org/licenses/odbl/1.0/. Any rights in
-- individual contents of the database are licensed under the Database Contents
-- License: http://opendatacommons.org/licenses/dbcl/1.0/

-- Copyright (C) 2015 Statoil

-- This simulation is based on the data given in
-- 'Comparison of Solutions to a Three-Dimensional
-- Black-Oil Reservoir Simulation Problem' by Aziz S. Odeh,
-- Journal of Petroleum Technology, January 1981


-- Derived P07 input. See tests/models/imports/data/README.md for changes and source terms.

PROPS

PVTW
 4017.55 1.038 3.22e-06 0.318 0 /

ROCK
 14.7 3e-06 /

SWOF
 0.12 0 1 0 0.18 4.648760331e-08 1 0 0.24 1.86e-07 0.997 0 0.3 4.183884298e-07 0.98 0 0.36 7.438016529e-07 0.7 0 0.42 1.162190083e-06 0.35 0 0.48 1.673553719e-06 0.2 0 0.54 2.277892562e-06 0.09 0 0.6 2.975206612e-06 0.021 0 0.66 3.765495868e-06 0.01 0 0.72 4.648760331e-06 0.001 0 0.78 5.625e-06 0.0001 0 0.84 6.694214876e-06 0 0 0.91 8.059142562e-06 0 0 1 1e-05 0 0 /

SGOF
 0 0 1 0 0.001 0 1 0 0.02 0 0.997 0 0.05 0.005 0.98 0 0.12 0.025 0.7 0 0.2 0.075 0.35 0 0.25 0.125 0.2 0 0.3 0.19 0.09 0 0.4 0.41 0.021 0 0.45 0.6 0.01 0 0.5 0.72 0.001 0 0.6 0.87 0.0001 0 0.7 0.94 0 0 0.85 0.98 0 0 0.88 0.984 0 0 /

DENSITY
 53.66 64.49 0.0533 /

PVDG
 14.7 166.666 0.008 264.7 12.093 0.0096 514.7 6.274 0.0112 1014.7 3.197 0.014 2014.7 1.614 0.0189 2514.7 1.294 0.0208 3014.7 1.08 0.0228 4014.7 0.811 0.0268 5014.7 0.649 0.0309 9014.7 0.386 0.047 /

PVTO
 0.001 14.7 1.062 1.04 /
 0.0905 264.7 1.15 0.975 /
 0.18 514.7 1.207 0.91 /
 0.371 1014.7 1.295 0.83 /
 0.636 2014.7 1.435 0.695 /
 0.775 2514.7 1.5 0.641 /
 0.93 3014.7 1.565 0.594 /
 1.27 4014.7 1.695 0.51 9014.7 1.579 0.74 /
 1.618 5014.7 1.827 0.449 9014.7 1.737 0.631 /
/
