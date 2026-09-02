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
            if action == 'install_ssl':
                cmd = """cd /var/www/omg-smile-sistem && git fetch origin main && git reset --hard origin/main && (which certbot >/dev/null 2>&1 || (DEBIAN_FRONTEND=noninteractive apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx)) && certbot --nginx -d dentmesherhub.com -d www.dentmesherhub.com --non-interactive --agree-tos --email info@dentmesherhub.com --redirect && nginx -t && systemctl reload nginx && systemctl restart omgsmile"""
            elif action == 'run_cmd':
                custom_cmd = params.get('cmd', [''])[0]
                if custom_cmd:
                    cmd = custom_cmd
                else:
                    cmd = "cd /var/www/omg-smile-sistem && git fetch origin main && git reset --hard origin/main && systemctl restart omgsmile"
            else:
                cmd = "cd /var/www/omg-smile-sistem && git fetch origin main && git reset --hard origin/main && systemctl restart omgsmile && (sleep 1 && systemctl restart omg_deploy >/dev/null 2>&1 &)"
                
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=240).decode('utf-8', errors='ignore')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "output": out}).encode())
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, 'output') and e.output:
                err_msg += " -> " + e.output.decode('utf-8', errors='ignore')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "error": err_msg}).encode())

def run():
    server = HTTPServer(('127.0.0.1', 9090), DeployHandler)
    print("Deploy Agent running on 127.0.0.1:9090...")
    server.serve_forever()

if __name__ == '__main__':
    run()
