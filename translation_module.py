# translation_module.py - 优化的文本翻译模块 - 性能优化版
from datetime import datetime
from wsgiref.handlers import format_date_time
from time import mktime
import hashlib
import base64
import hmac
from urllib.parse import urlencode
from threading import Lock
import time
import threading
from collections import OrderedDict
import sys
import os

# 尝试使用更快的JSON库
try:
    import ujson as json

    print("使用ujson加速JSON处理")
except ImportError:
    import json

    print("使用标准json库")

# 尝试使用更快的HTTP库
try:
    import httpx

    use_httpx = True
    print("使用httpx加速HTTP请求")
except ImportError:
    import requests

    use_httpx = False
    print("使用标准requests库")

# 支持的语言代码
LANGUAGE_CODES = {
    "中文": "cn",
    "英语": "en",
    "日语": "ja",
    "印尼语": "id",
    "越南语": "vi",
    "泰语": "th",
    "西班牙语": "es"
}

# 语言代码反向映射（用于显示）
LANGUAGE_NAMES = {code: name for name, code in LANGUAGE_CODES.items()}


class LRUCache:
    """基于OrderedDict实现的LRU缓存"""

    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        """获取缓存值，如果存在则移动到末尾（最近使用）"""
        with self.lock:
            if key not in self.cache:
                return None
            # 移动到末尾
            value = self.cache.pop(key)
            self.cache[key] = value
            return value

    def put(self, key, value):
        """添加或更新缓存条目"""
        with self.lock:
            if key in self.cache:
                # 已存在，移除旧值
                self.cache.pop(key)
            elif len(self.cache) >= self.capacity:
                # 达到容量上限，移除最早使用的条目（首个条目）
                self.cache.popitem(last=False)
            # 添加新值到末尾
            self.cache[key] = value

    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()

    def __len__(self):
        """返回缓存中的条目数"""
        return len(self.cache)


