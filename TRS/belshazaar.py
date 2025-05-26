#!/usr/bin/python3
from z3 import *
import argparse, random
import sys,os,json,re
from collections import defaultdict


parser = argparse.ArgumentParser()
parser.add_argument('--save', action="store_true", required=False, help='saves proof to file')
parser.add_argument('--show', action="store_true", required=False, help='displays proof to screen')
parser.add_argument('--verbose', action="store_true", required=False, help='prints debugging info to stdout')
args = parser.parse_args()

if os.path.exists('dataActions.txt'):
  with open('dataActions.txt', 'r') as file:
    S_list = [('a',line.strip()) for line in file if line.strip()]
else:
  print("ERROR. Run silhouette and extractDataActions.sh first")
  sys.exit()

print(len(S_list),"pairs to analyze")

if args.verbose:
  for item in S_list:
    print(item[1])

random.shuffle(S_list)

# ───────────────────────────────────────────────────────────
'''
S_list = [
    ('a', 'Something/*/read'),
    ('a', '/write'),
    ('b', '/read*'),
    ('c', '/delete'),
    ('c', '*/action'),
    ('d', 'misc'),
    ('e', 'resource.provider1/something/write'),
    ('e', 'resource.provider2/somethingelse/delete'),
    ('f', 'rp.0001/*'),
    ('g', '*'),
    ('g', '/read')
]
'''

# ───────────────────────────────────────────────────────────────
# Rewrite rules

def unary_nf(scope, perm):
    """Unary rewrite: normalize permissions based on suffix."""
    if perm.endswith('/read'):
        return scope, 'R'
    if perm.endswith('/write') or perm.endswith('/delete'):
        return scope, 'W'
    if perm.endswith('/action') or perm.endswith('*'):
        return scope, 'S'
    return scope, perm  # unchanged

def binary_nf(p1, p2):
    """Binary rewrite rules, including absorption."""
    (s1, t1), (s2, t2) = p1, p2

    if s1 == s2:
        # R + W → S
        if {t1, t2} == {'R', 'W'}:
            return (s1, 'S'), (s2, 'S')
        # Absorption: S + R/W → S + ⊥ (means: absorb the R/W)
        if t1 == 'S' and t2 in {'R', 'W'}:
            return (s1, 'S'), None
        if t2 == 'S' and t1 in {'R', 'W'}:
            return None, (s2, 'S')

    return None  # no rule fired

# ───────────────────────────────────────────────────────────────
# Saturation loop

current = list(S_list)

while True:
    unary_ops = [
        i for i, (s, p) in enumerate(current)
        if unary_nf(s, p) != (s, p)
    ]

    binary_ops = []
    for i in range(len(current)):
        for j in range(i + 1, len(current)):
            res = binary_nf(current[i], current[j])
            if res is not None:
                binary_ops.append((i, j))

    if not unary_ops and not binary_ops:
        break

    if unary_ops and (not binary_ops or random.random() < 0.5):
        i = random.choice(unary_ops)
        current[i] = unary_nf(*current[i])
    else:
        i, j = random.choice(binary_ops)
        r1, r2 = binary_nf(current[i], current[j])
        # Apply rewrite, using None to mean “delete”
        new_current = []
        for k, item in enumerate(current):
            if k == i and r1 is not None:
                new_current.append(r1)
            elif k == j and r2 is not None:
                new_current.append(r2)
            elif k != i and k != j:
                new_current.append(item)
        current = new_current

# ───────────────────────────────────────────────────────────────
# Partition result into equivalence classes

classes = defaultdict(list)
for original in S_list:
    # Find NF for original in current set
    scope_o, _ = original
    for scope_c, perm_c in current:
        if scope_c == scope_o:
            classes[(scope_c, perm_c)].append(original)
            break

# ───────────────────────────────────────────────────────────────
# Show results and anomalies

print("=== Final Equivalence Classes ===")
for nf, members in classes.items():
    print(f"NF {nf}: {members}")

allowed = {'S', 'R', 'W'}
anomalies = {nf: ms for nf, ms in classes.items() if nf[1] not in allowed}

if anomalies:
    print("\n=== Anomalies: non-SRW partitions ===")
    for nf, group in anomalies.items():
        print(f"NF {nf} ← {group}")
else:
    print("\nAll normal forms are within {S, R, W}.")

