#!/usr/bin/python3
from common import *

count,current,desired=generate_condensate(run_partition,"0",desired_silhouette=332)
effort=current-desired
print("SPNs count",count,"current silhouette",current,"desired",desired,"effort",effort)