class TranslationModule:
    """优化的星火机器翻译模块 - 性能优化版"""

    # 使用__slots__减少内存占用
    __slots__ = ['app_id', 'api_secret', 'api_key', 'url', 'res_id',
                 'lock', 'cache', 'cache_size', 'last_request_time',
                 'request_interval', 'client', 'timeout', 'session_lock']

    def __init__(self, app_id, api_secret, api_key, cache_size=200):
        """
        初始化翻译模块

        参数:
            app_id: APPID
            api_secret: APISecret
            api_key: APIKey
            cache_size: 缓存大小，默认200条
        """
        self.app_id = app_id
        self.api_secret = api_secret
        self.api_key = api_key
        self.url = 'https://itrans.xf-yun.com/v1/its'
        self.res_id = "its_en_cn_word"  # 术语资源ID

        # 线程安全锁
        self.lock = Lock()

        # 翻译结果缓存，使用LRU策略
        self.cache_size = cache_size
        self.cache = LRUCache(capacity=cache_size)

        # 请求速率控制
        self.last_request_time = 0
        self.request_interval = 0.05  # 50ms最小间隔，避免过快请求

        # HTTP客户端设置
        self.timeout = 5.0  # 请求超时设置

        # 如果使用httpx，创建一个客户端实例
        if use_httpx:
            self.client = httpx.Client(timeout=self.timeout)
            self.session_lock = Lock()
        else:
            self.client = None

    def parse_url(self, request_url):
        """解析URL"""
        stidx = request_url.index("://")
        host = request_url[stidx + 3:]
        schema = request_url[:stidx + 3]
        edidx = host.index("/")
        if edidx <= 0:
            raise Exception("invalid request url:" + request_url)
        path = host[edidx:]
        host = host[:edidx]
        return {"host": host, "path": path, "schema": schema}

    def assemble_auth_url(self, request_url, method="POST"):
        """构建带认证的请求URL"""
        url_parts = self.parse_url(request_url)
        host = url_parts["host"]
        path = url_parts["path"]

        # 生成时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 生成签名
        signature_origin = f"host: {host}\ndate: {date}\n{method} {path} HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode('utf-8')

        # 构建authorization
        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

        # 构建完整URL
        values = {
            "host": host,
            "date": date,
            "authorization": authorization
        }

        return request_url + "?" + urlencode(values)

    def _prepare_request_body(self, text, from_lang, to_lang, use_terminology):
        """准备请求正文"""
        # 检查文本长度
        if len(text) > 5000:
            raise ValueError("文本超过5000字符限制")

        # 构建请求体
        body = {
            "header": {
                "app_id": self.app_id,
                "status": 3
            },
            "parameter": {
                "its": {
                    "from": from_lang,
                    "to": to_lang,
                    "result": {}
                }
            },
            "payload": {
                "input_data": {
                    "encoding": "utf8",
                    "status": 3,
                    "text": base64.b64encode(text.encode("utf-8")).decode('utf-8')
                }
            }
        }

        # 添加术语资源
        if use_terminology and (from_lang == "cn" and to_lang == "en" or from_lang == "en" and to_lang == "cn"):
            body["header"]["res_id"] = self.res_id

        return body

    def _prepare_headers(self):
        """准备请求头"""
        return {
            'content-type': "application/json",
            'host': 'itrans.xf-yun.com',
            'app_id': self.app_id
        }

    def _parse_response(self, response):
        """解析API响应"""
        try:
            if hasattr(response, 'content'):
                # requests响应
                result = json.loads(response.content.decode())
            else:
                # httpx响应
                result = response.json()

            # 解析返回结果
            if 'payload' in result and 'result' in result['payload'] and 'text' in result['payload']['result']:
                translated_text_base64 = result['payload']['result']['text']
                translated_text = base64.b64decode(translated_text_base64).decode()

                # 解析JSON格式的响应，只提取翻译文本
                try:
                    json_result = json.loads(translated_text)
                    # 提取翻译结果
                    if 'trans_result' in json_result and 'dst' in json_result['trans_result']:
                        return json_result['trans_result']['dst']
                    elif 'dst' in json_result:
                        return json_result['dst']
                    else:
                        # 如果找不到预期的字段，返回完整JSON
                        return translated_text
                except:
                    # 如果不是JSON格式，返回原始文本
                    return translated_text
            else:
                print(f"翻译API错误: {result}")
                return None
        except Exception as e:
            print(f"解析响应出错: {str(e)}")
            return None

    def _rate_limit(self):
        """简单的请求速率限制"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time

        # 如果距离上次请求时间太短，则等待
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)

        # 更新最后请求时间
        self.last_request_time = time.time()

    def _do_translate(self, text, from_lang, to_lang, use_terminology):
        """实际执行翻译的方法（不含缓存）"""
        try:
            # 应用速率限制
            self._rate_limit()

            # 准备请求数据
            body = self._prepare_request_body(text, from_lang, to_lang, use_terminology)
            request_url = self.assemble_auth_url(self.url, "POST")
            headers = self._prepare_headers()

            # 发送请求（使用更高效的HTTP客户端）
            if use_httpx:
                with self.session_lock:
                    response = self.client.post(
                        request_url,
                        json=body,  # httpx会自动处理JSON序列化
                        headers=headers
                    )
            else:
                # 使用标准requests
                json_data = json.dumps(body)
                response = requests.post(
                    request_url,
                    data=json_data,
                    headers=headers,
                    timeout=self.timeout
                )

            # 解析响应
            return self._parse_response(response)

        except Exception as e:
            print(f"翻译过程出错: {str(e)}")
            return None

    def translate(self, text, from_lang="cn", to_lang="en", use_terminology=True, use_cache=True):
        """
        执行文本翻译

        参数:
            text: 待翻译文本
            from_lang: 源语言（cn：中文，en：英文等）
            to_lang: 目标语言（cn：中文，en：英文等）
            use_terminology: 是否使用术语资源
            use_cache: 是否使用缓存

        返回:
            翻译结果字符串，如果出错返回None
        """
        # 空文本直接返回
        if not text or not text.strip():
            return ""

        # 源语言与目标语言相同，直接返回原文
        if from_lang == to_lang:
            return text

        # 检查语言支持
        if from_lang not in [code for code in LANGUAGE_CODES.values()]:
            raise ValueError(f"不支持的源语言代码: {from_lang}")
        if to_lang not in [code for code in LANGUAGE_CODES.values()]:
            raise ValueError(f"不支持的目标语言代码: {to_lang}")

        # 生成缓存键
        if use_cache:
            cache_key = f"{text}_{from_lang}_{to_lang}_{use_terminology}"

            # 检查缓存
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                return cached_result

        # 执行翻译
        result = self._do_translate(text, from_lang, to_lang, use_terminology)

        # 更新缓存
        if use_cache and result:
            self.cache.put(cache_key, result)

        return result

    def batch_translate(self, texts, from_lang="cn", to_lang="en", use_terminology=True):
        """
        批量翻译文本

        参数:
            texts: 文本列表
            from_lang: 源语言
            to_lang: 目标语言
            use_terminology: 是否使用术语资源

        返回:
            翻译结果列表
        """
        results = []

        # 批量处理每个文本
        for text in texts:
            result = self.translate(text, from_lang, to_lang, use_terminology)
            results.append(result)

        return results

    def clear_cache(self):
        """清空翻译缓存"""
        self.cache.clear()

    def get_cache_stats(self):
        """获取缓存统计信息"""
        return {
            "capacity": self.cache_size,
            "current_size": len(self.cache)
        }

    def __del__(self):
        """清理资源"""
        try:
            # 如果使用httpx，关闭客户端
            if use_httpx and hasattr(self, 'client') and self.client:
                self.client.close()
        except:
            pass


def detect_language(text):
    """
    简单的语言检测函数，根据文本特征推测语言

    参数:
        text: 要检测的文本

    返回:
        检测到的语言代码
    """
    # 计算不同字符集的字符出现频率
    char_counts = {
        'cn': 0,  # 中文
        'en': 0,  # 英文
        'ja': 0,  # 日文（假设日文包含汉字）
        'es': 0,  # 西班牙文
        'other': 0  # 其他语言
    }

    # 简单的语言检测逻辑
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            # 汉字范围 (中文/日文)
            char_counts['cn'] += 1
        elif ('a' <= char.lower() <= 'z') or char in "''":
            # 英文字母
            char_counts['en'] += 1
        elif '\u3040' <= char <= '\u30ff':
            # 日文平假名和片假名
            char_counts['ja'] += 1
        elif char in 'áéíóúüñ¿¡':
            # 西班牙文特殊字符
            char_counts['es'] += 1
        elif char.isalpha():
            # 其他字母
            char_counts['other'] += 1

    # 确定主要语言
    if char_counts['ja'] > 0:
        return 'ja'  # 有日文假名，判断为日文
    elif char_counts['cn'] > char_counts['en'] and char_counts['cn'] > char_counts['other']:
        return 'cn'  # 中文字符占多数
    elif char_counts['es'] > 0 and char_counts['en'] > 0:
        return 'es'  # 有西班牙文特殊字符
    elif char_counts['en'] > 0:
        return 'en'  # 英文字符占多数

    # 默认返回英文
    return 'en'


def clear_screen():
    """清除终端屏幕"""
    os.system('cls' if os.name == 'nt' else 'clear')


def interactive_translation():
    """交互式翻译程序"""
    # 你的API密钥
    APP_ID = "86c79fb7"
    API_SECRET = "MDY3ZGFkYWEyZDBiOTJkOGIyOTllOWMz"
    API_KEY = "f4369644e37eddd43adfe436e7904cf1"

    # 创建翻译模块实例
    translator = TranslationModule(APP_ID, API_SECRET, API_KEY)

    while True:
        clear_screen()
        print("\n===== 多语言翻译工具 =====")
        print("支持的语言: " + ", ".join(LANGUAGE_CODES.keys()))
        print("------------------------")

        # 1. 手动输入文本
        print("请输入要翻译的文本 (输入'exit'退出):")
        text = input("> ")

        if text.lower() == 'exit':
            break

        if not text.strip():
            print("文本不能为空！按任意键继续...")
            input()
            continue

        # 自动检测输入语言
        detected_lang = detect_language(text)
        from_lang_name = LANGUAGE_NAMES.get(detected_lang, "未知")
        print(f"\n检测到输入语言: {from_lang_name} ({detected_lang})")

        # 2. 选择目标语言
        print("\n选择目标语言:")
        for i, (name, code) in enumerate(LANGUAGE_CODES.items(), 1):
            if code != detected_lang:  # 不显示检测到的源语言
                print(f"{i}. {name} ({code})")

        target_choice = input("\n请输入目标语言的序号: ")
        try:
            target_idx = int(target_choice) - 1
            if target_idx < 0 or target_idx >= len(LANGUAGE_CODES):
                raise ValueError()

            to_lang_name = list(LANGUAGE_CODES.keys())[target_idx]
            to_lang = LANGUAGE_CODES[to_lang_name]

            # 如果选择了与源语言相同的语言，提示重新选择
            if to_lang == detected_lang:
                print(f"目标语言与源语言相同，请重新选择！按任意键继续...")
                input()
                continue

        except (ValueError, IndexError):
            print("无效的选择！按任意键继续...")
            input()
            continue

        # 3. 执行翻译
        print(f"\n正在将 {from_lang_name} 翻译为 {to_lang_name}...")
        start_time = time.time()
        result = translator.translate(text, detected_lang, to_lang)
        elapsed = time.time() - start_time

        # 显示翻译结果
        if result:
            print("\n=== 翻译结果 ===")
            print(f"原文 ({from_lang_name}): {text}")
            print(f"译文 ({to_lang_name}): {result}")
            print(f"翻译用时: {elapsed:.2f} 秒")
        else:
            print("\n翻译失败，请检查网络连接或API密钥。")

        # 展示缓存状态
        cache_stats = translator.get_cache_stats()
        print(f"\n缓存状态: 已使用 {cache_stats['current_size']}/{cache_stats['capacity']}")

        print("\n按Enter键继续，输入'exit'退出...")
        if input().lower() == 'exit':
            break


# 主程序入口
if __name__ == "__main__":
    try:
        interactive_translation()
    except KeyboardInterrupt:
        print("\n程序已退出。")
    except Exception as e:
        print(f"\n程序发生错误: {str(e)}")
        sys.exit(1)