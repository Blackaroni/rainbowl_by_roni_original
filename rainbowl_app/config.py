from __future__ import annotations

from dataclasses import dataclass

from .env import get_env_bool, get_env_int, get_env_value, load_env_file


load_env_file()


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "rainbowl"
    user: str = "postgres"
    password: str = ""
    schema: str = "rainbowl"
    sslmode: str | None = None
    connect_timeout: int | None = None

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            host=get_env_value("RAINBOWL_DB_HOST", "DB_HOST", default="localhost") or "localhost",
            port=get_env_int("RAINBOWL_DB_PORT", "DB_PORT", default=5432),
            name=get_env_value("RAINBOWL_DB_NAME", "DB_NAME", default="rainbowl") or "rainbowl",
            user=get_env_value("RAINBOWL_DB_USER", "DB_USER", default="postgres") or "postgres",
            password=get_env_value("RAINBOWL_DB_PASSWORD", "DB_PASSWORD", default="") or "",
            schema=get_env_value("RAINBOWL_DB_SCHEMA", "DB_SCHEMA", default="rainbowl") or "rainbowl",
            sslmode=get_env_value("RAINBOWL_DB_SSLMODE", "DB_SSLMODE"),
            connect_timeout=get_env_int("RAINBOWL_DB_CONNECT_TIMEOUT", "DB_CONNECT_TIMEOUT", default=5),
        )

    def connection_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.name,
            "user": self.user,
            "password": self.password,
        }
        if self.sslmode:
            kwargs["sslmode"] = self.sslmode
        if self.connect_timeout is not None:
            kwargs["connect_timeout"] = self.connect_timeout
        return kwargs


def parse_csv_list(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8010
    cors_allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            host=(
                get_env_value("RAINBOWL_APP_HOST", "APP_HOST", "HOST", default=cls.host)
                or cls.host
            ),
            port=get_env_int("RAINBOWL_APP_PORT", "APP_PORT", "PORT", default=cls.port),
            cors_allowed_origins=parse_csv_list(
                get_env_value("RAINBOWL_CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS", default="")
            ),
        )


@dataclass(frozen=True)
class ReminderEmailConfig:
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    sender_email: str = ""
    recipient_email: str = ""
    use_starttls: bool = True
    enabled: bool = False
    interval_minutes: int = 60

    @classmethod
    def from_env(cls) -> "ReminderEmailConfig":
        sender_email = (
            get_env_value("RAINBOWL_SMTP_SENDER", "SMTP_SENDER")
            or get_env_value("RAINBOWL_SMTP_USER", "SMTP_USER")
            or cls.sender_email
        )
        return cls(
            smtp_host=get_env_value("RAINBOWL_SMTP_HOST", "SMTP_HOST", default=cls.smtp_host) or cls.smtp_host,
            smtp_port=get_env_int("RAINBOWL_SMTP_PORT", "SMTP_PORT", default=cls.smtp_port),
            smtp_user=get_env_value("RAINBOWL_SMTP_USER", "SMTP_USER", default=cls.smtp_user) or cls.smtp_user,
            smtp_password=get_env_value("RAINBOWL_SMTP_PASSWORD", "SMTP_PASSWORD", default=cls.smtp_password)
            or cls.smtp_password,
            sender_email=sender_email,
            recipient_email=(
                get_env_value("RAINBOWL_ALERT_RECIPIENT", "ALERT_RECIPIENT", default=cls.recipient_email)
                or cls.recipient_email
            ),
            use_starttls=not (
                get_env_value("RAINBOWL_SMTP_STARTTLS", "SMTP_STARTTLS", default="true").strip().lower()
                in {"0", "false", "no"}
            ),
            enabled=get_env_bool("RAINBOWL_REMINDERS_ENABLED", "REMINDERS_ENABLED", default=cls.enabled),
            interval_minutes=max(
                1,
                get_env_int(
                    "RAINBOWL_REMINDER_INTERVAL_MINUTES",
                    "REMINDER_INTERVAL_MINUTES",
                    default=cls.interval_minutes,
                ),
            ),
        )

    def is_ready(self) -> bool:
        return self.enabled and self.can_send_email()

    def can_send_email(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_port
            and self.smtp_user
            and self.smtp_password
            and self.sender_email
            and self.recipient_email
        )
