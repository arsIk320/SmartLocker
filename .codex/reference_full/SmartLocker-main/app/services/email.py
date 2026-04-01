import smtplib
from email.message import EmailMessage

import httpx

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
        mode = self._resolve_mode()
        if mode == "brevo":
            self._send_via_brevo(
                to_email=to_email,
                subject=subject,
                heading=heading,
                code=code,
                body=body,
            )
            return
        if mode == "console":
            print(
                f"[SmartLocker email fallback] to={to_email} subject={subject} code={code}"
            )
            return
        self._send_via_smtp(
            to_email=to_email,
            subject=subject,
            heading=heading,
            code=code,
            body=body,
        )

    def _resolve_mode(self) -> str:
        mode = self._settings.email_delivery_mode
        if mode == "auto":
            if self._settings.brevo_api_key and self._settings.smtp_from_email:
                return "brevo"
            if self._settings.smtp_host and self._settings.smtp_from_email:
                return "smtp"
            return "console"
        if mode not in {"brevo", "smtp", "console"}:
            raise RuntimeError(
                "Неизвестный EMAIL_DELIVERY_MODE. Используйте auto, brevo, smtp или console."
            )
        return mode

    def _send_via_smtp(
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
                "SMTP не настроен. Укажите SMTP_HOST и SMTP_FROM_EMAIL для отправки писем."
            )

        message = EmailMessage()
        message["From"] = self._settings.smtp_from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(
            f"{heading}\n\nКод: {code}\n\n{body}\n\nЕсли это были не вы, проигнорируйте письмо."
        )

        with smtplib.SMTP(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=20,
        ) as smtp:
            if self._settings.smtp_use_tls:
                smtp.starttls()
            if self._settings.smtp_username and self._settings.smtp_password:
                smtp.login(
                    self._settings.smtp_username,
                    self._settings.smtp_password,
                )
            smtp.send_message(message)

    def _send_via_brevo(
        self,
        *,
        to_email: str,
        subject: str,
        heading: str,
        code: str,
        body: str,
    ) -> None:
        if not self._settings.brevo_api_key or not self._settings.smtp_from_email:
            raise RuntimeError(
                "Brevo не настроен. Укажите BREVO_API_KEY и SMTP_FROM_EMAIL."
            )

        payload = {
            "sender": {
                "name": self._settings.email_from_name,
                "email": self._settings.smtp_from_email,
            },
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": (
                f"{heading}\n\nКод: {code}\n\n{body}\n\n"
                "Если это были не вы, проигнорируйте письмо."
            ),
            "htmlContent": (
                f"<h2>{heading}</h2>"
                f"<p><strong>Код:</strong> {code}</p>"
                f"<p>{body}</p>"
                "<p>Если это были не вы, проигнорируйте письмо.</p>"
            ),
        }

        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": self._settings.brevo_api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Brevo API error {response.status_code}: {response.text}"
            )
