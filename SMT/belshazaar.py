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

# Build the Z3 constants for them
S0 = [ mkPair(StringVal(s), StringVal(p)) for s,p in S_list ]

U_seen = set()
nf = Const("nf", Pair)

x = Const("x", Pair)
x1 = Const("x1", Pair)
x2 = Const("x2", Pair)

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



while True:
    solver = Solver()
    #solver.set("timeout", 50000)

    # Let x, x1, x2 come from the input set
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

# ── 2) Build new input for binary TRS ──
S1 = [ mkPair(StringVal(s), StringVal(p)) for (s,p) in U_seen ]

# ── 3) Binary saturation ──
B_seen = set()
B_phi  = BoolVal(True)
x1 = Const("x1", Pair)
x2 = Const("x2", Pair)

# === Binary rules ===
binary_rules = And(
    scope(x1) == scope(x2),
    Or(
            And(perm(x1) == StringVal("R"), perm(x2) == StringVal("W")),
            And(perm(x1) == StringVal("W"), perm(x2) == StringVal("R"))
        ),
        nf == mkPair(scope(x1), StringVal("S"))
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

# ── 4) Equivalence classes ──
#  map each original term in S0 to its (u_nf, then b_nf)
classes = defaultdict(list)
for t0 in S0:
    # find its unary NF u
    for u in U_seen:
        # check if t0 rewrites to u
        s = Solver(); 
        s.add(x == t0, nf == mkPair(StringVal(u[0]), StringVal(u[1])))
        s.add(unary_rules)
        if s.check() == sat:
            # now find its binary NF b (or identity)
            t1 = mkPair(StringVal(u[0]), StringVal(u[1]))
            b_nf = u
            for b in B_seen:
                s2 = Solver()
                s2.add(x1 == t1, x2 == t1,binary_rules)
                if s2.check() == sat:
                    b_nf = b
                    break
            classes[b_nf].append((m.eval(scope(t0)).as_string(),
                                   m.eval(perm(t0)).as_string()))
            break

print("\nEquivalence classes after chaining:")
for rep, members in classes.items():
    print(f"  {rep} -> {members}")
