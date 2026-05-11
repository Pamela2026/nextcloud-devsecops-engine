import requests
import yaml
import traceback

# =========================
# LOAD CONFIG
# =========================
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

SLACK_WEBHOOK = config.get("slack_webhook")


def send_slack_alert(message):
    """
    Sends formatted Slack alert.
    """

    if not SLACK_WEBHOOK:
        print("[SLACK] No webhook configured")
        return

    try:

        payload = {
            "text": message
        }

        response = requests.post(
            SLACK_WEBHOOK,
            json=payload,
            timeout=5
        )

        if response.status_code == 200:

            print("[SLACK] Alert sent")

        else:

            print(
                f"[SLACK ERROR] "
                f"status={response.status_code} "
                f"body={response.text}"
            )

    except Exception:

        print("[SLACK EXCEPTION]")

        traceback.print_exc()
