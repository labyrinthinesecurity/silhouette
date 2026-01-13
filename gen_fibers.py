#!/usr/bin/python3
import json
import ast
import subprocess
import csv,os
import math,hashlib
import argparse
import pandas as pd
import random
import uuid
import numpy as np
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics import pairwise_distances
from sklearn.cluster import DBSCAN
import sys
from datetime import datetime,timedelta

parser = argparse.ArgumentParser()
parser.add_argument('--synthetic', required=False, action="store_true", help='include dbscan method fibers')
parser.add_argument('--asof', type=str, required=False, help='set the timestamp to a specific date (format: YYYY-MM-DD)')
parser.add_argument('--fr', type=str, required=False, help='start date for processing (format: YYYY-MM-DD)')
parser.add_argument('--to', type=str, required=False, help='end date for processing (format: YYYY-MM-DD)')
args = parser.parse_args()

loose_threshold=2

# Validate --asof and --fr/--to are not used together
if args.asof and (args.fr or args.to):
    print("ERROR: Cannot use --asof with --fr or --to.")
    sys.exit(1)

# Validate --fr and --to
if (args.fr is None) != (args.to is None):
    print("ERROR: Both --fr and --to must be provided together.")
    sys.exit(1)

# Set timestamp logic
if args.asof:
    try:
        timestamp = datetime.strptime(args.asof, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        print("ERROR: Invalid date format for --asof. Use YYYY-MM-DD.")
        sys.exit(1)
    timestamps = [timestamp]
elif args.fr and args.to:
    try:
        fr_date = datetime.strptime(args.fr, "%Y-%m-%d")
        to_date = datetime.strptime(args.to, "%Y-%m-%d")
        if fr_date > to_date:
            print("ERROR: --fr date must be before or equal to --to date.")
            sys.exit(1)
    except ValueError:
        print("ERROR: Invalid date format for --fr or --to. Use YYYY-MM-DD.")
        sys.exit(1)
    delta = to_date - fr_date
    timestamps = [(fr_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(delta.days + 1)]
else:
    current_date = datetime.now()
    timestamp = current_date.strftime("%Y-%m-%d")
    timestamps = [timestamp]


def cap_scope_abstraction(strict_scope_abstraction):
    uuid, level = strict_scope_abstraction.rsplit(":",1)
    if int(level)>loose_threshold:
       return f"{uuid}:{loose_threshold}"
    return strict_scope_abstraction

# Get the medoid for each cluster
def find_medoid(cluster_indices, D):
    submatrix = D[np.ix_(cluster_indices, cluster_indices)]
    avg_distances = submatrix.mean(axis=1)
    return cluster_indices[np.argmin(avg_distances)]

# Generate hash of medoid's roles
def hash_medoid(uuid_list):
    sorted_uuids = sorted(uuid_list)
    joined = ','.join(sorted_uuids)
    return hashlib.md5(joined.encode()).hexdigest()

def hash_rdids(rdid_list):
    # Sort to ensure consistent hash regardless of order
    rdid_str = ','.join(sorted(map(str, rdid_list)))
    return hashlib.sha256(rdid_str.encode()).hexdigest()

 
def generate_AZGRAPH():
  strict=False
  strict_df=None
  loose_df=None
  hashed=None
  loose_hashed=None
  if os.path.exists(f'sorted_NHIs_{timestamp}.csv'):
    score_df = pd.read_csv(f'sorted_NHIs_{timestamp}.csv')
  else:
    print(f"  ERROR, cannot read sorted_NHIs_{timestamp}.csv ====> please run silhouette.py first")
    sys.exit(1)
  strict_score_df = score_df.copy()
  strict_score_df['kappa'] = np.where(score_df['WAR'] >= 900, 699,
                    np.where(score_df['WAR'] >= 800, 588,
                    np.where(score_df['WAR'] >= 700, 477, 
                    score_df['WAR'])))
  #loose_score_filtered = score_df[['pid', 'name', 'WAR', 'blast_radius']]
  score_filtered = strict_score_df[['pid', 'name', 'kappa', 'WAR', 'blast_radius']]
  if os.path.exists(f'AZURE_FRS_{timestamp}.csv'):
    loose_df = pd.read_csv(f'AZURE_FRS_{timestamp}.csv', usecols=['pid', 'rdid'])
  if os.path.exists(f'STRICT_AZURE_FRS_{timestamp}.csv'):
    strict_df = pd.read_csv(f'STRICT_AZURE_FRS_{timestamp}.csv', usecols=['pid', 'rdid'])
    strict=True
  if not os.path.exists(f'AZURE_FRS_{timestamp}.csv'):
    print(f"  ERROR, cannot read AZURE_FRS_{timestamp}.csv ====> please run silhouette with --frs option")
    sys.exit(1)

  c=0
  for p in loose_df['pid']:
    if p not in pid_dict:
      c+=1
      pid_dict[p]=c

  if strict_df is not None:
    for p in strict_df['rdid']:
      if p not in rdid_dict:
        c+=1
        rdid_dict[p]=c
    
  if loose_df is not None:
    for p in loose_df['rdid']:
      if p not in loose_rdid_dict:
        c+=1
        loose_rdid_dict[p]=c

  reverse_pid_dict = {v: k for k, v in pid_dict.items()}
  reverse_rdid_dict = {v: k for k, v in rdid_dict.items()}
  reverse_loose_rdid_dict = {v: k for k, v in loose_rdid_dict.items()}

  #df['loose_rdid']=df['rdid'].apply(cap_scope_abstraction)

  # Assign unique integer values to each unique pid and rdid
  if strict_df is not None:
    strict_df['pid_unique'] = strict_df['pid'].apply(lambda x: pid_dict[x])  
    strict_df['rdid_unique'] = strict_df['rdid'].apply(lambda x: rdid_dict[x])  # Same for rdid
    strict_df['edgetype'] = 'plus'
    strict_df[['rdid','pid','edgetype','rdid_unique', 'pid_unique']].to_csv(f"STRICT_AZGRAPH_{timestamp}.csv", index=False, header=['SourceName','TargetName','Type','Source','Target'])
    pid_to_rdids_list = strict_df.groupby('pid')['rdid'].apply(lambda lst: sorted(map(str, lst)))
    pid_to_rdids_dict = pid_to_rdids_list.to_dict()
    hashed = pid_to_rdids_list.apply(hash_rdids).reset_index()
    hashed.columns = ['pid', 'fiber_id']
    hashed['roles'] = hashed['pid'].map(pid_to_rdids_dict)
    hashed = pd.merge(hashed, score_filtered, on='pid', how='left')
    pops = hashed.groupby('fiber_id')['pid'].count().reset_index(name='pop')
    hashed = hashed.merge(pops, on='fiber_id')
    hashed['synth_fiber'] = False
    hashed = hashed[['fiber_id', 'pop', 'kappa', 'WAR', 'blast_radius', 'pid', 'name', 'roles','synth_fiber']]
    hashed = hashed.sort_values(by=['pop','WAR', 'blast_radius', 'fiber_id','pid'], ascending=[False,False,False,True,True])
    unique_fibers_count = hashed['fiber_id'].nunique()
    counts = hashed.groupby('fiber_id')['pid'].count().sort_values(ascending=False)
    singletons = counts[counts == 1].count()
    ratio=int(100.0*float(singletons)/float(len(pid_dict)))
  if loose_df is not None:
    loose_df['pid_unique'] = loose_df['pid'].apply(lambda x: pid_dict[x])  
    loose_df['rdid_unique'] = loose_df['rdid'].apply(lambda x: loose_rdid_dict[x])
    loose_df['edgetype'] = 'plus'
    loose_df[['rdid','pid','edgetype','rdid_unique', 'pid_unique']].to_csv(f"AZGRAPH_{timestamp}.csv", index=False, header=['SourceName','TargetName','Type','Source','Target'])
    pid_to_loose_rdids_list = loose_df.groupby('pid')['rdid'].apply(lambda lst: sorted(map(str, lst)))
    pid_to_loose_rdids_dict = pid_to_loose_rdids_list.to_dict()
    loose_hashed = pid_to_loose_rdids_list.apply(hash_rdids).reset_index()
    loose_hashed.columns = ['pid', 'fiber_id']
    loose_hashed['roles'] = loose_hashed['pid'].map(pid_to_loose_rdids_dict)
    loose_hashed = pd.merge(loose_hashed, score_filtered, on='pid', how='left')
    loose_pops = loose_hashed.groupby('fiber_id')['pid'].count().reset_index(name='pop')
    loose_hashed = loose_hashed.merge(loose_pops, on='fiber_id')
    loose_hashed['synth_fiber'] = False
    loose_hashed = loose_hashed[['fiber_id', 'pop', 'kappa', 'WAR', 'blast_radius', 'pid', 'name', 'roles','synth_fiber']]
    loose_hashed = loose_hashed.sort_values(by=['pop','WAR', 'blast_radius', 'fiber_id','pid'], ascending=[False,False,False,True,True])
    loose_unique_fibers_count = loose_hashed['fiber_id'].nunique()

  #print(f"  unique PIDs: {len(pid_dict)}, unique STRICT scoped role def: {len(rdid_dict)}, unique LOOSE scoped role def: {len(loose_rdid_dict)}")
  #print(f"  unique STRICT fibers: {unique_fibers_count}, unique LOOSE fibers: {loose_unique_fibers_count}")

    loose_counts = loose_hashed.groupby('fiber_id')['pid'].count().sort_values(ascending=False)

    loose_singletons = loose_counts[loose_counts == 1].count()

    loose_ratio=int(100.0*float(loose_singletons)/float(len(pid_dict)))
    #print(f"  STRICT singleton PIDs: {singletons} ({ratio}%), LOOSE singleton PIDs: {loose_singletons} ({loose_ratio}%)")

  if args.synthetic:
    #hashed.to_csv(f"fibers_{timestamp}.csv.tmp", index=False)
    #loose_hashed.to_csv(f"sorted_fibers_{timestamp}.csv.tmp", index=False)
    return hashed,loose_hashed
  else:
    if hashed is not None:
      hashed.to_csv(f"fibers_{timestamp}.csv", index=False)
    if loose_hashed is not None:
      loose_hashed.to_csv(f"sorted_fibers_{timestamp}.csv", index=False)
    return hashed,loose_hashed

if os.path.exists('groups_roles.json'):
  with open('groups_roles.json','r') as file:
    groups=json.load(file)
else:
  print("ERROR. file groups_roles.json not found. Run silhouette first")
  sys.exit(1)

print()

# Process each timestamp
for timestamp in timestamps:
    print(f"Processing timestamp: {timestamp}")
    if not os.path.exists(f'sorted_NHIs_{timestamp}.csv'):
        print(f"WARNING: File sorted_NHIs_{timestamp}.csv not found. Skipping...")
        continue
    warpermdict={}
    spnscache={}
    spn={}
    fiber={}
    pid_dict={}
    rdid_dict={}
    loose_rdid_dict={}
    groups={}
    group={}

    pid_dict = {}
    rdid_dict = {}
    reverse_pid_dict = {}
    reverse_rdid_dict = {}
    reverse_loose_rdid_dict = {}

    df,loose_df = generate_AZGRAPH()

    continue

    df2 = df[df['pop'] > 1].reset_index(drop=True)
    df = df[df['pop'] == 1].reset_index(drop=True)

#    df['roles'] = df['roles'].apply(ast.literal_eval) #stringed list to list
#    df['roles'] = df['roles'].apply(set) # list to set
   
    if not args.synthetic:
      continue
    # Encode sets into binary format
    mlb = MultiLabelBinarizer(sparse_output=True)
    X = mlb.fit_transform(df['roles'])

    # Compute Jaccard distance matrix
    D = pairwise_distances(X.toarray().astype(bool), metric='jaccard')

    #print(df)

    cl = DBSCAN(metric='precomputed', eps=0.2, min_samples=1)
    df['cluster'] = cl.fit_predict(D)

    #print(df[['roles', 'cluster']])
    cluster_counts = df['cluster'].value_counts()

    # Add a new column with cluster size for sorting
    df['pop'] = df['cluster'].map(cluster_counts)

    fiber_medoids = {
        label: find_medoid(df[df['cluster'] == label].index.tolist(), D)
        for label in df['cluster'].unique()
    }

    # Map medoid hashes to cluster labels
    medoid_hashes = {
        label: hash_medoid(df.loc[idx, 'roles'])
        for label, idx in fiber_medoids.items()
    }

    # Replace fiber_id with medoid hash
    df['fiber_id'] = df['cluster'].map(medoid_hashes)
    df['synth_fiber'] = True
    synth_count = df['fiber_id'].nunique()
    df = df.drop(columns=['cluster'])
    combined_df = pd.concat([df, df2], ignore_index=True)
    combined_df = combined_df.sort_values(by=['pop','WAR','fiber_id','pid'], ascending=[False,False,True,True])
    combined_df.to_csv("sorted_fibers_{timestamp}.csv", index=False)
    #print()
    print(f"  synthetic fibers: {synth_count}")
    counts = combined_df.groupby('fiber_id')['pid'].count().sort_values(ascending=False)
    residual_singletons = counts[counts == 1].count()
    ratio=int(100.0*float(residual_singletons)/float(len(pid_dict)))
    print(f"  residual singletons: {residual_singletons} ({ratio}%)")

