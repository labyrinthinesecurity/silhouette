#!/usr/bin/python3
from z3 import *
import argparse, random
import sys,os,json,re
from collections import defaultdict


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
      matches = re.findall(r'/[\w\d.-]+', perm)
      perm = matches[-1] if matches else perm
      if matches:
        pass
      else:
        S_list.append((scope,perm))

S_list.append(("ab","Something/*/read"))
S_list.append(("ab","Something/*/write"))
for item in S_list:
  print(item[1])
random.shuffle(S_list)

# Declare pair sort
Pair = Datatype('Pair')
Pair.declare('mkPair', ('scope', StringSort()), ('perm', StringSort()))
Pair = Pair.create()
mkPair = Pair.mkPair
scope = Pair.scope
perm = Pair.perm

any_char = Range('\x00', '\x7F')

# Build the Z3 constants for S_list pairs
S0 = [ mkPair(StringVal(s), StringVal(p)) for s,p in S_list ]

U_seen = set()
nf = Const("nf", Pair)
x = Const("x", Pair)

unary_rules = Or(
        And(SuffixOf(StringVal("/read"), perm(x)),
            nf == mkPair(scope(x), StringVal("R"))),
        And(SuffixOf(StringVal("/write"), perm(x)),
            nf == mkPair(scope(x), StringVal("W"))),
        And(SuffixOf(StringVal("*"), perm(x)),
            nf == mkPair(scope(x), StringVal("S"))),
        And(SuffixOf(StringVal("/delete"), perm(x)),
            nf == mkPair(scope(x), StringVal("W"))),
        And(SuffixOf(StringVal("/action"), perm(x)),
            nf == mkPair(scope(x), StringVal("A")))
)

# First TRS saturation engine
while True:
    solver = Solver()
    #solver.set("timeout", 50000)

    # Let x come from the input set
    solver.add(Or([x == t for t in S0]))
    solver.add(unary_rules)

    # block already seen unary NFs
    for (s_u,p_u) in U_seen:
        solver.add(nf != mkPair(StringVal(s_u), StringVal(p_u)))
    if solver.check() != sat:
        break
    m = solver.model()
    v = m.eval(nf, model_completion=True)
    u = (m.eval(scope(v)).as_string(), m.eval(perm(v)).as_string())
    U_seen.add(u)

# now U_seen holds all unary normal forms
print("Unary NFs:", U_seen)

# Build the Z3 constants for U_seen pairs
S1 = [ mkPair(StringVal(s), StringVal(p)) for (s,p) in U_seen ]

# Binary saturation
B_seen = set()
B_phi  = BoolVal(True)
x1 = Const("x1", Pair)
x2 = Const("x2", Pair)

# Binary rules
binary_rules = Or(
    And(
    scope(x1) == scope(x2),
    Or(
            And(perm(x1) == StringVal("R"), perm(x2) == StringVal("W")),
            And(perm(x1) == StringVal("W"), perm(x2) == StringVal("R"))
        ),
        nf == mkPair(scope(x1), StringVal("S"))
    ),
    And(
    scope(x1) == scope(x2),
    Or(
            And(perm(x1) == StringVal("R"), perm(x2) == StringVal("S")),
            And(perm(x1) == StringVal("S"), perm(x2) == StringVal("R"))
        ),
        nf != mkPair(scope(x1), StringVal("R"))
    )
)

while True:
    s = Solver()
    s.add(B_phi)
    s.add(Or([x1 == t1 for t1 in S1]))
    s.add(Or([x2 == t2 for t2 in S1]))
    s.add(binary_rules)
    # block seen binary NFs
    for (s_b,p_b) in B_seen:
        s.add(nf != mkPair(StringVal(s_b), StringVal(p_b)))
    if s.check() != sat:
        break
    m = s.model()
    v = m.eval(nf, model_completion=True)
    b = (m.eval(scope(v)).as_string(), m.eval(perm(v)).as_string())
    B_seen.add(b)
print("Binary NFs:", B_seen)

# Track terms that reduce to a binary NF
B_nf_to_terms = defaultdict(set)

for (scope_b, perm_b) in B_seen:
    target_nf = mkPair(StringVal(scope_b), StringVal(perm_b))
    for (s0, p0) in U_seen:
        t0 = mkPair(StringVal(s0), StringVal(p0))
        check_solver = Solver()
        x1_check = Const("x1", Pair)
        x2_check = Const("x2", Pair)
        nf_check = Const("nf", Pair)

        check_solver.add(x1_check == t0)
        check_solver.add(Or([x2_check == t for t in S1]))  # Second pair from S1
        check_solver.add(scope(x1_check) == scope(x2_check))
        check_solver.add(Or(
            And(perm(x1_check) == StringVal("R"), perm(x2_check) == StringVal("W")),
            And(perm(x1_check) == StringVal("W"), perm(x2_check) == StringVal("R"))
        ))
        check_solver.add(nf_check == mkPair(scope(x1_check), StringVal("S")))
        check_solver.add(nf_check == target_nf)

        if check_solver.check() == sat:
            B_nf_to_terms[(scope_b, perm_b)].add((s0, p0))

print("\nEquivalence classes from binary TRS:")
for nf_key, terms in B_nf_to_terms.items():
    print(f"  {nf_key} ← {sorted(terms)}")

