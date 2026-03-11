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
  "agent_token": "your-agent-token",
  "worker_enabled": "0",
  "require_agent_online_for_orders": "1",
  "agent_heartbeat_expire_seconds": "45",
  "payment_mode": "token",
  "payment_token_secret": "your-secret",
  "payment_token_ttl_seconds": "900",
  "balance_refund_on_fail": "1"
}
```

`services/pythonanywhere_app.py` 会自动读取它。

## 8）验证部署结果

打开：

- `https://<your-username>.pythonanywhere.com/`
- `https://<your-username>.pythonanywhere.com/api/health`

预期结果：

- `worker_enabled` 为 `false`
- `service_mode` 为 `cloud_agent`
- 如果本地 Agent 尚未启动，`agent_online` 会是 `false`

## 8.1）个人收款的支付校验（支付码模式）

个人微信收款没有官方的支付回调接口可用，因此本项目采用“支付码”方案：

1. 用户在手机上扫你的微信收款码完成转账。
2. 你在后台确认收到款后，通过后台页面或接口发放一次性 `payment token`。
3. 用户把 token 粘贴到下单页，再提交订单。

可选：把你的收款码图片放到 `assets/web/wechat_qr.png`，同步到 PythonAnywhere 后，下单页会自动显示二维码（`/assets/wechat_qr.png`）。

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
- `services/pythonanywhere_app.py`
- `services/project_paths.py`
- `services/__init__.py`
- `assets/web/mobile_order.html`
- `assets/web/admin_orders.html`
- `config/stations.json`
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



