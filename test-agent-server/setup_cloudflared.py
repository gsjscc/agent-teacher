import paramiko

host = "connect.cqa1.seetacloud.com"
port = 18552
user = "root"
password = "rG88tTVb9c9U"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username=user, password=password, timeout=20)

cmds = [
    "pkill -f 'ssh -o.*localhost.run' || true",
    "pkill -f cloudflared || true",
    "test -f /usr/local/bin/cloudflared && echo ALREADY_INSTALLED || echo NEED_INSTALL",
]
for c in cmds:
    stdin, stdout, stderr = client.exec_command(c, timeout=20)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(f"$ {c}")
    print(out)
    if err.strip():
        print("ERR:", err)

client.close()
