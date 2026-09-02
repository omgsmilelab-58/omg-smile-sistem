from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import subprocess
import os
import json

SECRET_TOKEN = "Dentmesher2026SecureToken"

class DeployHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        token = params.get('token', [''])[0]
        action = params.get('action', ['update'])[0]
        
        if token != SECRET_TOKEN:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "Yetkisiz erisim"}).encode())
            return
            
        try:
            cmd = "cd /var/www/omg-smile-sistem && git fetch origin main && git reset --hard origin/main && systemctl restart omgsmile"
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=60).decode('utf-8', errors='ignore')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "output": out}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode())

def run():
    server = HTTPServer(('127.0.0.1', 9090), DeployHandler)
    print("Deploy Agent running on 127.0.0.1:9090...")
    server.serve_forever()

if __name__ == '__main__':
    run()
