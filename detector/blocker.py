import subprocess
import time
import state
import yaml

# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

def block_ip(ip, duration=None):
    """
    Block an IP using iptables DROP rule.
    
    Args:
        ip: IP address to block
        duration: Duration in seconds, or None for permanent ban
    """
    try:
        # Add iptables DROP rule
        result = subprocess.run(
            ["iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode != 0:
            print(f"[BLOCKER ERROR] Failed to block {ip}: {result.stderr.decode()}")
            return False
        
        print(f"[BLOCKER] Successfully blocked {ip} (duration: {duration}s)" if duration else f"[BLOCKER] Permanently blocked {ip}")
        return True
        
    except Exception as e:
        print(f"[BLOCKER ERROR] Exception blocking {ip}: {e}")
        return False


def unblock_ip(ip):
    """
    Unblock an IP by removing the iptables DROP rule.
    
    Args:
        ip: IP address to unblock
    """
    try:
        result = subprocess.run(
            ["iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode != 0:
            print(f"[BLOCKER ERROR] Failed to unblock {ip}: {result.stderr.decode()}")
            return False
        
        print(f"[BLOCKER] Successfully unblocked {ip}")
        return True
        
    except Exception as e:
        print(f"[BLOCKER ERROR] Exception unblocking {ip}: {e}")
        return False
