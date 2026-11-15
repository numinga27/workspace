#!/usr/bin/env python3
"""Deploy files to server using base64 encoding via SSH."""
import base64
import subprocess
import sys

SERVER = "root@176.110.16.93"
REMOTE_PATH = "/var/www/workspace"

def deploy_file(local_path):
    """Read file, base64 encode, and write to server via SSH."""
    try:
        # Read local file
        with open(local_path, 'rb') as f:
            content = f.read()
        
        # Base64 encode
        encoded = base64.b64encode(content).decode('ascii')
        
        # Write to server using python3 -c with base64 decode
        cmd = f'''ssh {SERVER} "python3 -c 'import base64; open(\"{REMOTE_PATH}/{local_path}\", \"wb\").write(base64.b64decode(\"{encoded}\"))" '''
        
        print(f"📤 Deploying {local_path}...", file=sys.stderr)
        result = subprocess.run(cmd, shell=True, timeout=60, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ {local_path} deployed", file=sys.stderr)
            return True
        else:
            print(f"❌ {local_path} failed: {result.stderr}", file=sys.stderr)
            return False
            
    except Exception as e:
        print(f"❌ {local_path} error: {e}", file=sys.stderr)
        return False

def clear_cache():
    """Clear Python cache on server."""
    print("🧹 Clearing Python cache...", file=sys.stderr)
    cmd = f"ssh {SERVER} \"cd {REMOTE_PATH} && find . -name '__pycache__' -exec rm -rf {{}} + 2>/dev/null || true\""
    subprocess.run(cmd, shell=True, timeout=30)
    print("✅ Cache cleared", file=sys.stderr)

def restart_gunicorn():
    """Restart Gunicorn."""
    print("🔄 Restarting Gunicorn...", file=sys.stderr)
    cmd = f"ssh {SERVER} \"pkill -9 gunicorn && sleep 2 && systemctl start workspace.service\""
    subprocess.run(cmd, shell=True, timeout=30)
    print("✅ Gunicorn restarted", file=sys.stderr)

if __name__ == '__main__':
    files = [
        'templates/project.html',
        'blueprints/chat.py',
        'models.py',
    ]
    
    success_count = 0
    for f in files:
        if deploy_file(f):
            success_count += 1
    
    if success_count == len(files):
        clear_cache()
        restart_gunicorn()
        print(f"\n🎉 All {success_count}/{len(files)} files deployed successfully!", file=sys.stderr)
    else:
        print(f"\n⚠️ Only {success_count}/{len(files)} files deployed", file=sys.stderr)
        sys.exit(1)
