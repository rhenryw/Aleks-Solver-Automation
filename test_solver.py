from solver import Solver
from browser import Browser
import logging

logging.basicConfig(level=logging.ERROR)

def test():
    solver = Solver()
    questions = [
        'Fill in the blank to make equivalent rational expressions. begin fraction 8 v over 4 v - 7 end fraction = begin fraction empty input box over 32 v - 56 end fraction',
        'Fill in the blank to make equivalent rational expressions. (8v)/(4v-7) = (__)/(32v-56)',
        'Fill in the blank to make equivalent rational expressions. begin fraction 7 y over y - 8 end fraction = begin fraction empty input box over ( y - 8 ) ( y - 7 ) end fraction'
    ]
    print("Testing _solve_symbolically():")
    for q in questions:
        try:
            result = solver._solve_symbolically(q)
            print("Question:", q)
            print("Result:", result, "\n")
        except Exception as e:
            print("Error:", e)
    
    print("\nTesting browser._normalize_math_speech on question #1:")
    try:
        b =        b =        b =        =        b =        b =  h(        b =        b =   nt(        l:", que        b =        print("Normalized:", no        b
                  on as e:
        print("Error:", e)

if __name__ == "__main__":
    test()
