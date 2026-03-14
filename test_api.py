import urllib.request
import urllib.parse
import json

url = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_balancePay.action"

# 1元 = moneys/payMoney = 100
data = urllib.parse.urlencode({
    "isSafeServer": "0",
    "safeServerMoney": "0",
    "sn": "13061856473",  # 设备编号
    "sid": "1",           # 插座号
    "moneys": "100",      # 1元=100分
    "payMoney": "100",
    "memberId": "1708546",
    "miniAppType": "1",
}).encode("utf-8")

headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 MicroMessenger/7.0.20.1781",
    "Authorization": "",
}

req = urllib.request.Request(url, data=data, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        print("状态码:", resp.status)
        print("响应:", json.dumps(json.loads(body), ensure_ascii=False, indent=2))
except Exception as e:
    print("错误:", e)
