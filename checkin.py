import requests
import base64
import hashlib
import hmac
import json
import os
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pypushdeer import PushDeer
from logging_config import init_logger


class CheckinStatus(Enum):
    """签到状态"""

    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class ExchangePlan(Enum):
    """兑换计划"""

    PLAN100 = "plan100"
    PLAN200 = "plan200"
    PLAN500 = "plan500"


class APIEndpoint(Enum):
    """API端点"""

    CHECKIN = "/api/user/checkin"
    STATUS = "/api/user/status"
    POINTS = "/api/user/points"
    EXCHANGE = "/api/user/exchange"


class LogEmoji:
    """日志 Emoji 常量"""

    SUCCESS = "✅"
    FAIL = "❌"
    REPEAT = "🔄"
    PENDING = "⏳"
    CHECKIN = "🎫"
    STATUS = "📊"
    POINTS = "💰"
    EXCHANGE = "🎁"
    START = "🚀"
    END = "🏁"
    COOKIE = "🍪"
    DOMAIN = "🌐"
    WARNING = "⚠️ "
    ERROR = "🔴"
    INFO = "ℹ️ "


def log_method(func):
    """日志装饰器"""

    def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        emoji_map = {
            "checkin": LogEmoji.CHECKIN,
            "get_status": LogEmoji.STATUS,
            "get_points": LogEmoji.POINTS,
            "exchange": LogEmoji.EXCHANGE,
        }
        emoji = emoji_map.get(method_name, LogEmoji.INFO)
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {LogEmoji.ERROR} {method_name} 执行失败: {e}")

            DEFAULT_ERRORS = {
                "checkin": {"status": "签到失败", "points": "0", "message": ""},
                "get_status": ("None 天", -2),
                "get_points": ("None 积分", 0),
                "exchange": "",
            }

            if method_name in DEFAULT_ERRORS:
                error_template = DEFAULT_ERRORS[method_name]
                if isinstance(error_template, dict):
                    error_result = error_template.copy()
                    error_result["message"] = f"执行失败: {e}"
                    return error_result
                return error_template
            raise

    return wrapper


