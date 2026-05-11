import subprocess
import state

def block_ip(ip):

    subprocess.run(
        ["iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"]
    )

def unblock_ip(ip):

    subprocess.run(
        ["iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"]
    )
