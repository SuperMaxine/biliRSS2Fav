import argparse
import asyncio
import os

from dotenv import load_dotenv

from src.config import SMTPConfig
from src.notify import EmailNotifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="send test email by .env SMTP config")
    parser.add_argument("body", help="email body")
    parser.add_argument("--subject", default="Command End", help="email subject")
    parser.add_argument("--to", default="", help="override target email")
    parser.add_argument("--env-file", default=".env", help="dotenv path")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    load_dotenv(dotenv_path=args.env_file, override=False)

    to_email = args.to or os.getenv("ALERT_TO_EMAIL", "").strip()
    smtp = SMTPConfig(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=int(os.getenv("SMTP_PORT", "0")),
        user=os.getenv("SMTP_USER", "").strip(),
        password=os.getenv("SMTP_PASS", "").strip(),
        to_email=to_email,
        from_name=os.getenv("SMTP_FROM_NAME", "biliRSS2Fav").strip(),
    )
    notifier = EmailNotifier(smtp)
    await notifier.send(args.subject, args.body)
    print("邮件发送成功")


if __name__ == "__main__":
    asyncio.run(main())