class Config:
    """应用配置"""

    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
    ENV_FEISHU_WEBHOOK = "FEISHU_WEBHOOK"
    ENV_FEISHU_SECRET = "FEISHU_SECRET"
    ENV_COOKIES = "GLADOS_COOKIES"
    ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
    ENV_VERBOSE = "GLADOS_VERBOSE"
    ENV_COOKIE_EXPIRE_WARN_DAYS = "COOKIE_EXPIRE_WARN_DAYS"

    """默认兑换计划"""
    DEFAULT_EXCHANGE_PLAN = "plan500"

    """默认是否输出详细响应"""
    DEFAULT_VERBOSE = False

    """默认提前多少天提醒 Cookie 过期"""
    DEFAULT_COOKIE_EXPIRE_WARN_DAYS = 7

    """默认域名"""
    DOMAINS = ["glados.cloud", "railgun.info"]

    """兑换计划列表"""
    EXCHANGE_PLANS = {
        ExchangePlan.PLAN100.value: 100,
        ExchangePlan.PLAN200.value: 200,
        ExchangePlan.PLAN500.value: 500,
    }

    def __init__(self):
        self.push_key: str = ""
        self.feishu_webhook: str = ""
        self.feishu_secret: str = ""
        self.cookies_list: List[str] = []
        self.exchange_plan: str = self.DEFAULT_EXCHANGE_PLAN
        self.verbose: bool = self.DEFAULT_VERBOSE
        self.cookie_expire_warn_days: int = self.DEFAULT_COOKIE_EXPIRE_WARN_DAYS
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        feishu_webhook_env: Optional[str] = os.environ.get(self.ENV_FEISHU_WEBHOOK)
        feishu_secret_env: Optional[str] = os.environ.get(self.ENV_FEISHU_SECRET)
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)
        exchange_plan_env: Optional[str] = os.environ.get(self.ENV_EXCHANGE_PLAN)
        verbose_env: Optional[str] = os.environ.get(self.ENV_VERBOSE)
        cookie_expire_warn_days_env: Optional[str] = os.environ.get(self.ENV_COOKIE_EXPIRE_WARN_DAYS)

        if push_key_env:
            self.push_key = push_key_env

        if feishu_webhook_env:
            self.feishu_webhook = feishu_webhook_env

        if feishu_secret_env:
            self.feishu_secret = feishu_secret_env

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                raise ValueError(f"环境变量 '{self.ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

        if not exchange_plan_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 未设置，将使用默认兑换计划 {self.DEFAULT_EXCHANGE_PLAN}。")
            self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN
        else:
            if exchange_plan_env in self.EXCHANGE_PLANS:
                self.exchange_plan = exchange_plan_env
                logger.info(f"{LogEmoji.SUCCESS} 使用指定的兑换计划: {self.exchange_plan}")
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 的值 '{exchange_plan_env}' 无效，将使用默认兑换计划 {self.DEFAULT_EXCHANGE_PLAN}。")
                self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN

        logger.info(f"{LogEmoji.INFO} 共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        if self.feishu_webhook:
            logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_FEISHU_WEBHOOK} 已设置，将优先使用飞书推送。")
        elif self.push_key:
            logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_PUSH_KEY} 已设置，将使用 PushDeer 推送。")
        else:
            logger.info(f"{LogEmoji.INFO} 未设置推送渠道，仅输出 Actions 日志。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_EXCHANGE_PLAN}: {self.exchange_plan}。")

        if verbose_env:
            verbose_env_lower = verbose_env.lower()
            if verbose_env_lower in ["true", "1", "yes", "y"]:
                self.verbose = True
            elif verbose_env_lower in ["false", "0", "no", "n"]:
                self.verbose = False
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_VERBOSE}' 的值 '{verbose_env}' 无效，将使用默认值 {self.DEFAULT_VERBOSE}。")

        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_VERBOSE}: {self.verbose}。")

        if cookie_expire_warn_days_env:
            try:
                warn_days = int(cookie_expire_warn_days_env)
                if warn_days < 0:
                    raise ValueError
                self.cookie_expire_warn_days = warn_days
            except ValueError:
                logger.warning(
                    f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIE_EXPIRE_WARN_DAYS}' 的值 "
                    f"'{cookie_expire_warn_days_env}' 无效，将使用默认值 {self.DEFAULT_COOKIE_EXPIRE_WARN_DAYS}。"
                )

        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_COOKIE_EXPIRE_WARN_DAYS}: {self.cookie_expire_warn_days}。")


@dataclass()
class CookieExpirationInfo:
    """Cookie 过期信息"""

    cookie_index: int
    user_id: Optional[Union[int, str]]
    expire_ms: Optional[int]
    expire_at: Optional[datetime]
    days_left: Optional[int]
    should_warn: bool
    message: str


