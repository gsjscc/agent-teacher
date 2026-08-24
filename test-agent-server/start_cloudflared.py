import paramiko
import time

host = "connect.cqa1.seetacloud.com"
port = 18552
user = "root"
password = "rG88tTVb9c9U"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username=user, password=password, timeout=20)

def run(c, timeout=30):
    stdin, stdout, stderr = client.exec_command(c, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(f"$ {c}")
    print(out)
    if err.strip():
        print("ERR:", err)
    return out, err

run("pkill -f cloudflared || true")
run(
    "unset http_proxy https_proxy; "
    "nohup /usr/local/bin/cloudflared tunnel --url http://localhost:6006 "
    "> /root/cloudflared.log 2>&1 & disown"
)
time.sleep(10)
run("cat /root/cloudflared.log")

client.close()
