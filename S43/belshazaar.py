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
S_terms = [ mkPair(StringVal(s), StringVal(p)) for s,p in S_list ]

seen_nfs = set()
nf_to_terms = defaultdict(set)

while True:
    solver = Solver()
    #solver.set("timeout", 50000)

    nf = Const("nf", Pair)
    x = Const("x", Pair)
    x1 = Const("x1", Pair)
    x2 = Const("x2", Pair)

    # Let x, x1, x2 come from the input set
    solver.add(Or([x == t for t in S_terms]))
    solver.add(Or([
        And(x1 == t1, x2 == t2, Not(t1 == t2))
        for t1 in S_terms
        for t2 in S_terms
    ]))

    # === Unary rules ===
    unary_rule = Or(
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

    # === Binary rules ===
    binary_rule = And(
        scope(x1) == scope(x2),
        Or(
            And(perm(x1) == StringVal("R"), perm(x2) == StringVal("W")),
            And(perm(x1) == StringVal("W"), perm(x2) == StringVal("R"))
        ),
        nf == mkPair(scope(x1), StringVal("S"))
    )

    # Add rules and block previous nfs
    solver.add(Or(unary_rule, binary_rule))
    for s, p in seen_nfs:
        solver.add(nf != mkPair(StringVal(s), StringVal(p)))

    if solver.check() == sat:
        m = solver.model()
        val_nf = m.eval(nf, model_completion=True)
        scope_val = m.eval(scope(val_nf)).as_string()
        perm_val = m.eval(perm(val_nf)).as_string()
        rep = (scope_val, perm_val)
        print(f"→ New NF: {rep}")
        seen_nfs.add(rep)

        # Track all original terms that rewrite to this nf
        for t in S_terms:
            check_solver = Solver()
            check_solver.add(
                Or(
                    And(x == t,
                        And(SuffixOf(StringVal("/read"), perm(x)),
                            nf == mkPair(scope(x), StringVal("R"))
                        )),
                    And(x == t,
                        And(SuffixOf(StringVal("/write"), perm(x)),
                            nf == mkPair(scope(x), StringVal("W"))
                        )),
                    And(x == t,
                        And(SuffixOf(StringVal("/delete"), perm(x)),
                            nf == mkPair(scope(x), StringVal("W"))
                        )),
                    And(x == t,
                        And(SuffixOf(StringVal("/action"), perm(x)),
                            nf == mkPair(scope(x), StringVal("A"))
                        )),    
                    And(x == t,
                        And(SuffixOf(StringVal("*"), perm(x)),
                            nf == mkPair(scope(x), StringVal("S"))
                        )),
                    And(x1 == t,
                        Or(
                            And(perm(x1) == StringVal("R"), perm(x2) == StringVal("W")),
                            And(perm(x1) == StringVal("W"), perm(x2) == StringVal("R"))
                        ),
                        scope(x1) == scope(x2),
                        nf == mkPair(scope(x1), StringVal("S"))
                    )
                )
            )
            check_solver.add(nf == mkPair(StringVal(scope_val), StringVal(perm_val)))
            if check_solver.check() == sat:
                scope_t = m.eval(scope(t)).as_string()
                perm_t = m.eval(perm(t)).as_string()
                nf_to_terms[rep].add((scope_t, perm_t))
    else:
        print("Saturation complete.")
        break

print("\n=== Equivalence Classes ===")
for nf, terms in nf_to_terms.items():
    print(f"NF: {nf} ← {terms}")


for t in S_terms:
    s = Solver()
    s.add(x == t)

    print("\nChecking term:")

    # Optionally extract scope and perm for printing
    model_check = Solver()
    model_check.add(x == t)
    if model_check.check() == sat:
        m = model_check.model()
        scope_val = m.eval(scope(x), model_completion=True)
        perm_val = m.eval(perm(x), model_completion=True)
        print(f"  Term: ({scope_val}, {perm_val})")

    # Check /read
    s_read = Solver()
    s_read.add(x == t)
    s_read.add(SuffixOf(StringVal("/read"), perm(x)))
    if s_read.check() == sat:
        print("  → Matches unary rule: /read → R")

    # Check /write
    s_write = Solver()
    s_write.add(x == t)
    s_write.add(SuffixOf(StringVal("/write"), perm(x)))
    if s_write.check() == sat:
        print("  → Matches unary rule: /write → W")

    # Check /delete
    s_delete = Solver()
    s_delete.add(x == t)
    s_delete.add(SuffixOf(StringVal("/delete"), perm(x)))
    if s_delete.check() == sat:
        print("  → Matches unary rule: /delete → W")

    # Check *
    s_star = Solver()
    s_star.add(x == t)
    s_star.add(SuffixOf(StringVal("*"), perm(x)))
    if s_star.check() == sat:
        print("  → Matches unary rule: * → S")

    # Check /action
    s_action = Solver()
    s_action.add(x == t)
    s_action.add(SuffixOf(StringVal("/action"), perm(x)))
    if s_action.check() == sat:
        print("  → Matches unary rule: /action → A")

    # Fallback
    if all(s.check() == unsat for s in [s_read, s_write, s_star, s_delete, s_action]):
        print("  → No unary rule matches (falls back to identity)")

