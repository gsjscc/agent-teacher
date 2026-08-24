import sys
import paramiko

host = "connect.cqa1.seetacloud.com"
port = 18552
user = "root"
password = "rG88tTVb9c9U"

cmd = sys.argv[1] if len(sys.argv) > 1 else "echo CONNECTED && uname -a && (python3 --version || python --version)"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username=user, password=password, timeout=20)
stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
out = stdout.read().decode("utf-8", errors="replace")
err = stderr.read().decode("utf-8", errors="replace")
print("---STDOUT---")
print(out)
print("---STDERR---")
print(err)
client.close()
