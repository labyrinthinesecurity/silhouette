#!/usr/bin/python3

import json,os

def merge_clusters(cluster, clusters):
  run_partition=os.getenv('run_partition')
  with open(f"clusters_{run_partition}.json", 'r') as f:
    data = json.load(f)
  merged_items = []
  for clusterId in [cluster] + clusters:
    merged_items.extend(data.pop(str(clusterId), []))
    data[str(cluster)] = merged_items
  with open(f"merged_clusters_{run_partition}.json", 'w') as f:
    json.dump(data,f,indent=2)
  return

run_partition=os.getenv('run_partition')

cluster = 0
clusters = [1,3,5,6]
#merges clusters 0,1,3,5 and 6 into cluster 0
# 0 <- 0 + 1 + 3 + 5 + 6
merge_clusters(cluster, clusters) 
