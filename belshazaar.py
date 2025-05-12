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

ImpactPair = Datatype('ImpactPair')
ImpactPair.declare('mkImpactPair', ('scope', StringSort()), ('impact', IntSort()))
ImpactPair = ImpactPair.create()
mkImpactPair, scope, impact = ImpactPair.mkImpactPair, ImpactPair.scope, ImpactPair.impact


# Create Z3 terms with consistent pairing
S_z3_pairs = [(mkPair(StringVal(scope_), StringVal(perm_)), scope_, perm_) for (scope_, perm_) in S_list]
S_z3 = [z for (z, _, _) in S_z3_pairs]

S2_z3_pairs= []

# Declare normal form function
NF = Function('NF', Pair, Pair)
NFI = Function('NFI', ImpactPair, ImpactPair)
solver = Solver()

# Idempotence
x = Const('x', Pair)
xi = Const('xi', ImpactPair)
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
    coarse_partition=rep in ['R','W','S']
    print("coarse?",coarse_partition)
    if coarse_partition:
      solver=Solver()
      solver.add(ForAll([xi], NFI(NFI(xi)) == NFI(xi)))
      # Unary rule: if perm ends with 'S', normalize to (scope, '2')
      for zterm, sc, im in S_z3_pairs:
        if pr.endswith('S'):
            print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='2')")
            print(f"consuming {sc},{pr}")
            rep = mkImpactPair(StringVal(sc), IntVal(2))
            constraints.append((zterm,rep))
            new_reps.add((rep, sc, 2))
            consumed.add((zterm,sc,pr))
      S2_z3_pairs.extend(new_reps)
      S2_z3_pairs = [
          triple for triple in S2_z3_pairs
          if triple not in consumed
      ]
      new_reps = set()
      # Unary rule: if perm ends with 'R' or 'W', normalize to (scope, '1')
      for zterm, sc, pr in S_z3_pairs:
        if pr.endswith('R') or pr.endswith('W'):
            print(f"Unary rule applied: Term with perm '{pr}' is rewritten to (scope='{sc}', perm='1')")
            print(f"consuming {sc},{pr}")
            rep = mkImpactPair(StringVal(sc), IntVal(1))
            constraints.append((zterm,rep))
            new_reps.add((rep, sc, 1))
            consumed.add((zterm,sc,pr))
      S2_z3_pairs.extend(new_reps)
      S2_z3_pairs = [
          triple for triple in S2_z3_pairs
          if triple not in consumed
      ]
      new_reps = set()
      # Unary rule: if perm ends with 'A', drop 
      for zterm, sc, pr in S_z3_pairs:
        if pr.endswith('A'):
            print(f"Unary rule applied: dropping term with perm '{pr}'")
            print(f"consuming {sc},{pr}")
            consumed.add((zterm,sc,pr))
      new_reps = set()
      #for p in S_z3_pairs:
      #  print("...",p)
      formula=True
      for (_,sc,im) in S2_z3_pairs:
        formula=And(formula,im>0)
      solver.add(formula)
      print("\nSolver constraints before solving:")
      for sa in solver.assertions():
        print(sa)
        print()
      if solver.check() == sat:
        print("sat")
        m = solver.model()
        parts = {}
        for zterm, sc, pr in S2_z3_pairs:
          nf = m.evaluate(NFI(zterm), model_completion=True)
          parts.setdefault(str(pr), []).append((sc, pr))
        print("Partition:")
        for rep, elems in parts.items():
          print(f"  {rep} → {elems}")
          print()
      else:
        print("unsat")
else:
    print("UNSAT")
