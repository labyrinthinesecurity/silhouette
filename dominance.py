#!/usr/bin/python3
import numpy as np
import pandas as pd
import sys

pd.set_option('display.max_rows', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.max_columns', None)

BIGINT=21
input_path="sorted_NHIs_2025-12-03.csv"
raw_df = pd.read_csv(input_path)

df_biomes = pd.read_csv('sorted_biomes_2025-12-03.csv')

#print("orig",len(df_biomes))
df_biomes = df_biomes[df_biomes['name'].str.len() < 64]
#print("filtered",len(df_biomes))
filtered_pop = df_biomes.groupby('biome_id')['pid'].transform('count')
df_biomes['filtered_pop'] = filtered_pop

unique_biome_count = df_biomes['biome_id'].nunique()
#print(f"Number of unique biome_id values: {unique_biome_count}")

df_biomes = df_biomes.drop_duplicates(subset='biome_id', keep='first')

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

df = map_blast_to_kappa(raw_df, war_col='WAR', blast_col='blast_radius', depth_col='depth_d', sublevel_col='delta_sublevel', kappa_col='kappa_equiv', i_col='i_factor', bigint_guardrail=23, fallback_kappa_for_deep=2, tol=1e-6)

#print("suspicious",df['mapping_suspicious'].sum())

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

print(result_df[["binned_WAR","WAR > kappa_equiv","kappa_equiv > WAR "]])

controlplane_dominance = len(df[(df['WAR'] > df["kappa_equiv"])])
dataplane_dominance = len(df[df['WAR']  < df["kappa_equiv"]])

print(f"DP dominance {dataplane_dominance}")
print(f"CP dominance {controlplane_dominance}")

# Filter counterexamples
#counterexamples = df[df['kappa_equiv'] > df['WAR']]
counterexamples = df

counterexamples_summary = counterexamples[['pid','name', 'kappa_equiv', 'WAR']]

counterexamples_with_biome = counterexamples_summary.merge(df_biomes[['pid', 'biome_id', 'filtered_pop']], on='pid', how='right')

counterexamples_with_biome = counterexamples_with_biome.drop(columns=['pid'])

unique_biome_count = counterexamples_with_biome['biome_id'].nunique()
print(f"JOIN Number of unique biome_id values: {unique_biome_count}")
print(f"Rows with NaN biome_id: {counterexamples_with_biome['biome_id'].isna().sum()}")

counterexamples_with_biome = counterexamples_with_biome.reset_index(drop=True)

# Group by biome_id and take the first row to deduplicate
counterexamples_dedup = counterexamples_with_biome.groupby('biome_id', as_index=False).first()


counterexamples_dedup = counterexamples_dedup.sort_values(by=['WAR', 'filtered_pop', 'kappa_equiv', 'biome_id'],ascending=[False,False,False,True])

counterexamples_dedup['cum_filtered_pop'] = counterexamples_dedup['filtered_pop'].cumsum()

counterexamples_dedup['biome_id'] = counterexamples_dedup['biome_id'].str[:12]

print(counterexamples_dedup.to_string(index=False, line_width=None, justify='left'))
num_rows = counterexamples_dedup.shape[0]
num_nhis = df_biomes['filtered_pop'].sum()
print(f"Number of fibers: {num_rows}")
print(f"Number of filtered NHIs: {num_nhis}")
