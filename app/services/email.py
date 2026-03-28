import smtplib
from email.message import EmailMessage

from app.core.config import Settings


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send_code(
        self,
        *,
        to_email: str,
        subject: str,
        heading: str,
        code: str,
        body: str,
    ) -> None:
        if not self._settings.smtp_host or not self._settings.smtp_from_email:
            raise RuntimeError(
                "SMTP не настроен. Укажите SMTP_HOST и SMTP_FROM_EMAIL для реальной отправки писем."
            )

        message = EmailMessage()
        message["From"] = self._settings.smtp_from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(
            f"{heading}\n\nКод: {code}\n\n{body}\n\nЕсли это были не вы, проигнорируйте письмо."
        )

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20) as smtp:
            if self._settings.smtp_use_tls:
                smtp.starttls()
            if self._settings.smtp_username and self._settings.smtp_password:
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
            smtp.send_message(message)
