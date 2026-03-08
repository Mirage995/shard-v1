from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

class RequestHandler(BaseHTTPRequestHandler):
    users = {
        1: {"name": "John", "age": 30},
        2: {"name": "Jane", "age": 25}
    }

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/users":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(str(self.users).encode())
        elif parsed_path.path.startswith("/users/"):
            user_id = int(parsed_path.path.split("/")[-1])
            if user_id in self.users:
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(str(self.users[user_id]).encode())
            else:
                self.send_response(404)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write('{"error": "User not found"}'.encode())
        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write('{"error": "Resource not found"}'.encode())

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/users":
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length)
            user_data = eval(body.decode())
            new_user_id = max(self.users.keys()) + 1 if self.users else 1
            self.users[new_user_id] = user_data
            self.send_response(201)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(str(self.users[new_user_id]).encode())
        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write('{"error": "Resource not found"}'.encode())

    def do_PUT(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path.startswith("/users/"):
            user_id = int(parsed_path.path.split("/")[-1])
            if user_id in self.users:
                content_length = int(self.headers["Content-Length"])
                body = self.rfile.read(content_length)
                user_data = eval(body.decode())
                self.users[user_id] = user_data
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(str(self.users[user_id]).encode())
            else:
                self.send_response(404)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write('{"error": "User not found"}'.encode())
        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write('{"error": "Resource not found"}'.encode())

    def do_DELETE(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path.startswith("/users/"):
            user_id = int(parsed_path.path.split("/")[-1])
            if user_id in self.users:
                del self.users[user_id]
                self.send_response(204)
                self.send_header("Content-type", "application/json")
                self.end_headers()
            else:
                self.send_response(404)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write('{"error": "User not found"}'.encode())
        else:
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write('{"error": "Resource not found"}'.encode())

def run_server():
    server_address = ("", 8000)
    httpd = HTTPServer(server_address, RequestHandler)
    print("Server running on port 8000...")
    httpd.serve_forever()

run_server()