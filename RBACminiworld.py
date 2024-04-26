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

print("  * Asymmetry")
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
s.add(Or(And(a2==c2,b2!=c2,f(b1)==f(c1)),And(a2!=c2,b2==c2,f(a1)==f(c1))))
s.add(Not(And(f(a1)==f(c1),f(b1)==f(c1))))
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

print("  * Find SP-equivalent pair (a,b) with no tuple c, distinct from a and b,  joining a and b")
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

TIERBlo=IntVal(10)
TIERBhi=IntVal(19)
TIERClo=IntVal(20)
TIERChi=IntVal(29)
TIERDlo=IntVal(30)
TIERDhi=IntVal(39)
TIERlast=IntVal(40)
s.add(a1>=TIERBlo,a1<TIERlast)
s.add(b1>=TIERBlo,b1<TIERlast)
s.add(c1>=TIERBlo,c1<TIERlast)

# Horizontal (or vertical) Congruence
s.add(ForAll([a1,b1],Implies(And(a1>=TIERBlo,a1<=TIERBhi,b1>=TIERBlo,b1<=TIERBhi),SP(f(a1), f(b1)))))
s.add(ForAll([a1,b1],Implies(And(a1>=TIERClo,a1<=TIERChi,b1>=TIERClo,b1<=TIERChi),SP(f(a1), f(b1)))))
s.add(ForAll([a1,b1],Implies(And(a1>=TIERDlo,a1<=TIERDhi,b1>=TIERDlo,b1<=TIERDhi),SP(f(a1), f(b1)))))

print("")
print("Part 3/Prove that HV congruence is an equivalence relation")
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

print("  * Asymmetry")
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

print("  * Find HV-equivalent pairs a,b which are distinct and joined by a third pair c distinct from a and b")
s.add(a2!=b2, a1!=b1, SP(f(a1),f(b1)))
s.add(Not(And(a1==c1,a2==c2)),Not(And(b1==c1,b2==c2)))
s.add(Or(And(a2==c2,b2!=c2,f(b1)==f(c1)),And(a2!=c2,b2==c2,f(a1)==f(c1))))
s.add(Not(And(f(a1)==f(c1),f(b1)==f(c1))))
result = s.check()
if result == sat:
    print("    SAT: ", s.model())
elif result == unsat:
    print("    UNSAT")
else:
    print("    UNKNOWN")
s.pop()

print("  * Find HV-equivalent pair (a,b) with no tuple c, distinct from a and b,  joining a and b")
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
print("  * Find not HV-equivalent pairs")
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