class CookieInspector:
    """解析 koa-session Cookie 过期时间"""

    SESSION_COOKIE_NAME = "koa:sess="

    @classmethod
    def inspect(cls, cookie: str, cookie_index: int, warn_days: int) -> CookieExpirationInfo:
        payload = cls._extract_session_payload(cookie)
        if not payload:
            return CookieExpirationInfo(
                cookie_index=cookie_index,
                user_id=None,
                expire_ms=None,
                expire_at=None,
                days_left=None,
                should_warn=True,
                message=f"Cookie {cookie_index} 未解析到 koa:sess，无法判断登录态过期时间，请确认 Cookie 是否完整。",
            )

        user_id = payload.get("userId")
        expire_ms = payload.get("_expire")
        if not isinstance(expire_ms, (int, float)):
            return CookieExpirationInfo(
                cookie_index=cookie_index,
                user_id=user_id,
                expire_ms=None,
                expire_at=None,
                days_left=None,
                should_warn=True,
                message=f"Cookie {cookie_index} 未解析到 _expire，无法判断登录态过期时间，请确认 Cookie 是否完整。",
            )

        expire_at = datetime.fromtimestamp(expire_ms / 1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=8)))
        now = datetime.now(timezone(timedelta(hours=8)))
        seconds_left = (expire_at - now).total_seconds()
        days_left = int(seconds_left // 86400)
        should_warn = seconds_left <= warn_days * 86400

        if seconds_left <= 0:
            message = f"Cookie {cookie_index} 已过期，请重新登录获取新的 Cookie。"
        elif should_warn:
            message = f"Cookie {cookie_index} 将在 {days_left} 天内过期，到期时间 {expire_at:%Y-%m-%d %H:%M:%S}。"
        else:
            message = f"Cookie {cookie_index} 到期时间 {expire_at:%Y-%m-%d %H:%M:%S}，剩余约 {days_left} 天。"

        if user_id is not None:
            message = f"{message} 用户 ID: {user_id}。"

        return CookieExpirationInfo(
            cookie_index=cookie_index,
            user_id=user_id,
            expire_ms=int(expire_ms),
            expire_at=expire_at,
            days_left=days_left,
            should_warn=should_warn,
            message=message,
        )

    @classmethod
    def _extract_session_payload(cls, cookie: str) -> Optional[Dict]:
        session_value = None
        for part in cookie.split(";"):
            item = part.strip()
            if item.startswith(cls.SESSION_COOKIE_NAME):
                session_value = item[len(cls.SESSION_COOKIE_NAME):]
                break

        if not session_value:
            return None

        try:
            padded = session_value + "=" * (-len(session_value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
            payload = json.loads(decoded.decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None


class API:
    """API 调用"""

    CHECKIN_URL = APIEndpoint.CHECKIN.value
    STATUS_URL = APIEndpoint.STATUS.value
    POINTS_URL = APIEndpoint.POINTS.value
    EXCHANGE_URL = APIEndpoint.EXCHANGE.value

    def __init__(self, domain: str, cookie_index: int = 0, verbose: bool = False):
        self.domain: str = domain
        self.cookie_index: int = cookie_index
        self.verbose: bool = verbose
        self.headers: Dict[str, str] = self._get_headers()
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "origin": f"https://{self.domain}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        }

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        log_message = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {message}"

        if force or self.verbose:
            if level == "info":
                logger.info(log_message)
            elif level == "warning":
                logger.warning(log_message)
            elif level == "error":
                logger.error(log_message)

    def _get_full_url(self, path: str) -> str:
        """获取完整 URL"""
        return f"https://{self.domain}{path}"

    def _make_request(self, url: str, method: str, data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
        """发送 HTTP 请求"""
        session_headers = self.headers.copy()
        session_headers["cookie"] = cookies

        try:
            if method.upper() == "POST":
                response = self.session.post(url, headers=session_headers, data=json.dumps(data), timeout=(60, 120))
            elif method.upper() == "GET":
                response = self.session.get(url, headers=session_headers, timeout=(60, 120))
            else:
                self._log("error", LogEmoji.ERROR, f"不支持的 HTTP 方法: {method}", force=True)
                return None

            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"向 {url} 发起的请求失败，状态码 {response.status_code}。响应内容: {response.text}", force=True)
                return None
            return response
        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"向 {url} 发起请求时发生网络错误: {e}", force=True)
            return None

    def _get_checkin_data(self) -> Dict[str, str]:
        """获取签到数据"""
        return {"token": self.domain}

    @log_method
    def checkin(self, cookies: str) -> Dict[str, Union[str, CheckinStatus]]:
        """执行签到"""
        url = self._get_full_url(self.CHECKIN_URL)
        checkin_data = self._get_checkin_data()
        response = self._make_request(url, "POST", checkin_data, cookies)

        result = {
            "status": "签到失败",
            "points": "0",
            "message": "",
            "code": CheckinStatus.FAILURE,
        }

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "无消息字段")
            points = str(data.get("points", 0))

            if code == CheckinStatus.SUCCESS.value:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points}, message : {message} }}")
                result["code"] = CheckinStatus.SUCCESS
                result["status"] = "签到成功"
                result["points"] = points
                result["message"] = message
            elif code == CheckinStatus.REPEAT.value:
                self._log("info", LogEmoji.REPEAT, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.REPEAT
                result["status"] = "重复签到"
                result["points"] = "0"
                result["message"] = message
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.FAILURE
                result["status"] = "签到失败"
                result["points"] = "0"
                result["message"] = message
        else:
            self._log("warning", LogEmoji.WARNING, "签到失败", force=True)
            result["code"] = CheckinStatus.FAILURE
            result["status"] = "签到失败"
            result["message"] = "网络请求失败"

        return result

    @log_method
    def get_status(self, cookies: str) -> Tuple[str, int]:
        """获取状态"""

        url = self._get_full_url(self.STATUS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            left_days = data.get("data", {}).get("leftDays", None)

            if left_days is not None:
                left_days_int = int(float(left_days))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, leftDays : {left_days_int} 天}}")
                return f"{left_days_int} 天", code
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, leftDays : {left_days} 天}}", force=True)
                return "None 天", code
        else:
            self._log("warning", LogEmoji.WARNING, "获取状态失败", force=True)
            return "None 天", -2

    @log_method
    def get_points(self, cookies: str) -> Tuple[str, int]:
        """获取积分"""
        url = self._get_full_url(self.POINTS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            points = data.get("points", None)

            if points is not None:
                points_int = int(float(points))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points_int} 积分}}")
                points_str = f"{points_int} 积分"
                points_num = points_int
                return points_str, points_num
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, points : {points} 积分}}", force=True)
                return "None 积分", 0
        else:
            self._log("warning", LogEmoji.WARNING, "获取积分失败", force=True)
            return "None 积分", 0

    @log_method
    def exchange(self, cookies: str, plan: str, required_points: int) -> str:
        """执行兑换"""
        url = self._get_full_url(self.EXCHANGE_URL)
        response = self._make_request(url, "POST", {"planType": plan}, cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "未知错误")

            if code == 0:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, message : {message} }}")
                return f"兑换成功: {plan}"
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                return f"兑换失败: {message}"
        else:
            self._log("warning", LogEmoji.WARNING, "兑换失败", force=True)
            return "兑换失败"


