import paramiko
import time

host = "connect.cqa1.seetacloud.com"
port = 18552
user = "root"
password = "rG88tTVb9c9U"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username=user, password=password, timeout=20)

def run(c, timeout=90):
    stdin, stdout, stderr = client.exec_command(c, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(f"$ {c}")
    print(out[-2000:])
    if err.strip():
        print("ERR:", err[-1000:])
    return out, err

run(
    "export http_proxy=http://172.26.1.26:12798 https_proxy=http://172.26.1.26:12798; "
    "curl -L -o /usr/local/bin/cloudflared "
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
    "--max-time 60 -s -w 'HTTP_CODE:%{http_code} SIZE:%{size_download}\\n'",
    timeout=90,
)
run("chmod +x /usr/local/bin/cloudflared; ls -la /usr/local/bin/cloudflared")
run("/usr/local/bin/cloudflared --version")

client.close()
