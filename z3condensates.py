#!/usr/bin/python3

from z3 import *
s = Solver()

scopes = StringSort()
permissions = StringSort()
f_codomain = StringSort()

f = Function('f', scopes, f_codomain)
S = Function('S_equivalence', f_codomain, f_codomain, BoolSort())
P = Function('P_equivalence', permissions, permissions, BoolSort())

# Define variables a1, b1, a2, b2 as constants
a1 = Const('a1', scopes)
b1 = Const('b1', scopes)
a2 = Const('a2', permissions)
b2 = Const('b2', permissions)

<<<<<<< HEAD
A=StringVal("A")
Z=StringVal("Z")
=======
>>>>>>> 957294613abd5de08cde250243442852dedac6d1
TIERBlo=StringVal("BA")
TIERBhi=StringVal("BZ")
TIERClo=StringVal("CA")
TIERChi=StringVal("CZ")
TIERDlo=StringVal("DA")
TIERDhi=StringVal("DZ")
<<<<<<< HEAD
TIERlast=StringVal("ZZ")

# Axiom 1
s.add(Implies(a1 == b1, f(a1) == f(b1)))
s.add(Implies(And(a1>=TIERBlo,a1<=TIERBhi,b1>=TIERBlo,b1<=TIERBhi),S(f(a1), f(b1))))
s.add(Implies(And(a1>=TIERClo,a1<=TIERChi,b1>=TIERClo,b1<=TIERChi),S(f(a1), f(b1))))
s.add(Implies(And(a1>=TIERDlo,a1<=TIERDhi,b1>=TIERDlo,b1<=TIERDhi),S(f(a1), f(b1))))

# Axiom 2
s.add(Implies(a2 == b2, S(f(a1), f(b1))))

# Axiom 3
s.add(Implies(f(a1) == f(b1),S(f(a1),f(b1))))

# Bind f() to P() and finish Axiom 1
s.add(Implies(S(f(a1), f(b1)), P(a2, b2)))
s.add(Implies(Not(S(f(a1), f(b1))), Not(P(a2, b2))))

# For clarity, enforce minimum length for string constants
s.add(Length(a1) == 2)#, Length(a2) == 1)
s.add(Length(b1) == 2)#, Length(b2) == 1)

# For clarity, prevent "scopes" and "permissions" domains from overlapping
#s.add(a1!=a2,a1!=b2)
#s.add(b1!=a2,b1!=b2)
s.add(a2>=A,b2>=A,a2<=Z,b2<=Z)

s.add(a1<TIERlast,a2<TIERlast)

print("")
print("Part 1/Looking for SAT non-obvious examples")
print("  * Find P-equivalent pairs in the litteraly same scope")
=======

# Axiom 1A: f(a1) is in the same equivalence class as f(b1) (under the equivalence relation S) implies a2 P b2
s.add(Implies(S(f(a1), f(b1)), P(a2, b2)))

# Axiom 1B: f(a1) is NOT in the same equivalence class as f(b1) (under the equivalence relation S) implies NOT a2 P b2
s.add(Implies(Not(S(f(a1), f(b1))), Not(P(a2, b2))))

# Axiom 2A: a2 = b2 implies (f(a1) and f(b1) are class representatives of the same equivalence class of S
s.add(Implies(a2 == b2, S(f(a1), f(b1))))

# Axiom 2B: a1 = b1 implies (f(a1) and f(b1) are class representatives of the same equivalence class of S
s.add(Implies(a1 == b1, f(a1) == f(b1)))
s.add(Implies(f(a1) == f(b1),S(f(a1),f(b1))))

s.add(Implies(And(a1>=TIERBlo,a1<=TIERBhi,b1>=TIERBlo,b1<=TIERBhi),S(f(a1), f(b1))))
s.add(Implies(And(a1>=TIERClo,a1<=TIERChi,b1>=TIERClo,b1<=TIERChi),S(f(a1), f(b1))))
s.add(Implies(And(a1>=TIERDlo,a1<=TIERDhi,b1>=TIERDlo,b1<=TIERDhi),S(f(a1), f(b1))))

# For clarity, enforce minimum length for string constants
s.add(Length(a1) == 2, Length(a2) == 1)
s.add(Length(b1) == 2, Length(b2) == 1)

# For clarity, prevent "scopes" and "permissions" domains from overlapping
s.add(a1!=a2,a1!=b2)
s.add(b1!=a2,b1!=b2)

print("")
print("Part 1/Looking for SAT non-obvious examples")
print("  * Find P-equivalent pairs in the same scope")
>>>>>>> 957294613abd5de08cde250243442852dedac6d1
s.push()
s.add(f(a1) == f(b1), P(a2,b2))
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