@dataclass()
class CheckinResult:
    """签到结果"""

    cookie_index: int
    domain: str
    status: str = "签到失败"
    points: str = "0"
    days: str = "None"
    points_total: str = "None"
    exchange: str = "未兑换"
    code: CheckinStatus = CheckinStatus.FAILURE  # 0: 成功, 1: 重复, -2: 失败

    def to_dict(self) -> Dict[str, Union[str, CheckinStatus]]:
        result_dict = asdict(self)
        return result_dict


class PushService:
    """推送服务"""

    def __init__(self, config: Config):
        self.config = config

    def send(self, title: str, content: str) -> bool:
        """发送推送"""
        if self.config.feishu_webhook:
            return self._send_feishu(title, content)

        if not self.config.push_key:
            logger.info(f"{LogEmoji.WARNING} 未设置推送密钥，跳过推送通知。")
            return False

        try:
            pushdeer = PushDeer(pushkey=self.config.push_key)
            pushdeer.send_text(title, desp=content)
            logger.info(f"{LogEmoji.SUCCESS} 推送通知发送成功。")
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} 发送推送通知失败: {e}")
            return False

    def _send_feishu(self, title: str, content: str) -> bool:
        """发送飞书自定义机器人推送"""
        message = f"{title}\n\n{content}".strip()
        payload = {
            "msg_type": "text",
            "content": {
                "text": message,
            },
        }

        if self.config.feishu_secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._build_feishu_sign(timestamp, self.config.feishu_secret)

        try:
            response = requests.post(self.config.feishu_webhook, json=payload, timeout=(10, 30))
            data = response.json()
            if response.ok and data.get("code", data.get("StatusCode")) in (0, None):
                logger.info(f"{LogEmoji.SUCCESS} 飞书推送通知发送成功。")
                return True

            logger.error(f"{LogEmoji.ERROR} 飞书推送通知失败: HTTP {response.status_code}, 响应: {response.text}")
            return False
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} 发送飞书推送通知失败: {e}")
            return False

    @staticmethod
    def _build_feishu_sign(timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")


class Checker:
    """签到"""

    def __init__(self, config: Config):
        self.config = config
        self.results = []
        self.cookie_expiration_infos: List[CookieExpirationInfo] = []

    def _log(self, cookie_idx: int, domain: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        if self.config.verbose or force:
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.DOMAIN}[{domain}] {emoji} {message}")

    def checkin_all(self):
        """执行所有签到任务"""
        cookie_count = len(self.config.cookies_list)
        domain_count = len(self.config.DOMAINS)
        total_tasks = cookie_count * domain_count
        task_idx = 0

        logger.info(f"{LogEmoji.INFO} 共 {cookie_count} 个 Cookie, {domain_count} 个域名, 共 {total_tasks} 个任务")

        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.START} ========== 开始处理 Cookie {cookie_idx} ==========")
            cookie_expiration_info = CookieInspector.inspect(cookie, cookie_idx, self.config.cookie_expire_warn_days)
            self.cookie_expiration_infos.append(cookie_expiration_info)
            log_level = logging.WARNING if cookie_expiration_info.should_warn else logging.INFO
            logger.log(log_level, f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.INFO} {cookie_expiration_info.message}")

            for domain in self.config.DOMAINS:
                task_idx += 1
                logger.info(f"{LogEmoji.INFO} ----- 任务 {task_idx}/{total_tasks}: {LogEmoji.COOKIE}[{cookie_idx}] on {LogEmoji.DOMAIN}[{domain}] -----")

                result = self._checkin_on_domain(cookie, cookie_idx, domain)
                self.results.append(result)

                result_message = f"结果: {result.status}"
                if result.code == CheckinStatus.SUCCESS:
                    if self.config.verbose:
                        result_message = f"结果: {result.status}, 获得 {result.points} 积分, 剩余 {result.days}, 总 {result.points_total}, {result.exchange}"
                    self._log(cookie_idx, domain, LogEmoji.SUCCESS, result_message, force=True)
                else:
                    self._log(cookie_idx, domain, LogEmoji.WARNING, result_message, force=True)

    def _checkin_on_domain(self, cookie: str, cookie_idx: int, domain: str) -> CheckinResult:
        result = CheckinResult(cookie_idx, domain)

        with API(domain, cookie_idx, verbose=self.config.verbose) as api:
            # 1. 获取状态
            self._log(cookie_idx, domain, LogEmoji.STATUS, "查询剩余天数")
            days_str, status_code = api.get_status(cookie)
            result.days = days_str

            # 2. 签到
            self._log(cookie_idx, domain, LogEmoji.CHECKIN, "执行签到")
            checkin_result = api.checkin(cookie)
            result.status = checkin_result["status"]
            result.code = checkin_result.get("code", CheckinStatus.FAILURE)

            # 3. 获取积分
            self._log(cookie_idx, domain, LogEmoji.POINTS, "查询总积分")
            points_str, points_num = api.get_points(cookie)
            result.points_total = points_str

            # 4. 执行兑换
            required_points = self.config.EXCHANGE_PLANS.get(self.config.exchange_plan, 500)
            self._log(
                cookie_idx,
                domain,
                LogEmoji.EXCHANGE,
                f"开始兑换 {self.config.exchange_plan} (需要 {required_points} 积分)",
            )
            result.exchange = api.exchange(cookie, self.config.exchange_plan, required_points)

        return result

    def get_results(self) -> List[Dict[str, str]]:
        """获取所有结果"""
        return [result.to_dict() for result in self.results]

    def format_results(self) -> Tuple[str, str, str, bool]:
        """格式化结果"""
        results = self.get_results()

        success_count = sum(1 for r in results if r["code"] == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == CheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r["code"] == CheckinStatus.FAILURE)

        action_lines = self._build_actionable_notification_lines(results)
        should_notify = bool(action_lines)
        title = f"GLaDOS 签到, 成功{success_count}, 失败{fail_count}, 重复{repeat_count}"
        if should_notify:
            title = f"GLaDOS 需要关注: {len(action_lines)} 条提醒"

        log_content_lines = []
        if self.cookie_expiration_infos:
            log_content_lines.append("【Cookie 到期检查】")
            for info in self.cookie_expiration_infos:
                line = info.message
                if self.config.verbose or info.should_warn:
                    log_content_lines.append(line)

            if len(log_content_lines) > 1:
                log_content_lines.append("")

        log_content_lines.append("【签到结果】")
        for i, res in enumerate(results, 1):
            line = f"#{i} P:{res['points']} 剩余:{res['days']} 总积分:{res['points_total']} | {res['status']} | {res['exchange']}"

            if self.config.verbose:
                log_line = line
            else:
                log_line = f"#{i} {res['status']}"
            log_content_lines.append(log_line)

        content = "\n".join(action_lines)
        log_content = "\n".join(log_content_lines)
        return title, content, log_content, should_notify

    def _build_actionable_notification_lines(self, results: List[Dict[str, str]]) -> List[str]:
        """只生成需要打扰用户的通知内容"""
        lines = []

        cookie_warning_lines = [info.message for info in self.cookie_expiration_infos if info.should_warn]
        if cookie_warning_lines:
            lines.append("【Cookie 到期提醒】")
            lines.extend(cookie_warning_lines)

        fully_failed_cookie_lines = []
        for cookie_idx in sorted({res["cookie_index"] for res in results}):
            cookie_results = [res for res in results if res["cookie_index"] == cookie_idx]
            if cookie_results and all(res["code"] == CheckinStatus.FAILURE for res in cookie_results):
                domains = ", ".join(f"{res['domain']}:{res['status']}" for res in cookie_results)
                fully_failed_cookie_lines.append(f"Cookie {cookie_idx} 所有域名签到失败，请检查 Cookie 是否过期或失效。{domains}")

        if fully_failed_cookie_lines:
            if lines:
                lines.append("")
            lines.append("【签到失败提醒】")
            lines.extend(fully_failed_cookie_lines)

        exchange_success_lines = []
        for res in results:
            exchange_result = str(res.get("exchange", ""))
            if exchange_result.startswith("兑换成功"):
                exchange_success_lines.append(f"Cookie {res['cookie_index']} {res['domain']} {exchange_result}，剩余:{res['days']} 总积分:{res['points_total']}")

        if exchange_success_lines:
            if lines:
                lines.append("")
            lines.append("【积分兑换提醒】")
            lines.extend(exchange_success_lines)

        return lines


