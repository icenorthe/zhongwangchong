# PythonAnywhere 部署说明

这份说明用于把下单网站部署到 PythonAnywhere 的固定域名上，例如：

- `https://<你的用户名>.pythonanywhere.com`

注意：PythonAnywhere 这边只负责接单和展示订单，不负责运行本地微信执行器。

## 1）创建账号

1. 注册一个 PythonAnywhere 免费账号。
2. 用户名要认真选，因为免费域名会直接使用它。

## 2）上传项目

你可以任选一种方式：

- 在 Files 页面上传压缩包后解压。
- 或者在 Bash 控制台里用 Git 拉代码。

建议项目目录：

```bash
/home/<your-username>/zhongwang-charge
```

## 3）创建虚拟环境并安装依赖

在 PythonAnywhere 的 Bash 控制台执行：

```bash
cd /home/<your-username>/zhongwang-charge
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements_mobile.txt
```

## 4）创建 Web App

在 PythonAnywhere 的 Web 页面：

1. 点击 `Add a new web app`
2. 选择免费域名 `<your-username>.pythonanywhere.com`
3. 选择 `Manual configuration`
4. 选择 Python `3.12`
5. 把应用类型切换为 `ASGI`

## 5）修改 ASGI 配置

把 Web 页面里自动生成的 ASGI 配置替换为：

```python
import os
import sys

project_home = "/home/<your-username>/zhongwang-charge"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.chdir(project_home)

from services.pythonanywhere_app import app
```

## 6）设置虚拟环境并重载

在 Web 页面中：

1. 把 virtualenv 路径设为：
   `/home/<your-username>/zhongwang-charge/.venv`
2. 点击 `Reload`

## 7）放置密钥配置

在项目目录下的 `config/pythonanywhere_secrets.json` 中填写：

```json
{
  "admin_token": "your-admin-token",
  "admin_password": "your-admin-password",
  "agent_token": "your-agent-token",
  "worker_enabled": "0",
  "require_agent_online_for_orders": "1",
  "agent_heartbeat_expire_seconds": "45",
  "socket_overview_bridge_url": "",
  "payment_mode": "balance",
  "payment_bridge_url": "https://zhongwang-payment-bridge.<your-subdomain>.workers.dev",
  "manual_payment_contact": "微信：your-wechat / 手机：13800000000",
  "manual_payment_instructions": "扫码付款后点击“我已付款”，备注尾号或转账说明，我确认到账后会补余额。",
  "balance_refund_on_fail": "1"
}
```

`services/pythonanywhere_app.py` 会自动读取它。

说明：

- `admin_token` 用于后台接口鉴权
- `admin_password` 是后台页面的第二道密码，不填则不启用

## 8）验证部署结果

打开：

- `https://<your-username>.pythonanywhere.com/`
- `https://<your-username>.pythonanywhere.com/api/health`

预期结果：

- `worker_enabled` 为 `false`
- `service_mode` 为 `cloud_agent`
- `payment_mode` 为 `balance`
- `payment_bridge_url` 指向你的 Cloudflare Worker
- 如果本地 Agent 尚未启动，`agent_online` 会是 `false`

## 8.1）XPay 在线收款与回调

推荐结构：

1. 网站前端调用 Cloudflare Worker 创建充值支付单。
2. Worker 再去请求 XPay/EPay 接口，返回微信或支付宝支付链接。
3. XPay 支付成功后回调 Worker 的 `/api/payment/notify`。
4. Worker 自动调用 PythonAnywhere 后台接口审核通过充值申请。
5. 用户余额自动到账，页面也会轮询查单兜底。

当前项目更适合这样配：

1. PythonAnywhere 只负责网站、登录、订单和余额。
2. Cloudflare Worker 负责 XPay 下单、签名、回调。
3. `payment_mode` 使用 `balance`，不要再用旧的 `token` 模式做在线收款。

如果你暂时没有 XPay 商户，也可以把微信收款码放到 `assets/web/wechat_qr.png`，同步到 PythonAnywhere 后先用线下确认到账的方式过渡。

现在页面已经支持轻量 MVP：

1. 首页保留“立即购买”按钮。
2. 点击后弹出收款二维码、付款说明和联系方式。
3. 用户付款后提交“我已付款”申请。
4. 你在后台审核通过后，余额会补到用户账户里。

## 9）为本地执行做准备

服务端已经暴露好了这两个 Agent 接口：

- `POST /api/agent/heartbeat`
- `POST /api/agent/orders/claim`
- `POST /api/agent/orders/{order_id}/complete`

后面本地 Windows 电脑只要运行：

- `services/cloud_agent.py`

就可以轮询 PythonAnywhere、上报在线状态，并执行本地微信自动化。

当网站首页显示“电脑接单服务在线”后，别人下单才会进入真正可执行的状态。

## 10）后续一键同步

现在不需要每次都手动打包上传。

同步脚本会上传这些本地文件：

- `services/mobile_charge_server.py`
- `services/socket_snapshot.py`
- `services/pythonanywhere_app.py`
- `services/project_paths.py`
- `services/__init__.py`
- `assets/web/mobile_order.html`
- `assets/web/admin_orders.html`
- `config/stations.json`
- `config/station_placeholders.json`
- `config/charge_api_config.json`
- `config/pythonanywhere_secrets.json`
- `config/gateway_config.json`
- `requirements_mobile.txt`
- `docs/PythonAnywhere部署说明.md`

启用方法：

1. 复制 `config/pythonanywhere_sync_config.example.json`
2. 命名为 `config/pythonanywhere_sync_config.json`
3. 填写 PythonAnywhere API Token
4. 运行：

```bat
一键同步云端.bat
```

同步脚本会自动上传这些文件，并尝试重载 Web App。

补充：

- 如果 `requirements_mobile.txt` 变了，仍然要在 PythonAnywhere Bash 里手动执行一次 `pip install -r requirements_mobile.txt`



