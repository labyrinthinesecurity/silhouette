#!/usr/bin/python3
from z3 import *
import argparse, random
import sys,os,json,re
from collections import defaultdict


parser = argparse.ArgumentParser()
parser.add_argument('--pid', required=True, type=str, help='verify dataAction structure of a principal')
parser.add_argument('--save', action="store_true", required=False, help='saves proof to file')
parser.add_argument('--show', action="store_true", required=False, help='displays proof to screen')
parser.add_argument('--verbose', action="store_true", required=False, help='prints debugging info to stdout')
args = parser.parse_args()

if os.path.exists('spnperms.json'):
  with open('spnperms.json','r') as file:
    spn=json.load(file)
else:
  print("ERROR. Run silhouette first")
  sys.exit()

S_list=[]

if args.pid not in spn:
  print("ERROR. This SPN doesnt exist")
  sys.exit()

if 'dataActions' not in spn[args.pid]:
  print("INFO. This SPN has no data actions")
  sys.exit()

if spn[args.pid]['dataActions']:
  for scope in spn[args.pid]['dataActions_dict']:
    for perm in spn[args.pid]['dataActions_dict'][scope]:
      matches = re.findall(r'/[\w\d.-]+', perm)
      condensed_perm = matches[-1] if matches else perm
      if matches:
        S_list.append((scope,condensed_perm))
      else:
        S_list.append((scope,perm))

'''
S_list.append(("ab","Something/*/read"))
S_list.append(("ab","Something/*/write"))
S_list.append(("c","Something/*/read"))
S_list.append(("c","Something/*/action"))
'''

print(len(S_list),"pairs to analyze for SPN",args.pid)

if args.verbose:
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
TRS2_pairs = [ mkPair(StringVal(s), StringVal(p)) for s,p in S_list ]

TRS1_seen = set()
nf = Const("nf", Pair)
x = Const("x", Pair)
TRS1_nf_to_terms = defaultdict(set)

TRS1_rules = Or(
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
    solver.add(Or([x == t for t in TRS2_pairs]))
    solver.add(TRS1_rules)

    # block already seen TRS1 NFs
    for (s_u,p_u) in TRS1_seen:
        solver.add(nf != mkPair(StringVal(s_u), StringVal(p_u)))
    if solver.check() != sat:
        break
    m = solver.model()
    v = m.eval(nf, model_completion=True)
    u = (m.eval(scope(v)).as_string(), m.eval(perm(v)).as_string())
    TRS1_seen.add(u)
    # Track all original terms that rewrite to this NF u
    for t in TRS2_pairs:
      s_check = Solver()
      s_check.add(x == t)
      s_check.add(TRS1_rules)
      s_check.add(nf == mkPair(StringVal(u[0]), StringVal(u[1])))
      if s_check.check() == sat:
        scope_t = m.eval(scope(t)).as_string()
        perm_t = m.eval(perm(t)).as_string()
        TRS1_nf_to_terms[u].add((scope_t, perm_t))


# now TRS1_seen holds all TRS1 normal forms
if args.show:
  print("TRS1 NFs:", TRS1_seen)

# Build the Z3 constants for TRS1_seen pairs
TRS2_pairs = [ mkPair(StringVal(s), StringVal(p)) for (s,p) in TRS1_seen ]

# TRS2 saturation
TRS2_seen = set()
x1 = Const("x1", Pair)
x2 = Const("x2", Pair)

# TRS2 rules
TRS2_rules = Or(
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
    ),
    And(
    scope(x1) == scope(x2),
    Or(
            And(perm(x1) == StringVal("W"), perm(x2) == StringVal("S")),
            And(perm(x1) == StringVal("S"), perm(x2) == StringVal("W"))
        ),
        nf != mkPair(scope(x1), StringVal("W"))
    )
)

while True:
    s = Solver()
    # Let x1 and x2 range over all previously seen TRS1 NFs (TRS2_pairs),
    # representing potential inputs to the binary rules
    s.add(Or([x1 == t1 for t1 in TRS2_pairs]))
    s.add(Or([x2 == t2 for t2 in TRS2_pairs]))
    s.add(TRS2_rules)
    # block seen TRS NFs
    for (s_b,p_b) in TRS2_seen:
        s.add(nf != mkPair(StringVal(s_b), StringVal(p_b)))
    # If no more rewrites are found, saturation is complete
    if s.check() != sat:
        break
    m = s.model()
    v = m.eval(nf, model_completion=True)
    b = (m.eval(scope(v)).as_string(), m.eval(perm(v)).as_string())
    TRS2_seen.add(b)

if args.show:
  print("TRS2 NFs:", TRS2_seen)


# Track terms that reduce to a TRS2 NF
TRS2_nf_to_terms = defaultdict(set)

# Loop: Which TRS1 normal forms are absorbed by TRS2 rules?
# For each NF (normal form) found by TRS2
for (scope_b, perm_b) in TRS2_seen:
    # Construct the Z3 Pair constant for the target NF
    target_nf = mkPair(StringVal(scope_b), StringVal(perm_b))
    # Iterate through all NFs produced by TRS1
    for (s0, p0) in TRS1_seen:
        t0 = mkPair(StringVal(s0), StringVal(p0)) # Create a term to check if it collapses further via TRS2
        # Set up a Z3 solver to check whether this TRS1 NF can reduce to the TRS2 NF
        check_solver = Solver()
        # Assign x1 to the TRS1 NF term being tested
        check_solver.add(x1 == t0)
        # Assign x2 to one of the TRS2 input pairs
        check_solver.add(Or([x2 == t for t in TRS2_pairs]))  # Second pair from TRS2_pairs
        check_solver.add(scope(x1) == scope(x2))
        # Apply the TRS2 rules
        check_solver.add(TRS2_rules)
        # Resulting NF must match the currently tested TRS2 NF
        check_solver.add(nf == mkPair(scope(x1), StringVal("S")))
        check_solver.add(nf == target_nf)

        # If satisfiable, then the TRS1 NF rewrites further to this TRS2 NF
        if check_solver.check() == sat:
            TRS2_nf_to_terms[(scope_b, perm_b)].add((s0, p0))

# Generate final equivalence classes
final_equiv_classes=dict()
# 1) TRS2-derived classes
for nf, terms in dict(TRS2_nf_to_terms):
    jnf = json.dumps(nf)
    if jnf not in final_equiv_classes:
        final_equiv_classes[jnf] = str(terms)

# 2) add TRS1 NFs that did not participate in any TRS2 rule
for nf, terms in TRS1_nf_to_terms.items():
    jnf = json.dumps(nf)
    if jnf not in final_equiv_classes:
        final_equiv_classes[jnf] = str(terms)
if args.show:
  print("\n=== Final Equivalence Classes ===")
  for nf, terms in final_equiv_classes.items():
    print(f"NF: {nf} ← {terms}")

if args.save:
  with open(f"TRS_{args.pid}.json","w") as f:
    json.dump(final_equiv_classes,f,indent=2)
