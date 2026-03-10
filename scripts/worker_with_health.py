import os
import subprocess
import sys
import threading
import http.server
import socketserver

# A simple HTTP server to satisfy Cloud Run's health check.
class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    
    def log_message(self, format, *args):
        # Suppress health check logs to keep container logs clean
        return

def run_health_server(port):
    with socketserver.TCPServer(("", port), HealthHandler) as httpd:
        print(f"Health check server listening on port {port}")
        httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # 1. Start health check server in background thread
    t = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    t.start()
    
    # 2. Start Celery worker
    # Using the same arguments as original Cloud Build config
    cmd = ["celery", "-A", "app.core.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
    print(f"Starting Celery: {' '.join(cmd)}")
    
    try:
        # We use subprocess.call to block until celery exits.
        # If celery fails, the container exits, which is what we want.
        sys.exit(subprocess.call(cmd))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
