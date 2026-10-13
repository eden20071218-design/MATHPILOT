from datetime import time
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import AwareDatetime, Field, field_validator, model_validator
from app.schemas.knowledge import StrictModel
from app.core.config import settings
import base64


class ReminderSettings(StrictModel):
    enabled: bool = True
    lead_minutes: int = Field(default=10, ge=0, le=10080)
    timezone: str = 'Asia/Shanghai'
    quiet_start: time | None = time(22, 0)
    quiet_end: time | None = time(8, 0)

    @model_validator(mode='after')
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('无效时区') from exc
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError('免打扰开始与结束必须同时设置')
        if self.quiet_start is not None and (self.quiet_start == self.quiet_end or self.quiet_start.tzinfo or self.quiet_end.tzinfo):
            raise ValueError('免打扰时间须为不同的当地时钟时间')
        return self


class SubscriptionInput(StrictModel):
    endpoint: str = Field(max_length=4096)
    keys: dict[str, str]
    expirationTime: float | None = None

    @field_validator('endpoint')
    @classmethod
    def endpoint_allowed(cls, endpoint):
        url = urlsplit(endpoint)
        hosts = [h.strip() for h in settings.push_allowed_hosts.split(',')]
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443) or url.fragment:
            raise ValueError('推送端点必须为可信HTTPS推送服务')
        if not any(url.hostname == h or url.hostname.endswith('.'+h) for h in hosts if h and url.hostname):
            raise ValueError('推送服务域名不在允许名单中')
        return endpoint

    @field_validator('keys')
    @classmethod
    def valid_keys(cls, value):
        if set(value) != {'p256dh', 'auth'}:
            raise ValueError('缺少推送加密参数')
        try:
            public = base64.urlsafe_b64decode(value['p256dh'] + '='*(-len(value['p256dh'])%4))
            auth = base64.urlsafe_b64decode(value['auth'] + '='*(-len(value['auth'])%4))
            if len(public) != 65 or public[0] != 4 or len(auth) != 16:
                raise ValueError()
        except Exception as exc:
            raise ValueError('无效推送密钥') from exc
        return value


class TaskChange(StrictModel):
    action: Literal['postpone', 'reschedule', 'cancel']
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def dates(self):
        if self.action != 'cancel' and (not self.start or not self.end or self.start >= self.end):
            raise ValueError('延期或重排须提供有效的开始与截止时间')
        return self


class FeedbackInput(StrictModel):
    request_key: str = Field(min_length=1, max_length=100)
    score_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    difficulty: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    duration_minutes: int = Field(ge=1, le=1440)
    notes: str = Field(default='', max_length=10000)


class PushReceipt(StrictModel):
    token: str = Field(min_length=20, max_length=100)
    open_windows: int = Field(ge=0, le=1000)
