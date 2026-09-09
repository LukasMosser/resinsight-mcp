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

RPTRST
 'BASIC=1' /
DRSDT
 0 /
WELSPECS
 'PROD' 'G1' 10 10 8400 'OIL' /
 'INJ' 'G1' 1 1 8335 'GAS' /
/
COMPDAT
 'PROD' 10 10 3 3 'OPEN' 1* 1* 0.5 /
 'INJ' 1 1 1 1 'OPEN' 1* 1* 0.5 /
/
WCONPROD
 'PROD' 'OPEN' 'ORAT' 15000 4* 1000 /
/
WCONINJE
 'INJ' 'GAS' 'OPEN' 'RATE' 100000 1* 9014 /
/
TSTEP
 1 1 /
