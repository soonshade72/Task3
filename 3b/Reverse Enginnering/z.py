from z3 import * 
b0= BitVec('b0',32)
b1= BitVec('b1',32)
b2= BitVec('b2',32)
solver=Solver()
solver.add(b0 + 1337 == 2007 )
solver.add(b0 ^ b1 == 1570)
solver.add(b2%b1 == 870)
solver.add(b2/2 ==22251)
if solver.check()== sat:
    print(solver.model())

