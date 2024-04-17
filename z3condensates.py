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

# Axiom 1A: f(a1) is in the same equivalence class as f(b1) (under the equivalence relation S) implies a2 P b2
s.add(ForAll([a1, b1, a2, b2], Implies(S(f(a1), f(b1)), P(a2, b2))))
# Axiom 1B: f(a1) is NOT in the same equivalence class as f(b1) (under the equivalence relation S) implies NOT a2 P b2
s.add(ForAll([a1, b1, a2, b2], Implies(Not(S(f(a1), f(b1))), Not(P(a2, b2)))))

# Axiom 2: a2 = b2 implies (f(a1) and f(b1) are class representatives of the same equivalence class of S
s.add(ForAll([a1, b1, a2, b2], Implies(a2 == b2, S(f(a1), f(b1)))))

# Create string constants for tuples "x", "y" and "z"
x1 = Const('x1', scopes)
y1 = Const('y1', scopes)
z1 = Const('z1', scopes)
x2 = Const('x2', permissions)
y2 = Const('y2', permissions)
z2 = Const('z2', permissions)

# Enforce minimum length of 1 for string constants
s.add(Length(x1) >= 1, Length(y1) >= 1, Length(z1) >= 1)
s.add(Length(x2) >= 1, Length(y2) >= 1, Length(z2) >= 1)

# For clarity, prevent scopes and permissions domains to overlap
s.add(x1!=x2,x1!=y2,x1!=z2)
s.add(y1!=x2,y1!=y2,y1!=z2)
s.add(z1!=x2,z1!=y2,z1!=z2)

print("Part 1: UNSATS")
print("Axiom 1A cannot be contradicted")
s.push()
s.add(S(f(x1),f(y1)), Not(P(x2,y2)))
result = s.check()
if result == sat:
    print("SAT: ", s.model())
elif result == unsat:
    print("UNSAT")
else:
    print("UNKNOWN")
s.pop()

s.push()
print("Axiom 1B cannot be contradicted")
s.add(Not(S(f(x1),f(y1))), P(x2,y2))
result = s.check()
if result == sat:
    print("SAT: ", s.model())
elif result == unsat:
    print("UNSAT")
else:
    print("UNKNOWN")
s.pop()

s.push()
print("Axiom 2 cannot be contradicted")
s.add(x2!=y2, Not(S(f(x1),f(y1))))
result = s.check()
if result == sat:
    print("SAT: ", s.model())
elif result == unsat:
    print("UNSAT")
else:
    print("UNKNOWN")
s.pop()

print("")
print("Part 2: SATS")
print("subcase of Axiom 1A (reason about f(), not S(f()))")
s.push()
s.add(f(x1) == f(y1), P(x2,y2))
result = s.check()
if result == sat:
    print("SAT: ", s.model())
elif result == unsat:
    print("UNSAT")
else:
    print("UNKNOWN")
s.pop()

print("")
print("Part 3: ")
s.push()
print("There are P-equivalent pairs with different permissions")
s.add(x2!=y2, P(x2,y2))
result = s.check()
if result == sat:
    print("SAT: ", s.model())
elif result == unsat:
    print("UNSAT")
else:
    print("UNKNOWN")
s.pop()

