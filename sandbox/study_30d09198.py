from flask import Flask, jsonify, request

app = Flask(__name__)

books = [
    {"id": 1, "title": "Book 1", "author": "Author 1"},
    {"id": 2, "title": "Book 2", "author": "Author 2"},
    {"id": 3, "title": "Book 3", "author": "Author 3"}
]

@app.route("/books", methods=["GET"])
def get_books():
    return jsonify(books)

@app.route("/books/<int:book_id>", methods=["GET"])
def get_book(book_id):
    book = next((book for book in books if book["id"] == book_id), None)
    if book is None:
        return jsonify({"message": "Book not found"}), 404
    return jsonify(book)

@app.route("/books", methods=["POST"])
def create_book():
    new_book = {
        "id": len(books) + 1,
        "title": request.json["title"],
        "author": request.json["author"]
    }
    books.append(new_book)
    return jsonify(new_book), 201

@app.route("/books/<int:book_id>", methods=["PUT"])
def update_book(book_id):
    book = next((book for book in books if book["id"] == book_id), None)
    if book is None:
        return jsonify({"message": "Book not found"}), 404
    book["title"] = request.json.get("title", book["title"])
    book["author"] = request.json.get("author", book["author"])
    return jsonify(book)

@app.route("/books/<int:book_id>", methods=["DELETE"])
def delete_book(book_id):
    book = next((book for book in books if book["id"] == book_id), None)
    if book is None:
        return jsonify({"message": "Book not found"}), 404
    books.remove(book)
    return jsonify({"message": "Book deleted"})

if __name__ == "__main__":
    app.run(debug=True)