#!/usr/bin/python3
import pandas as pd
import numpy as np
from ultrametry import *

BIGINT=28
input_path="sorted_NHIs_2025-07-21.csv"
df = pd.read_csv(input_path)
# Clean data
df = df[df["WAR"] >= 0]
#df["blast_radius"] = df["blast_radius"].fillna(0.0)
df = df.dropna(subset=["blast_radius"])
df = df[df["type"].notnull()]
# Compute log10(WAR)/3
#df["log10_WAR/3"] = (1 / 3) * np.log10(1.0 + df["WAR"])
df["log10_WAR/3"] = 1.6 * np.power(df["WAR"]/1000,4)

df["newblast"] = -np.log2(df["blast_radius"])
df["newblast"] = df["newblast"].replace([np.inf, -np.inf], BIGINT)
df["newblast"] = df["newblast"].apply(lambda val: 500 if 0 <= val <= 7 else val)
df["newblast"] = df["newblast"].apply(lambda val: 400 if 8 <= val <= 9 else val)
df["newblast"] = df["newblast"].apply(lambda val: 300 if 10 <= val <= 11 else val)
df["newblast"] = df["newblast"].apply(lambda val: 200 if 12 <= val <= 13 else val)
df["newblast"] = df["newblast"].apply(lambda val: 100 if 14 <= val <= 15 else val)
df["newblast"] = df["newblast"].apply(lambda val: 0 if 16 <= val <= BIGINT else val)

#controlplane_dominance = len(df[(df['log10_WAR/3'] > df["blast_radius"])])
#dataplane_dominance = len(df[df['log10_WAR/3'] < df["blast_radius"]])

controlplane_dominance = len(df[(df['WAR'] > df["newblast"])])
dataplane_dominance = len(df[df['WAR'] < df["newblast"]])

print(f"DP dominance {dataplane_dominance}")
print(f"CP dominance {controlplane_dominance}")

plot_crossplane(input_path)

#print(df["WAR"].describe())
#print(df["log10_WAR/3"].describe())
print(df["blast_radius"].describe())
print(df["newblast"].describe())
