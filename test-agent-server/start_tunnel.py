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
    "unset http_proxy https_proxy; nohup ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=20 -R 80:localhost:6006 nokey@localhost.run > /root/tunnel.log 2>&1 &",
    "sleep 6",
    "cat /root/tunnel.log",
]
for c in cmds:
    stdin, stdout, stderr = client.exec_command(c, timeout=25)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(f"$ {c}")
    print(out)
    if err.strip():
        print("ERR:", err)

client.close()
