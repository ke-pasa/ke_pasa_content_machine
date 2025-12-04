import logging
import os
import smtplib
import time
from email.message import EmailMessage

import docker
import requests

logging.basicConfig(level=logging.INFO, format="[exit-notifier] %(asctime)s %(levelname)s: %(message)s")


def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        response.raise_for_status()
        logging.info("Sent Telegram alert")
        return True
    except Exception as exc:  # pragma: no cover - best effort alerting
        logging.error("Failed to send Telegram alert: %s", exc)
        return False


def send_email(message: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST")
    recipient = os.getenv("ALERT_EMAIL")
    if not smtp_host or not recipient:
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    use_starttls = os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}

    email = EmailMessage()
    email["Subject"] = "Docker container exited with non-zero code"
    email["From"] = username or f"noreply@{smtp_host}"
    email["To"] = recipient
    email.set_content(message)

    try:
        with smtplib.SMTP(smtp_host, port, timeout=15) as smtp:
            if use_starttls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(email)
            logging.info("Sent email alert")
            return True
    except Exception as exc:  # pragma: no cover - best effort alerting
        logging.error("Failed to send email alert: %s", exc)
        return False


def notify(message: str) -> None:
    delivered = send_telegram(message)
    delivered = send_email(message) or delivered
    if not delivered:
        logging.warning(
            "Alert delivery failed. Configure TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
            "or SMTP_HOST/ALERT_EMAIL to receive notifications."
        )


def monitor_events() -> None:
    client = docker.from_env()
    logging.info("Listening for container exit events...")
    for event in client.events(decode=True):
        if event.get("Type") != "container" or event.get("Action") != "die":
            continue

        attrs = event.get("Actor", {}).get("Attributes", {})
        exit_code = int(attrs.get("exitCode") or 0)
        container_name = attrs.get("name") or event.get("id")

        if exit_code != 0:
            message = f"Container {container_name} exited with code {exit_code}."
            logging.error(message)
            notify(message)


def main() -> None:
    while True:
        try:
            monitor_events()
        except Exception as exc:  # pragma: no cover - keep retrying if docker socket is flaky
            logging.error("docker event stream failed: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
