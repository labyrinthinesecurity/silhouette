#!/usr/bin/python3
from common import *

count,current,desired=investigate_cluster(run_partition,"0",strat=None, verbose=True)
effort=current-desired
print("SPNs count",count,"current silhouette",current,"desired",desired,"effort",effort)
