import time
import state

from blocker import unblock_ip
from notifier import send_slack_alert

def unban_worker():
    """
    Unban worker. Checks every 10 seconds for IPs whose ban has expired.
    
    Ban durations follow a backoff schedule:
    - 1st offense: 10 minutes
    - 2nd offense: 30 minutes
    - 3rd offense: 2 hours
    - 4th+ offense: Permanent (no auto-unban)
    
    On unban, sends Slack notification and logs to audit trail.
    """
    
    print("[UNBAN] Worker started")
    
    while True:
        try:
            now = time.time()
            to_remove = []
            
            with state.lock:
                for ip, data in list(state.banned_ips.items()):
                    expires = data.get("expires")
                    offense_count = data.get("offense_count", 0)
                    
                    # Skip permanent bans (expires == inf)
                    if expires == float('inf'):
                        print(f"[UNBAN] Skipping permanent ban for {ip}")
                        continue
                    
                    # Check if ban time has expired
                    if expires and now >= expires:
                        print(f"[UNBAN] Ban expired for {ip}")
                        
                        # Remove from blocked state
                        to_remove.append(ip)
                        
                        # Unblock the IP
                        unblock_ip(ip)
                        
                        # Determine ban duration that expired
                        ban_config = state.state_config.get("ban_durations", [600, 1800, 7200])
                        if offense_count > 0 and offense_count <= len(ban_config):
                            duration_secs = ban_config[offense_count - 1]
                        else:
                            duration_secs = "∞"
                        
                        # Send Slack alert
                        alert_message = (
                            f"✅ **IP UNBANNED**\n\n"
                            f"**IP:** `{ip}`\n"
                            f"**Offense Count:** {offense_count}\n"
                            f"**Ban Duration:** {duration_secs}s\n"
                            f"**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        
                        send_slack_alert(alert_message)
                        
                        # Audit log
                        with open("audit.log", "a") as f:
                            f.write(
                                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                                f"UNBAN | ip={ip} | "
                                f"offense_count={offense_count} | "
                                f"duration={duration_secs}\n"
                            )
            
            # Remove unbanned IPs from state
            for ip in to_remove:
                if ip in state.banned_ips:
                    del state.banned_ips[ip]
        
        except Exception as e:
            print(f"[UNBAN ERROR] {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(10)
