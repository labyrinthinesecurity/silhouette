#!/usr/bin/python3

from z3 import *
import sys

s = Solver()

scopes = StringSort()
permissions = StringSort()
f_codomain = StringSort()

f = Function('f', scopes, f_codomain)
S = Function('S_equivalence', f_codomain, f_codomain, BoolSort())
P = Function('P_equivalence', permissions, permissions, BoolSort())

# Define variables a1, b1, a2, b2, c1, c2  as constants
a1 = Const('a1', scopes)
b1 = Const('b1', scopes)
c1 = Const('c1', scopes)

a2 = Const('a2', permissions)
b2 = Const('b2', permissions)
c2 = Const('c2', permissions)

A=StringVal("A")
Z=StringVal("Z")
TIERBlo=StringVal("BA")
TIERBhi=StringVal("BZ")
TIERClo=StringVal("CA")
TIERChi=StringVal("CZ")
TIERDlo=StringVal("DA")
TIERDhi=StringVal("DZ")
TIERlast=StringVal("ZZ")

# Axiom 1
s.add(ForAll([a1,b1],Implies(a1 == b1, f(a1) == f(b1))))

# Horizontal congruence
#s.add(Implies(And(a1>=TIERBlo,a1<=TIERBhi,b1>=TIERBlo,b1<=TIERBhi),S(f(a1), f(b1))))
#s.add(Implies(And(a1>=TIERClo,a1<=TIERChi,b1>=TIERClo,b1<=TIERChi),S(f(a1), f(b1))))
#s.add(Implies(And(a1>=TIERDlo,a1<=TIERDhi,b1>=TIERDlo,b1<=TIERDhi),S(f(a1), f(b1))))

# Axiom 2
s.add(ForAll([a1,b1,a2,b2],Implies(a2 == b2, S(f(a1), f(b1)))))

# Axiom 3
s.add(ForAll([a1,b1],Implies(f(a1) == f(b1),S(f(a1),f(b1)))))

# Bind f() to P() and finish Axiom 1
s.add(ForAll([a1,b1,a2,b2],Implies(S(f(a1), f(b1)), P(a2, b2))))
s.add(ForAll([a1,b1,a2,b2],Implies(Not(S(f(a1), f(b1))), Not(P(a2, b2)))))

# Enforce search bounds on string variables
s.add(Length(a1) == 2)
s.add(Length(b1) == 2)
s.add(Length(c1) == 2)
s.add(Length(a2) == 2)
s.add(Length(b2) == 2)
s.add(Length(c2) == 2)

#s.add(a2>=A,b2>=A,a2<=Z,b2<=Z)
s.add(a1<TIERlast,a2<TIERlast)
s.add(b1<TIERlast,b2<TIERlast)
s.add(c1<TIERlast,c2<TIERlast)

s.add(a1!=a2,a1!=b2,a1!=c2)
s.add(b1!=a2,b1!=b2,b1!=c2)
s.add(c1!=a2,c1!=b2,c1!=c2)

print("")
print("Part 0/Prove that P is an equivalence relation")
print("  * Reflexivity")
# Expected result: SAT
s.push()
s.add(P(a2,a2))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Non-reflexivity")
# Expected result: UNSAT
s.push()
s.add(Not(P(a2,a2)))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Symmetry")
# Expected result: SAT
s.push()
s.add(And(P(a2,b2),P(b2,a2)))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Non-symmetry")
# Expected result: UNSAT
s.push()
s.add(And(P(a2,b2),Not(P(b2,a2))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Transitivity")
# Expected result: SAT
s.push()
s.add(And(P(a2,b2),P(b2,c2),P(a2,c2)))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Non-transitivity")
# Expected result: UNSAT
s.push()
s.add(And(P(a2,b2),P(b2,c2),Not(P(a2,c2))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("")
print("Part 1/Looking for SAT non-obvious examples")
print("  * Find P-equivalent pairs in the litteraly same scope")
'''
Example result:
SAT:  [a1 = "Z@",
 b1 = "Z@",
 b2 = "D",
 a2 = "D",
 f = [else -> "D"],
 S_equivalence = [else -> True],
 P_equivalence = [else -> True]]
'''
s.push()
s.add(a1 == b1, P(a2,b2), a2!=b2)
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

s.push()
print("")
print("  * Find P-equivalent pairs with different permissions")
'''
Example result:
SAT:  [a1 = "Z@",
 b1 = "Z@",
 b2 = "D",
 a2 = "DH",
 f = [else -> "B"],
 S_equivalence = [else -> True],
 P_equivalence = [else -> True]]
'''
s.add(a2!=b2, P(a2,b2))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

s.push()
print("")
print("  * Find not P-equivalent pairs")
#Example result:
#SAT:  [a1 = "BZ",
# b1 = "B\u{}",
# b2 = "Z",
# a2 = "C",
# f = ["B\u{}" -> "B", else -> ""],
# S_equivalence = [else -> False],
# P_equivalence = [else -> False]]
s.add(Not(P(a2,b2)))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("")
print("Part 2/Looking for fatal SAT counterexamples")
print("  * Find P-equivalent pairs which are not S-equivalent")
'''
Expected result: UNSAT
'''
s.push()
s.add(P(a2,b2),Not(S(f(a1),f(b1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("")
print("  * Find equal permissions which are not P-equivalent")
'''
Expected result: UNSAT
'''
s.push()
s.add(a2 == b2, Not(P(a2,b2)))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()
