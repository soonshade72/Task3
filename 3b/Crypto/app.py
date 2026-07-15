import hashlib
from flask import Flask,request,jsonify
app = Flask(__name__)
PIN="4812"
SALT="salt"
FLAG="CTF{br4v0_51r}"
dhash= PIN+SALT
Thash=hashlib.md5(dhash.encode()).hexdigest()
@app.route('/api/challenge',methods=['GET'])
def get():
    return jsonify({
        "target_hash":Thash
    })
@app.route('/api/unlock',methods=['POST'])
def uflag():
    guess = request.json.get('pin')
    if guess == PIN:
        return jsonify({"success":True,"flag":FLAG})
    else:
        return jsonify({"success":False,"message":"Incorrect PIN."})
if __name__=='__main__':
    app.run(port=5000)