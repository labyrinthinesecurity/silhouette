#!/usr/bin/python3
import pandas as pd
import numpy as np
import sys,math
from collections import defaultdict
import argparse
from datetime import datetime
from ultrametry import *

current_date = datetime.now()
timestamp = current_date.strftime("%Y-%m-%d")

parser = argparse.ArgumentParser()

if os.path.exists('management_hierarchy.csv'):
  hierarchy = load_hierarchy_from_csv("management_hierarchy.csv")
else:
  print("ERROR. Ambient hierarchy not found. Please rn Silhouette first.")
  sys.exit()

shunts = {}
shunts['native']= hierarchy


def data_action_tuples(pid,role_dict):
    cdict = {}
    shunt = 'native'
    blast_radii = {}
    max_pairs = {}
    max_pairs[shunt] = []

    if pid in role_dict:
        permiplets = group_permiplets_by_action_scope(shunts[shunt], role_dict[pid], collapsed=False)
    else:
        return None

    ps = list(permiplets)
    blast_radii[shunt], pairs = process_pairs(shunts[shunt], permiplets)
    n = len(ps)
    distance_matrix = np.full((n, n), 1.0)

    cnt = -1
    for p in pairs:
        if p['p1'] not in cdict:
            cnt += 1
            cdict[p['p1']] = cnt
        if p['p2'] and p['p2'] not in cdict:
            cnt += 1
            cdict[p['p2']] = cnt

    for p in pairs:
        i = cdict[p['p1']]
        if p['p2'] is None:
          j = cdict[p['p1']]
        else:
          j = cdict[p['p2']]
        distance_matrix[i, j] = p['distance'] 
        distance_matrix[j, i] = p['distance']

    # Start from one endpoint of the max distance pair
    max_dist = np.max(distance_matrix)
    max_dist_indices = np.where(distance_matrix == max_dist)
    max_dist_idx = (max_dist_indices[0][0], max_dist_indices[1][0])

    ordered_indices = [max_dist_idx[0]]
    remaining_indices = set(range(n)) - set(ordered_indices)

    while remaining_indices:
        last_added = ordered_indices[-1]
        min_dist = float('inf')
        next_idx = None
        for idx in remaining_indices:
            dist = distance_matrix[idx, last_added]
            if dist < min_dist:
                min_dist = dist
                next_idx = idx

        ordered_indices.append(next_idx)
        remaining_indices.remove(next_idx)

    # Convert indices to actual data action tuples
    ordered_tuples = [list(cdict.keys())[list(cdict.values()).index(i)] for i in ordered_indices]

    # Calculate Data Perimeter (TSP-style perimeter with wraparound)
    perimeter = 0
    for i in range(n):
        a = ordered_indices[i]
        b = ordered_indices[(i + 1) % n]  # wrap around
        perimeter += distance_matrix[a, b]

    # Calculate Mean (Avg distance over the whole distance matrix)
    n = distance_matrix.shape[0]
    total_pairs = n * (n - 1) // 2
    total_sum = 0.0

    # Sum over all upper triangle entries (excluding diagonal)
    if total_pairs>0:
      for i in range(n):
          for j in range(i + 1, n):
              total_sum += distance_matrix[i, j]

      mean = total_sum / total_pairs
    else:
      mean = distance_matrix[0, 0]

    return {
        "ordered_tuples": ordered_tuples,
        "data_perimeter": perimeter,
        "mean": mean,
        "data_actions": n
    }

def load_blast_radii(csv_file):
    blast_radius_dict = {}
    with open(csv_file, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            pid = row['pid']
            blast_radius_str = row['blast_radius']
            if blast_radius_str and blast_radius_str.strip():  # Check if blast_radius is not empty
                try:
                    blast_radius_float = float(blast_radius_str)
                    if blast_radius_float > 0.0:  # Check if blast_radius is greater than 0.0
                        blast_radius_dict[pid] = blast_radius_float
                except ValueError:
                    print(f"Skipping row with invalid blast_radius value: {blast_radius_str}")
    return blast_radius_dict


def group_by_band(df, epsilon=1e-35):
    band_groups = defaultdict(list)
    for _, row in df.iterrows():
        radius = row['blast_radius']
        for key in band_groups:
            if abs(key - radius) < epsilon:
                band_groups[key].append(row)
                break
        else:
            band_groups[radius].append(row)
    return band_groups

def analyze_band_spread_from_csv(csv_path):
    df = pd.read_csv(csv_path, sep=';')
    df['P_n'] = df['data_perimeter'] / df['data_actions']

    print(df)

    band_groups = group_by_band(df)
    results = []

    for radius, rows in band_groups.items():
        if len(rows) < 2:
            continue  # skip small bands

        band_df = pd.DataFrame(rows)
        perimeter_sum = band_df['P_n'].sum()
        mean_sum = band_df['mean'].sum()

        avg_perimeter = perimeter_sum / len(band_df)
        avg_mean = mean_sum / len(band_df)

        spread_ratio = avg_perimeter / avg_mean if avg_mean > 0 else float('inf')

        results.append({
            'blast_radius': radius,
            'count': len(band_df),
            'avg_data_perimeter': avg_perimeter,
            'avg_mean': avg_mean,
            'spread_ratio': spread_ratio
        })

    return pd.DataFrame(results).sort_values(by='blast_radius')

role_dict=load_roles()

if os.path.exists(f"sorted_NHIs_{timestamp}.csv"):
  brd=load_blast_radii(f"sorted_NHIs_{timestamp}.csv")
else:
  print("ERROR. sorted NHIs file not found. Please run Silhouette first.")
  sys.exit()

# Generate CSV output
print("pid;blast_radius;data_actions;data_perimeter;mean")
for pid, blast_radius in brd.items():
  geo=data_action_tuples(pid,role_dict)
  print(pid+str(";")+str(blast_radius)+str(";")+str(geo['data_actions'])+str(";")+str(geo['data_perimeter'])+str(";")+str(geo['mean']))
