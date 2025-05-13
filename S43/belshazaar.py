#!/usr/bin/python3
from z3 import *
import argparse
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

S_list = [
    ('x','R'), ('x','W'),
    ('y','/read'), ('y','/write'),
    ('z','/*'), ('z','R'), ('z','*'),
    ('a','/read'), ('b','/action')
]

# 1) Declare your pair sort
Pair = Datatype('Pair')
Pair.declare('mkPair', ('scope', StringSort()), ('perm', StringSort()))
Pair = Pair.create()
mkPair = Pair.mkPair
scope = Pair.scope
perm = Pair.perm

# Declare normal form function
NF = Function('NF', Pair, Pair)

# and build the Z3 constants for them
S_terms = [ mkPair(StringVal(s), StringVal(p)) for s,p in S_list ]

# 3) Vars to enumerate
x, y = Consts('x y', Pair)


# 4) Start phi = (x∈S_terms ∧ y∈S_terms)
phi = Or([x == t for t in S_terms])

# 5) Build the solver once with your native rewrite‐rules + domain restriction on perm:
solver = Solver()

# Binary rule: ∃y in S_terms such that (R,W) or (W,R) → both normalize to S
# Here, we only care about NF(x), so project only on x
# We define this as: if such a y exists, then NF(x) = (scope(x), 'S')
binary_clause = []
for t in S_terms:
    binary_clause.append(
        And(
            scope(x) == scope(t),
            Or(
                And(perm(x) == StringVal("R"), perm(t) == StringVal("W")),
                And(perm(x) == StringVal("W"), perm(t) == StringVal("R"))
            )
        )
    )

solver.add(
    Implies(
        Or(*binary_clause),
        NF(x) == mkPair(scope(x), StringVal("S"))
    )
)

#  Unary “*” rule: if perm ends with '*' then perm→"S"
solver.add(
    Implies(
        SubString(perm(x), Length(perm(x)) - 1, 1) == StringVal("*"),
        NF(x) == mkPair(scope(x), StringVal("S"))
    )
)

solver.add(
    Implies(
        SubString(perm(x), Length(perm(x)) - 5, 5) == StringVal("/read"),
        NF(x) == mkPair(scope(x), StringVal("R"))
    )
)

solver.add(
    Implies(
        SubString(perm(x), Length(perm(x)) - 6, 6) == StringVal("/write"),
        NF(x) == mkPair(scope(x), StringVal("W"))
    )
)

solver.add(
    Implies(
        SubString(perm(x), Length(perm(x)) - 7, 7) == StringVal("/action"),
        NF(x) == mkPair(scope(x), StringVal("A"))
    )
)



# Otherwise, default NF(x) = x (identity)
# If neither unary nor binary applies, NF(x) == x
solver.add(
    Implies(
        And(
            SubString(perm(x), Length(perm(x)) - 1, 1) != StringVal("*"),
            Not(Or(*binary_clause)),
            SubString(perm(x), Length(perm(x)) - 5, 5) != StringVal("/read"),
            SubString(perm(x), Length(perm(x)) - 6, 6) != StringVal("/write"),
            SubString(perm(x), Length(perm(x)) - 7, 7) != StringVal("/action")
        ),
        NF(x) == x
    )
)

results = []

while True:
    s = Solver()
    s.add(phi)
    s.add(solver.assertions())
    if s.check() != sat:
        break
    m = s.model()
    valx = m[x]
    valnf = m.eval(NF(valx), model_completion=True)
    results.append((valx, valnf))
    # Add blocking clause: exclude this x in next round
    phi = And(phi, x != valx)

for orig, nf in results:
    print(f"x = {orig}, NF(x) = {nf}")

