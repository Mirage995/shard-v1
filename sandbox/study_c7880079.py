from flask import Flask, request, jsonify

app = Flask(__name__)

# Sample in-memory data store
data_store = {
    1: {"name": "John Doe", "age": 30},
    2: {"name": "Jane Doe", "age": 25}
}

# GET /users
@app.route('/users', methods=['GET'])
def get_users():
    return jsonify(list(data_store.values()))

# GET /users/:id
@app.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    if user_id in data_store:
        return jsonify(data_store[user_id])
    else:
        return jsonify({"error": "User not found"}), 404

# POST /users
@app.route('/users', methods=['POST'])
def create_user():
    new_user = {
        "name": request.json["name"],
        "age": request.json["age"]
    }
    new_user_id = max(data_store.keys()) + 1
    data_store[new_user_id] = new_user
    return jsonify(new_user), 201

# PUT /users/:id
@app.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    if user_id in data_store:
        data_store[user_id]["name"] = request.json.get("name", data_store[user_id]["name"])
        data_store[user_id]["age"] = request.json.get("age", data_store[user_id]["age"])
        return jsonify(data_store[user_id])
    else:
        return jsonify({"error": "User not found"}), 404

# DELETE /users/:id
@app.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if user_id in data_store:
        del data_store[user_id]
        return jsonify({"message": "User deleted"})
    else:
        return jsonify({"error": "User not found"}), 404

if __name__ == '__main__':
    app.run()