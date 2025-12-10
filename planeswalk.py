#!/usr/bin/python3
import numpy as np
import pandas as pd
import argparse
import sys

parser = argparse.ArgumentParser(description='Read data as of a specific date.')
parser.add_argument('--asof', type=str, required=True, help='Date in YYYY-MM-DD format')
parser.add_argument('--show-dominance', action='store_true', help='Print dominance matrix and CP/DP stats')
args = parser.parse_args()

pd.set_option('display.max_rows', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.max_columns', None)

df_nhis = pd.read_csv(f'sorted_NHIs_{args.asof}.csv')
df_fibers = pd.read_csv(f'sorted_fibers_{args.asof}.csv')

filtered_pop = df_fibers.groupby('fiber_id')['pid'].transform('count')
df_fibers['pop'] = filtered_pop

unique_fiber_count = df_fibers['fiber_id'].nunique()

# sort by blast radius to make sure that we keep the highest score in drop_duplicates below (since fibration doesnt preserve blast raddi, we must take the highest one to be conservative)
df_fibers = df_fibers.sort_values(by='blast_radius', ascending=False)
df_fibers = df_fibers.drop_duplicates(subset='fiber_id', keep='first')

def map_blast_to_kappa(df,
                       war_col='WAR',
                       blast_col='blast_radius',
                       depth_col='depth_d',
                       sublevel_col='delta_sublevel',
                       kappa_col='kappa_equiv',
                       i_col='i_factor',
                       bigint_guardrail=23,
                       fallback_kappa_for_deep=2,
                       tol=1e-8):
    """
    Vectorized mapping:
      - computes delta = -log2(blast_radius)  (sublevel)
      - rounds to nearest integer with tolerance and flags suspicious rows
      - computes depth d = sublevel // 2
      - infers i = 1 if sublevel odd else 2
      - maps depth -> kappa_equiv with guardrail -> 0 if depth >= bigint_guardrail
      - returns copy of df with new columns and a 'mapping_issue' boolean
    """

    df = df.copy()

    # 1) Safety & clamp
    br = df[blast_col].astype(float).copy()
    invalid_mask = br.isna() | (br <= 0) | (br > 1)

    # For numeric stability, avoid log2(0) by setting invalid to NaN and handling later
    br_nonzero = br.replace(0, np.nan)

    # 2) compute delta (sublevel float)
    with np.errstate(divide='ignore', invalid='ignore'):
        delta_float = -np.log2(br_nonzero)

    # Where br was invalid (NaN, <=0), set delta to a large sentinel: 2*bigint_guardrail
    sentinel = 2 * bigint_guardrail
    delta_float = delta_float.fillna(sentinel)

    # 3) round to nearest integer and record deviation
    delta_sublevel = np.rint(delta_float).astype(int)
    deviation = np.abs(delta_float - delta_sublevel)

    # 4) flag suspicious rows (floating noise or non exact)
    suspicious = (deviation > tol) | invalid_mask

    # 5) get depth and i
    depth_d = (delta_sublevel // 2).astype(int)
    i_factor = np.where(delta_sublevel % 2 == 1, 1, 2)

    # 6) depth -> kappa mapping (tune these values to your WAR ladder)
    depth_to_kappa = {
        0: 900,   # tenant admin
        1: 800,   # management group admin
        2: 700,   # subscription admin
        3: 407,   # subscription W+R
        4: 306,   # resource group W+R
        5: 204,   # resource W+R
        6: 102,   # subresource W+R
        7: 2      # subresource R only (and deeper fallback)
    }

    # Map; depths above highest known depth get fallback_kappa_for_deep (if < bigint_guardrail)
    kappa_eq = depth_d.map(depth_to_kappa)

    # Fill missing depth mappings with 0 
    kappa_eq = kappa_eq.fillna(0).astype(int)

    # Apply guardrail: if depth >= bigint_guardrail -> set kappa to 0
    kappa_eq = kappa_eq.where(depth_d < bigint_guardrail, other=0)

    # 7) produce final columns
    df[sublevel_col] = delta_sublevel
    df[depth_col] = depth_d
    df[i_col] = i_factor
    df[kappa_col] = kappa_eq
    df['mapping_suspicious'] = suspicious

    # optional: computed ctrl_max boolean comparing WAR > kappa_equiv
    df['ctrl_max_flag'] = (df[war_col] > df[kappa_col]) & (~df['mapping_suspicious'])

    return df

df = map_blast_to_kappa(df_nhis, war_col='WAR', blast_col='blast_radius', depth_col='depth_d', sublevel_col='delta_sublevel', kappa_col='kappa_equiv', i_col='i_factor', bigint_guardrail=23, fallback_kappa_for_deep=2, tol=1e-6)

if args.show_dominance:
    bins = range(0, int(df['WAR'].max()) + 50, 50)
    df['binned_WAR'] = pd.cut(df['WAR'], bins=bins)
    war_greater_counts = []
    kappa_equiv_greater_counts = []
    bin_labels = []

    # Iterate over each bin
    for bin_label, group in df.groupby('binned_WAR', observed=True):
        war_greater_count = (group['WAR'] > group['kappa_equiv']).sum()
        kappa_equiv_greater_count = (group['kappa_equiv'] > group['WAR'] ).sum()
        war_greater_counts.append(war_greater_count)
        kappa_equiv_greater_counts.append(kappa_equiv_greater_count)
        bin_labels.append(int(bin_label.right))  # upper bound

    result_df = pd.DataFrame({
        'binned_WAR': bin_labels,
        'WAR > kappa_equiv': war_greater_counts,
        'kappa_equiv > WAR ': kappa_equiv_greater_counts
    }).reset_index(drop=True)

    controlplane_dominance = len(df[(df['WAR'] > df["kappa_equiv"])])
    dataplane_dominance = len(df[df['WAR']  < df["kappa_equiv"]])

    print(result_df[["binned_WAR", "WAR > kappa_equiv", "kappa_equiv > WAR "]])
    print(f"DP dominance {dataplane_dominance}")
    print(f"CP dominance {controlplane_dominance}")
    sys.exit()

min_WAR = df['WAR'].min()
max_WAR = df['WAR'].max()

# Linearize 'WAR' to [0.0, 1000.0]
df['linearized_WAR'] = 1000 * (df['WAR'] - min_WAR) / (max_WAR - min_WAR)
df['linearized_WAR'] = df['linearized_WAR']**2

min_ke = df['kappa_equiv'].min()
max_ke = df['kappa_equiv'].max()

# Linearize 'kappa_equiv' to [0.0, 1000.0]
df['linearized_ke'] = 1000 * (df['kappa_equiv'] - min_ke) / (max_ke - min_ke)
df['linearized_ke'] = df['linearized_ke']**2

df['combined'] = df['linearized_ke'] + df['linearized_WAR']
df['combined'] = df['combined'].round().astype(int)

# Filter counterexamples
#counterexamples = df[df['kappa_equiv'] > df['WAR']]
counterexamples = df

counterexamples_summary = counterexamples[['pid','name', 'kappa_equiv', 'WAR', 'combined']]

counterexamples_with_fiber = counterexamples_summary.merge(df_fibers[['pid', 'fiber_id', 'pop']], on='pid', how='right')

counterexamples_with_fiber = counterexamples_with_fiber.drop(columns=['pid'])

unique_fiber_count = counterexamples_with_fiber['fiber_id'].nunique()

counterexamples_with_fiber = counterexamples_with_fiber.reset_index(drop=True)

# Group by fiber_id and take the first row to deduplicate
counterexamples_dedup = counterexamples_with_fiber.groupby('fiber_id', as_index=False).first()

#counterexamples_dedup['score'] = counterexamples_dedup['WAR'] + counterexamples_dedup['kappa_equiv']

counterexamples_dedup = counterexamples_dedup.sort_values(by=['combined', 'WAR', 'kappa_equiv', 'pop', 'fiber_id'],ascending=[False,False,False,False,True])

counterexamples_dedup = counterexamples_dedup.reset_index(drop=True)
counterexamples_dedup.index = counterexamples_dedup.index + 1  # Start index from 1

counterexamples_dedup['cum_pop'] = counterexamples_dedup['pop'].cumsum()
counterexamples_dedup['percentile'] = counterexamples_dedup['combined'].rank(pct=True) * 100

counterexamples_dedup['fiber_id'] = counterexamples_dedup['fiber_id'].str[:12]


counterexamples_dedup = counterexamples_dedup.drop(columns=['combined'])

print(counterexamples_dedup.to_string(index=True, line_width=None, justify='left'))
num_rows = counterexamples_dedup.shape[0]
num_nhis = df_fibers['pop'].sum()
print(f"Number of fibers: {num_rows}")
print(f"Number of NHIs: {num_nhis}")
