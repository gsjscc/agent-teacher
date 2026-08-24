import paramiko

host = "connect.cqa1.seetacloud.com"
port = 18552
user = "root"
password = "rG88tTVb9c9U"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username=user, password=password, timeout=20)

sftp = client.open_sftp()
sftp.put(r"D:\agent-teacher\test-agent-server\server_6006.py", "/root/server_6006.py")
sftp.close()

cmds = [
    "pkill -f server_6006.py || true",
    "nohup /root/miniconda3/bin/python3 /root/server_6006.py > /root/server_6006.log 2>&1 &",
    "sleep 1",
    "curl -s http://127.0.0.1:6006/ || echo CURL_FAILED",
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
