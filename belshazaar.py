#!/usr/bin/python3

import argparse
from z3 import *
import sys,os,json

parser = argparse.ArgumentParser()
parser.add_argument('--pid', required=True, type=str, help='verify dataAction structure of a principal')
args = parser.parse_args()

if os.path.exists('spnperms.json'):
  with open('spnperms.json','r') as file:
    spn=json.load(file)

S_list=[]

if spn[args.pid]['dataActions']:
  for scope in spn[args.pid]['dataActions_dict']:
    for perm in spn[args.pid]['dataActions_dict'][scope]:
      S_list.append((scope,perm))
#print(S_list)

# Pair datatype: (scope, perm)
Pair = Datatype('Pair')
Pair.declare('mkPair', ('scope', StringSort()), ('perm', StringSort()))
Pair = Pair.create()
mkPair, scope, perm = Pair.mkPair, Pair.scope, Pair.perm

# Create Z3 terms with consistent pairing
S_z3_pairs = [(mkPair(StringVal(scope_), StringVal(perm_)), scope_, perm_) for (scope_, perm_) in S_list]
S_z3 = [z for (z, _, _) in S_z3_pairs]

# Declare normal form function
NF = Function('NF', Pair, Pair)
solver = Solver()

# Idempotence
x = Const('x', Pair)
solver.add(ForAll([x], NF(NF(x)) == NF(x)))

constraints = []
new_reps = set()
consumed = set()

# Unary rule: if perm ends with '*', normalize to (scope, 'S')
for zterm, sc, pr in S_z3_pairs:
    if pr.endswith('*'):
        print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='S')")
        print(f"consuming {sc},{pr}")
        rep = mkPair(StringVal(sc), StringVal('S'))
        constraints.append((zterm,rep))
        new_reps.add((rep, sc, 'S'))
        consumed.add((zterm,sc,pr))

S_z3_pairs.extend(new_reps)
S_z3_pairs = [
          triple for triple in S_z3_pairs
          if triple not in consumed
]
new_reps = set()

# Unary rule: if perm ends with 'read', normalize to (scope, 'R')
for zterm, sc, pr in S_z3_pairs:
    if pr.endswith('/read'):
        print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='R')")
        print(f"consuming {sc},{pr}")
        rep = mkPair(StringVal(sc), StringVal('R'))
        constraints.append((zterm,rep))
        new_reps.add((rep, sc, 'R'))
        consumed.add((zterm,sc,pr))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
          triple for triple in S_z3_pairs
          if triple not in consumed
]
new_reps = set()

# Unary rule: if perm ends with 'action', drop
for zterm, sc, pr in S_z3_pairs:
    if pr.endswith('/action'):
        print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='R')")
        print(f"consuming {sc},{pr}")
        consumed.add((zterm,sc,pr))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
          triple for triple in S_z3_pairs
          if triple not in consumed
]
new_reps = set()


# Unary rule: if perm ends with 'delete' or 'write', normalize to (scope, 'W')
for zterm, sc, pr in S_z3_pairs:
    if pr.endswith('/write') or pr.endswith('/delete'):
        print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='W')")
        rep = mkPair(StringVal(sc), StringVal('W'))
        constraints.append((zterm,rep))
        new_reps.add((rep, sc, 'W'))
        consumed.add((zterm,sc,pr))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
          triple for triple in S_z3_pairs
          if triple not in consumed
]
new_reps = set()

# Binary rule: if same scope and perms are 'R' and 'W' → normalize both to (scope, 'S')
for i in range(len(S_z3_pairs)):
    for j in range(i + 1, len(S_z3_pairs)):
        zi, si, pi = S_z3_pairs[i]
        zj, sj, pj = S_z3_pairs[j]
        if (si == sj) and ({pi, pj} == {'R', 'W'} or {pi, pj} == {'W', 'R'}):
            print(f"Binary rule applied: Pair {zi} and {zj} are rewritten to (scope='{si}', perm='S')")
            rep = mkPair(StringVal(si), StringVal('S'))
            new_reps.add((rep, si, 'S'))
            constraints.append((zi, rep))
            constraints.append((zj, rep))
            consumed.add((zi,si,pi))
            consumed.add((zj,sj,pj))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
            triple for triple in S_z3_pairs
              if triple not in consumed
]
new_reps = set()

# Binary rule: if same scope and perms are 'S' and 'R' → normalize both to (scope, 'S')
for i in range(len(S_z3_pairs)):
    for j in range(i + 1, len(S_z3_pairs)):
        zi, si, pi = S_z3_pairs[i]
        zj, sj, pj = S_z3_pairs[j]
        if (si == sj) and ({pi, pj} == {'R', 'S'} or {pi, pj} == {'S', 'R'}):
            print(f"Binary rule applied: Pair {zi} and {zj} are rewritten to (scope='{si}', perm='S')")
            rep = mkPair(StringVal(si), StringVal('S'))
            new_reps.add((rep, si, 'S'))
            constraints.append((zi, rep))
            constraints.append((zj, rep))
            consumed.add((zi,si,pi))
            consumed.add((zj,sj,pj))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
            triple for triple in S_z3_pairs
              if triple not in consumed
]
new_reps = set()

# Binary rule: if same scope and perms are 'S' and 'W' → normalize both to (scope, 'S')
for i in range(len(S_z3_pairs)):
    for j in range(i + 1, len(S_z3_pairs)):
        zi, si, pi = S_z3_pairs[i]
        zj, sj, pj = S_z3_pairs[j]
        if (si == sj) and ({pi, pj} == {'W', 'S'} or {pi, pj} == {'S', 'W'}):
            print(f"Binary rule applied: Pair {zi} and {zj} are rewritten to (scope='{si}', perm='S')")
            rep = mkPair(StringVal(si), StringVal('S'))
            new_reps.add((rep, si, 'S'))
            constraints.append((zi, rep))
            constraints.append((zj, rep))
            consumed.add((zi,si,pi))
            consumed.add((zj,sj,pj))
S_z3_pairs.extend(new_reps)
S_z3_pairs = [
            triple for triple in S_z3_pairs
              if triple not in consumed
]
new_reps = set()


# **Prune** collected constraints to drop any whose LHS was consumed
valid_terms = {t for (t, _, _) in S_z3_pairs}
#print("valid terms")
#for v in valid_terms:
#  print(valid_terms)
#print()

pruned = [(t, r) for (t, r) in constraints if t in valid_terms]

# Now add **only** these pruned constraints to the solver
#print("pruned:")
for (t, r) in pruned:
#  print(t,r)
  solver.add(NF(t) == r)

print("\nSolver constraints before solving:")
for sa in solver.assertions():
  print(sa)
  print()

# Solve and extract normal forms
if solver.check() == sat:
    m = solver.model()
    parts = {}
    for zterm, sc, pr in S_z3_pairs:
        nf = m.evaluate(NF(zterm), model_completion=True)
        parts.setdefault(str(pr), []).append((sc, pr))

    print("Partition:")
    for rep, elems in parts.items():
        print(f"  {rep} → {elems}")
        print()
else:
    print("UNSAT")