# 初始化日志
logger = init_logger()


def main():
    """主函数"""
    try:
        # 1. 加载配置
        logger.info(f"{LogEmoji.START} 步骤 1: 加载配置")
        config = Config()

        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的 Cookie, 退出程序。")
            title, content = "# 未找到 cookies!", ""
            should_notify = True
        else:
            # 2. 执行签到
            logger.info(f"{LogEmoji.START} 步骤 2: 执行签到")
            checker = Checker(config)
            checker.checkin_all()

            # 3. 格式化结果
            logger.info(f"{LogEmoji.START} 步骤 3: 格式化结果")
            title, content, log_content, should_notify = checker.format_results()
            logger.info(f"\n{LogEmoji.END}========== 签到总结 ==========\n{title}\n{log_content}")

    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 主程序执行过程中发生未预期的错误: {e}")
        title, content, log_content = "# 脚本执行出错", str(e), str(e)
        should_notify = True

    # 4. 发送推送
    logger.info(f"{LogEmoji.START} 步骤 4: 发送推送")
    if not should_notify:
        logger.info(f"{LogEmoji.INFO} 本次没有 Cookie 临期、整体签到失败或兑换成功，跳过推送通知。")
    elif "config" in locals():
        push_service = PushService(config)
        push_service.send(title, content)
    else:
        logger.info(f"{LogEmoji.WARNING} 配置未完成加载，跳过推送通知。")
    logger.info(f"{LogEmoji.END} 签到完成")


if __name__ == "__main__":
    main()
