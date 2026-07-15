import hashlib
import time
def crack_pin(thash,salt="salt"):
    for i in range(10000):
        guess=f"{i:04d}"
        intel=guess+salt
        ghash=hashlib.md5(intel.encode()).hexdigest()
        if ghash == thash:
            print(f"The Correct PIN is:{guess}")
            return guess 
    return None
if __name__=='__main__':
    thash=input("Enter the target hash:")
    crack_pin(thash)
