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
parser.add_argument('--single', type=str, help='display data perimeter for just one SPN id: SINGLE')
parser.add_argument('--verbose', required=False, action="store_true", help='toggle debugging output')
args = parser.parse_args()

if os.path.exists('management_hierarchy.csv'):
  hierarchy = load_hierarchy_from_csv("management_hierarchy.csv")
else:
  print("ERROR. Ambient hierarchy not found. Please rn Silhouette first.")
  sys.exit()

shunts = {}
shunts['native']= hierarchy


def data_action_tuples(pid,role_dict,verbose):
    cdict = {}
    shunt = 'native'
    blast_radii = {}
    max_pairs = {}
    max_pairs[shunt] = []

    if pid in role_dict:
        permiplets = group_permiplets_by_action_scope(shunts[shunt], role_dict[pid], collapsed=False)
        if verbose:
          print("permiplets:")
          for p in permiplets:
            print("  ",p)
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
    TSP_tour = [list(cdict.keys())[list(cdict.values()).index(i)] for i in ordered_indices]
    TSP_tour_steps = []

    # Calculate Data Perimeter (TSP-style perimeter with wraparound)
    perimeter = 0
    for i in range(n):
        a = ordered_indices[i]
        b = ordered_indices[(i + 1) % n]  # wrap around
        perimeter += distance_matrix[a, b]
        TSP_tour_steps.append(distance_matrix[a, b])

    # Calculate Mean (Avg distance over the whole distance matrix)
    #n = distance_matrix.shape[0]
    if verbose:
      print("number of permiplets",n)
    total_permiplet_pairs = n * (n - 1) // 2
    total_sum = 0.0

    # Sum over all upper triangle entries (excluding diagonal)
    if total_permiplet_pairs>0:
      for i in range(n):
          for j in range(i + 1, n):
              total_sum += distance_matrix[i, j]

      mean = total_sum / total_permiplet_pairs
    else:
      mean = distance_matrix[0, 0]

    return {
        "TSP_tour": TSP_tour,
        "TSP_steps": TSP_tour_steps,
        "data_perimeter": perimeter,
        "mean": mean,
        "permiplets": n
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
    df['P_p'] = df['data_perimeter'] / df['permiplets']

    print(df)

    band_groups = group_by_band(df)
    results = []

    for radius, rows in band_groups.items():
        if len(rows) < 2:
            continue  # skip small bands

        band_df = pd.DataFrame(rows)
        perimeter_sum = band_df['P_p'].sum()
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


if args.single:
  geo=data_action_tuples(args.single, role_dict,False)
  print("number of permiplets:",geo['permiplets'])
  print("data perimeter:",geo['data_perimeter'])
  if args.verbose:
    print("TSP tour:")
    for o in zip(geo['TSP_tour'],geo['TSP_steps']):
      print(o)
  sys.exit()

# Generate CSV output
rows = []
for pid, blast_radius in brd.items():
    geo = data_action_tuples(pid, role_dict,False)
    rows.append({
        "pid": pid,
        "blast_radius": float(blast_radius),
        "permiplets": int(geo['permiplets']),
        "data_perimeter": float(geo['data_perimeter']),
        "mean": float(geo['mean'])
    })

# Create DataFrame
df = pd.DataFrame(rows)

# Sort by blast_radius and data_perimeter, both descending
df = df.sort_values(by=["blast_radius", "data_perimeter"], ascending=[False, False])
df.to_csv(f"perimeter_{timestamp}.csv", index=False)

