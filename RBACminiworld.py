#!/usr/bin/python3

from z3 import *
import sys

s = Solver()

scopes = IntSort()
permissions = StringSort()
f_codomain = IntSort()

f = Function('scope filter', scopes, f_codomain)
SP = Function('SP_equivalence', f_codomain, f_codomain, BoolSort())

# Define variables a1, b1, a2, b2, c1, c2  as constants
a1 = Const('a1', scopes)
b1 = Const('b1', scopes)
c1 = Const('c1', scopes)

a2 = Const('a2', permissions)
b2 = Const('b2', permissions)
c2 = Const('c2', permissions)

# Axiom 1
s.add(ForAll([a1,b1],Implies(a1 == b1, f(a1) == f(b1))))

# Axiom 2
s.add(ForAll([a1,b1,a2,b2],Implies(a2 == b2, SP(f(a1), f(b1)))))

# Axiom 3
s.add(ForAll([a1,b1],Implies(f(a1) == f(b1),SP(f(a1),f(b1)))))

s.add(Length(a2)==2)
s.add(Length(b2)==2)
s.add(Length(c2)==2)

print("")
print("Part 0/Prove that SP is an equivalence relation")
print("  * Non-reflexivity")
# Expected result: UNSAT
s.push()
s.add(Not(SP(f(a1),f(a1))))
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
s.add(And(SP(f(a1),f(b1)),Not(SP(f(b1),f(a1)))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Intransitivity")
# Expected result: UNSAT
s.push()
s.add(And(SP(f(a1),f(b1)),SP(f(b1),f(c1)),Not(SP(f(a1),f(c1)))))
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

s.push()
print("")
print("  * Find SP-equivalent pairs a,b which are distinct and joined directly by a third pair c distinct from a and b")
s.add(a2!=b2, a1!=b1, SP(f(a1),f(b1)))
s.add(Not(And(a1==c1,a2==c2)),Not(And(b1==c1,b2==c2)))
s.add(Or(And(a2==c2,b2!=c2,f(b1)==f(c1),f(a1)!=f(c1)),And(a2!=c2,b2==c2,f(a1)==f(c1),f(b1)!=f(c1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN",result)
s.pop()

print("")
print("Part 2/Looking for fatal SAT counterexamples")
print("  * Find same scope pairs not SP-equivalent")
s.push()
s.add(a1 == b1, Not(SP(f(a1),f(b1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Any SP-equivalent pair (a,b) always has a tuple c, distinct from a and b,  joining a and b directly")
# Expected result: UNSAT
s.push()
s.add(Implies(SP(f(a1), f(b1)),ForAll([c1,c2],And(Not(And(a1==c1,a2==c2)),Not(And(b1==c1,b2==c2)),And(Or(a1==c1,b1==c1),Or(a2==c2,b2==c2))))))
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
print("  * Find not SP-equivalent pairs")
# Expected result: UNSAT
s.add(Not(SP(f(a1),f(b1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

# Define intervals of 3 cylinders CYL10, CYL20 and CYL30
CYL10_low=IntVal(10)
CYL10_hi=IntVal(19)
CYL20_lo=IntVal(20)
CYL20_hi=IntVal(29)
CYL30_lo=IntVal(30)
CYL30_hi=IntVal(39)

# Tie a1, b1 and c1 to any of the 3 cylinders
s.add(a1>=CYL10_low,a1<CYL30_hi)
s.add(b1>=CYL10_low,b1<CYL30_hi)
s.add(c1>=CYL10_low,c1<CYL30_hi)

# Horizontal Congruence: if two scopes belong to the same cylinder, they are SP equivalent
s.add(ForAll([a1,b1],Implies(And(a1>=CYL10_low,a1<=CYL10_hi,b1>=CYL10_low,b1<=CYL10_hi),SP(f(a1), f(b1)))))
s.add(ForAll([a1,b1],Implies(And(a1>=CYL20_lo,a1<=CYL20_hi,b1>=CYL20_lo,b1<=CYL20_hi),SP(f(a1), f(b1)))))
s.add(ForAll([a1,b1],Implies(And(a1>=CYL30_lo,a1<=CYL30_hi,b1>=CYL30_lo,b1<=CYL30_hi),SP(f(a1), f(b1)))))

print("")
print("Part 3/Prove that H congruence is an equivalence relation")
print("  * Non-reflexivity")
# Expected result: UNSAT
s.push()
s.add(Not(SP(f(a1),f(a1))))
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
s.add(And(SP(f(a1),f(b1)),Not(SP(f(b1),f(a1)))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Intransitivity")
# Expected result: UNSAT
s.push()
s.add(And(SP(f(a1),f(b1)),SP(f(b1),f(c1)),Not(SP(f(a1),f(c1)))))
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

print("  * Find H-equivalent pairs a,b which are distinct and joined by a third pair c distinct from a and b")
s.add(a2!=b2, a1!=b1, SP(f(a1),f(b1)))
s.add(Not(And(a1==c1,a2==c2)),Not(And(b1==c1,b2==c2)))
s.add(Or(And(a2==c2,b2!=c2,f(b1)==f(c1),f(a1)!=f(c1)),And(a2!=c2,b2==c2,f(a1)==f(c1),f(b1)!=f(c1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Any H-equivalent pairs (a,b) has a tuple c, distinct from a and b,  joining a and b directly")
# Expected result: UNSAT
s.push()
s.add(Implies(SP(f(a1), f(b1)),ForAll([c1,c2],And(Not(And(a1==c1,a2==c2)),Not(And(b1==c1,b2==c2)),And(Or(a1==c1,b1==c1),Or(a2==c2,b2==c2))))))
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
print("  * Find not H-equivalent pairs")
# Expected result: UNSAT
s.add(Not(SP(f(a1),f(b1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()
