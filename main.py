#!/usr/bin/env python3
"""
AstrBot v4 短视频解析插件
解析短视频/图集分享链接并发送直链内容。
支持从纯文本和QQ小程序卡片（JSON消息段）中提取链接。
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Tuple

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain, Video
from astrbot.api.star import Context, Star

# ---- 链接匹配正则 ----

VIDEO_SHARE_URL_REGEX = re.compile(
    r"(https?://)?(v\.douyin\.com|www\.iesdouyin\.com|www\.douyin\.com"
    r"|v\.kuaishou\.com|share\.xiaochuankeji\.cn|v\.ixigua\.com"
    r"|h5\.pipix\.com|isee\.weishi\.qq\.com|share\.huoshan\.com"
    r"|www\.pearvideo\.com|h5\.pipigx\.com|xspshare\.baidu\.com"
    r"|v\.huya\.com|www\.acfun\.cn|weibo\.com|weibo\.cn"
    r"|meipai\.com|doupai\.cc|kg\.qq\.com|6\.cn"
    r"|xinpianchang\.com|haokan\.baidu\.com|haokan\.hao123\.com"
    r"|www\.xiaohongshu\.com|xhslink\.com|bilibili\.com|b23\.tv)"
    r"(\S*)"
)

# ---- 默认配置 ----

DEFAULT_PARSER_API_BASE_URL = "http://127.0.0.1:17992"
DEFAULT_VIDEO_MAX_SIZE_MB = 50
DEFAULT_TIMEOUT_MS = 15000
DEFAULT_UNTITLED_TITLE = "未命名"
DEFAULT_UNKNOWN_AUTHOR = "未知作者"
DEFAULT_REMOTE_FILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Encoding": "identity",
}

# ---- 工具函数 ----


def request_json(url: str, *, timeout_ms: int) -> Tuple[Any, int]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_ms / 1000.0) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc

    return json.loads(body), status_code


def regexp_match_url_from_string(text: str) -> Optional[str]:
    match = VIDEO_SHARE_URL_REGEX.search(text)
    if match is None:
        return None

    value = match.group(0)
    if "b23.tv" in value:
        value = value.replace(r"\/", "/").split("?", 1)[0]
    if not value.startswith("http"):
        return f"https://{value}"
    return value


def extract_url_from_event_text(event: AstrMessageEvent) -> Optional[str]:
    """从事件的纯文本内容中提取视频链接。"""
    raw_text = event.get_message_str() or ""
    return regexp_match_url_from_string(raw_text)


def extract_url_from_json_segments(event: AstrMessageEvent) -> Optional[str]:
    """从 QQ 小程序 / JSON 消息段中提取视频平台链接。

    直接把 AstrMessageEvent 里能拿到的所有消息内容序列化成字符串，
    在其中搜索视频平台 URL——比遍历链式结构更可靠。
    """
    candidates: List[str] = []

    # 1) message_obj 整体序列化
    msg_obj = getattr(event, "message_obj", None)
    if msg_obj is not None:
        try:
            candidates.append(json.dumps(msg_obj, default=str, ensure_ascii=False))
        except Exception:
            candidates.append(str(msg_obj))

    # 2) 取原始消息链（list）
    for attr in ("message_chain", "messages", "message"):
        chain = getattr(event, attr, None)
        if isinstance(chain, list):
            try:
                candidates.append(json.dumps(chain, default=str, ensure_ascii=False))
            except Exception:
                candidates.append(str(chain))

    # 3) message_obj 内部的 .message / .messages / .data  list
    if msg_obj is not None:
        for sub_attr in ("message", "messages", "message_chain", "data"):
            sub = getattr(msg_obj, sub_attr, None)
            if isinstance(sub, (list, dict)):
                try:
                    candidates.append(json.dumps(sub, default=str, ensure_ascii=False))
                except Exception:
                    candidates.append(str(sub))

    # 4) raw_message 字符串
    raw_msg = getattr(event, "raw_message", None) or getattr(event, "raw", None)
    if raw_msg:
        candidates.append(str(raw_msg))

    for text in candidates:
        url = regexp_match_url_from_string(text)
        if url:
            return url

    return None


def parse_remote_file_size_from_headers(headers: Mapping[str, str]) -> int | None:
    content_range = str(headers.get("Content-Range") or "").strip()
    if content_range:
        match = re.search(r"/(\d+)\s*$", content_range)
        if match:
            return int(match.group(1))

    content_length = str(headers.get("Content-Length") or "").strip()
    if content_length.isdigit():
        return int(content_length)
    return None


def build_remote_file_metadata_requests(file_url: str) -> List[urllib.request.Request]:
    return [
        urllib.request.Request(
            file_url, headers=DEFAULT_REMOTE_FILE_HEADERS, method="HEAD"
        ),
        urllib.request.Request(
            file_url,
            headers={**DEFAULT_REMOTE_FILE_HEADERS, "Range": "bytes=0-0"},
            method="GET",
        ),
    ]


def ensure_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def ensure_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [ensure_dict(item) for item in value]


def to_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def empty_fallback(value: str, fallback: str) -> str:
    return value if value.strip() else fallback


def _pick_first_str(data: Dict[str, Any], *keys: str) -> Optional[str]:
    """从 dict 中按顺序尝试多个 key，返回第一个非空字符串值。"""
    for key in keys:
        value = data.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _component_to_dict(component: Any) -> Dict[str, Any]:
    """把 AstrBot 消息组件转成 OneBot dict 格式。"""
    if hasattr(component, "to_dict"):
        return component.to_dict()
    if hasattr(component, "dict"):
        return component.dict()
    if hasattr(component, "__dict__"):
        d = component.__dict__
        type_val = d.get("type") or getattr(component, "type", None)
        data_val = d.get("data") or {}
        return {"type": str(type_val), "data": data_val}
    return {"type": "text", "data": {"text": str(component)}}


# ---- 插件主体 ----


class VideoParserPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.parser_api_base_url = (
            str(config.get("parser_api_base_url") or DEFAULT_PARSER_API_BASE_URL).strip()
            or DEFAULT_PARSER_API_BASE_URL
        )
        self.video_max_size_mb = to_positive_int(
            config.get("video_max_size_mb"), DEFAULT_VIDEO_MAX_SIZE_MB
        )
        self.request_timeout_ms = to_positive_int(
            config.get("request_timeout_ms"), DEFAULT_TIMEOUT_MS
        )
        self.send_cover = bool(config.get("send_cover", True))
        self.processing_message = str(config.get("processing_message") or "ikun解析bot正在处理中。。。").strip()
        logger.info(
            f"video_parser initialized: "
            f"parser_api_base_url={self.parser_api_base_url} "
            f"video_max_size_mb={self.video_max_size_mb} "
            f"send_cover={self.send_cover}"
        )

    # ---- 消息事件处理器 ----

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        # 1) 先尝试从纯文本中提取 URL
        share_url = extract_url_from_event_text(event)
        # 2) 如果没找到，尝试从 JSON/小程序消息段中提取（如 B站小程序卡片）
        if share_url is None:
            share_url = extract_url_from_json_segments(event)
            if share_url is not None:
                logger.info(f"video_parser extracted URL from JSON segment: {share_url}")
            else:
                # 调试：dump 消息结构以便排查
                try:
                    msg_obj = getattr(event, "message_obj", None)
                    logger.info(
                        "video_parser: no URL found in text or JSON segments, "
                        f"message_obj type={type(msg_obj).__name__}, "
                        f"attrs={[a for a in dir(msg_obj) if not a.startswith('_')][:20] if msg_obj else 'None'}"
                    )
                except Exception:
                    pass
        if share_url is None:
            return

        if self.processing_message:
            yield event.plain_result(self.processing_message)

        try:
            video_data = await self.parse_video_share_url(share_url)
        except Exception as exc:
            logger.error(f"video_parser failed to parse url={share_url}: {exc}")
            return

        if "douyin.com" in share_url and str(
            video_data.get("video_url") or ""
        ).strip():
            async for result in self.handle_video(event, video_data, direct=True):
                yield result
            return
        if ensure_list(video_data.get("images")):
            async for result in self.handle_album(event, video_data):
                yield result
            return
        if str(video_data.get("video_url") or "").strip():
            async for result in self.handle_video(event, video_data, direct=False):
                yield result
            return

        yield event.plain_result("解析成功，但链接内容好像既不是视频也不是图集呢")

    # ---- 图集处理 ----

    async def handle_album(self, event: AstrMessageEvent, data: Dict[str, Any]):
        images = ensure_list(data.get("images"))
        title = str(data.get("title") or "").strip()
        author = str(ensure_dict(data.get("author")).get("name") or "").strip()
        total = len(images)
        sender_name = empty_fallback(author, DEFAULT_UNKNOWN_AUTHOR)

        # 构建摘要文字
        summary = f"图集解析成功！共 {total} 张图片"
        if title or author:
            summary += (
                f"\n标题: {empty_fallback(title, DEFAULT_UNTITLED_TITLE)}"
                f"\n作者: {sender_name}"
            )

        # 构建 OneBot 格式的转发消息节点
        forward_nodes: List[Dict[str, Any]] = []
        # 摘要节点
        forward_nodes.append({
            "type": "node",
            "data": {
                "name": sender_name,
                "uin": "10000",
                "content": [{"type": "text", "data": {"text": summary}}],
            },
        })
        # 图片节点：用 Image.fromURL 构建，再转成 OneBot dict
        for index, image in enumerate(images, start=1):
            image_url = str(image.get("url") or "").strip()
            if not image_url:
                continue
            img_component = Image.fromURL(image_url)
            img_dict = _component_to_dict(img_component)
            node_content: List[Dict[str, Any]] = [img_dict]
            if total > 1:
                node_content.append(
                    {"type": "text", "data": {"text": f"第 {index} / {total} 张"}}
                )
            forward_nodes.append({
                "type": "node",
                "data": {
                    "name": sender_name,
                    "uin": "10000",
                    "content": node_content,
                },
            })

        if not forward_nodes:
            return

        # 通过平台适配器发送合并转发
        if await self._do_send_forward(event, forward_nodes):
            return

        # Fallback：逐条发送
        yield event.plain_result(summary)
        for index, image in enumerate(images, start=1):
            image_url = str(image.get("url") or "").strip()
            if not image_url:
                continue
            chain: List[Any] = [Image.fromURL(image_url)]
            if total > 1:
                chain.append(Plain(f"\n第 {index} / {total} 张"))
            yield event.chain_result(chain)

    async def _do_send_forward(
        self,
        event: AstrMessageEvent,
        forward_nodes: List[Dict[str, Any]],
    ) -> bool:
        """通过平台适配器发送合并转发消息。"""
        raw_event: Dict[str, Any] = getattr(event, "raw_event", None) or {}
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None:
            for attr in ("raw_event", "event", "_event", "data"):
                re = getattr(msg_obj, attr, None)
                if isinstance(re, dict):
                    raw_event = {**raw_event, **re}
                    break

        message_type = str(raw_event.get("message_type") or "")
        group_id = raw_event.get("group_id")
        user_id = raw_event.get("user_id") or event.get_sender_id()

        if not message_type and group_id:
            message_type = "group"
        elif not message_type and user_id:
            message_type = "private"

        params: Dict[str, Any] = {"messages": forward_nodes}
        if message_type == "group" and group_id:
            params["group_id"] = group_id
            params["message_type"] = "group"
        elif user_id:
            params["user_id"] = user_id
            params["message_type"] = "private"

        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "send_forward_msg"):
            logger.warning("video_parser _do_send_forward: event.bot.send_forward_msg not available")
            return False

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: bot.send_forward_msg(**params))
            return True
        except Exception as exc:
            logger.warning(f"video_parser _do_send_forward failed: {exc}")
            return False

    # ---- 视频处理 ----

    async def handle_video(
        self,
        event: AstrMessageEvent,
        data: Dict[str, Any],
        *,
        direct: bool,
    ):
        tip = (
            "抖音视频解析成功，正在直接发送..."
            if direct
            else "视频解析成功，正在发送视频..."
        )
        yield event.plain_result(tip)

        video_url = str(data.get("video_url") or "").strip()

        # 先发封面（只传 URL，不依赖服务端 DNS）
        if self.send_cover:
            cover_url = _pick_first_str(data, "cover_url", "cover", "thumbnail", "thumb", "poster")
            if cover_url:
                yield event.chain_result([Image.fromURL(cover_url)])
            else:
                logger.info(
                    "video_parser cover not found, available keys: "
                    + ", ".join(str(k) for k in sorted(data.keys()))
                )

        # 再探测视频大小
        try:
            file_size = await self.get_remote_file_size(video_url)
        except Exception as exc:
            logger.warning(
                f"video_parser failed to probe remote file size "
                f"url={video_url} error={exc}"
            )
            yield event.plain_result(
                "获取视频大小失败，无法直接发送，请尝试点击源链接观看。"
            )
            return

        threshold = self.video_max_size_mb * 1024 * 1024
        file_size_mb = file_size / (1024 * 1024)
        if file_size > threshold:
            yield event.plain_result(
                f"视频大小为 {file_size_mb:.2f}MB，"
                f"超过 {self.video_max_size_mb}MB 限制，"
                f"无法直接发送，请尝试点击源链接观看。"
            )
            return

        chain = []
        # 封面已在前面单独发送，这里不再重复

        title = str(data.get("title") or "").strip()
        author = str(ensure_dict(data.get("author")).get("name") or "").strip()
        if title or author:
            chain.append(
                Plain(
                    f"\n标题: {empty_fallback(title, DEFAULT_UNTITLED_TITLE)}"
                    f"\n作者: {empty_fallback(author, DEFAULT_UNKNOWN_AUTHOR)}"
                )
            )
        chain.append(Video.fromURL(video_url))
        yield event.chain_result(chain)

    # ---- 核心解析逻辑 ----

    async def parse_video_share_url(self, share_url: str) -> Dict[str, Any]:
        base_url = self.parser_api_base_url.rstrip("/")
        full_url = (
            f"{base_url}/video/share/url/parse"
            f"?url={urllib.parse.quote(share_url, safe='')}"
        )
        loop = asyncio.get_running_loop()
        payload, _status = await loop.run_in_executor(
            None,
            lambda: request_json(full_url, timeout_ms=self.request_timeout_ms),
        )
        result = ensure_dict(payload)
        if int(result.get("code") or 0) != 200:
            raise RuntimeError(
                f"parser error: {result.get('msg')} ({result.get('code')})"
            )
        return ensure_dict(result.get("data"))

    async def get_remote_file_size(self, file_url: str) -> int:
        loop = asyncio.get_running_loop()
        timeout_seconds = self.request_timeout_ms / 1000.0
        errors: List[str] = []

        for request in build_remote_file_metadata_requests(file_url):
            method = request.get_method()
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda r=request: urllib.request.urlopen(r, timeout=timeout_seconds),
                )
                status_code = int(getattr(response, "status", 200))
                if not 200 <= status_code < 300:
                    raise RuntimeError(f"{method} failed: {status_code}")
                file_size = parse_remote_file_size_from_headers(response.headers)
                if file_size is not None:
                    return file_size
                raise RuntimeError(f"{method} missing size headers")
            except urllib.error.HTTPError as exc:
                errors.append(f"{method} HTTP {exc.code}")
            except urllib.error.URLError as exc:
                errors.append(f"{method} {exc.reason or exc}")
            except RuntimeError as exc:
                errors.append(str(exc))

        raise RuntimeError(
            "; ".join(errors) or "failed to probe remote file size"
        )
