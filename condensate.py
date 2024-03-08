#!/usr/bin/python3
from common import *

count,current,desired=generate_condensate(run_partition,"7",strat=None, verbose=False, debug=False)
effort=current-desired
print("SPNs count",count,"current silhouette",current,"desired",desired,"effort",effort)
