"""
Tiny static file server for the Grove frontend.
Serves frontend/ on port 8080 so the whole thing works from
http://localhost:8080 while the backend WebSocket runs on 8765.

Hardened to never fail silently: if the port is already taken (a common
issue on Windows, where other local services sometimes sit on 8080), it
prints a clear message and tries the next few ports automatically.
"""
import http.server
import socketserver
import os
import sys
import traceback

PORT = int(os.environ.get("GROVE_FRONTEND_PORT", 8080))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), format % args))
        sys.stdout.flush()


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    last_error = None
    for attempt_port in range(PORT, PORT + 5):
        try:
            with ReusableTCPServer(("0.0.0.0", attempt_port), Handler) as httpd:
                if attempt_port != PORT:
                    print(f"Port {PORT} was unavailable, using {attempt_port} instead.")
                    print(f"Open http://localhost:{attempt_port} in your browser.")
                print(f"Grove frontend serving at http://0.0.0.0:{attempt_port}")
                sys.stdout.flush()
                httpd.serve_forever()
            return
        except OSError as e:
            last_error = e
            print(f"Could not bind port {attempt_port}: {e}")
            sys.stdout.flush()
            continue

    print("Failed to start the frontend server after trying several ports.")
    print(f"Last error: {last_error}")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Frontend server crashed with an unexpected error:")
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
