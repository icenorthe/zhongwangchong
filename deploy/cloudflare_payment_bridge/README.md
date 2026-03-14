# Cloudflare Workers XPay 中转

这个 Worker 用来把 `XPay/EPay` 风格的支付下单、签名、回调验签放到 Cloudflare 上执行，避免 PythonAnywhere 免费版因为外部请求限制而卡在“创建支付订单”这一步。

## 它负责什么

1. 接收前端发来的充值金额与支付方式
2. 先在 PythonAnywhere 创建一条 `recharge_request`
3. 调用 XPay/EPay 下单接口拿到支付链接或二维码
4. 收到异步回调后，自动调用 PythonAnywhere 后台接口审核通过充值申请
5. 前端轮询 `GET /api/recharge/status` 时，也会补一次“主动查单自动入账”

## 当前接口

- `GET /api/health`
- `GET /api/socket-overview`
- `POST /api/recharge/create`
- `GET /api/recharge/status`
- `POST /api/payment/notify`

`GET /api/health` 会返回当前 Worker 的 `provider`、`pay_types`，以及 `payment_configured` / `realtime_configured`（是否已完成支付桥 / 实时站点代理配置）。

## 环境变量

必填（支付桥）：

- `CODEPAY_ID` 或 `XPAY_PID`
- `CODEPAY_KEY` 或 `XPAY_KEY`
- `CODEPAY_API_BASE` 或 `XPAY_API_BASE`
- `PYTHONANYWHERE_BASE_URL`
- `PYTHONANYWHERE_ADMIN_TOKEN`
- `RETURN_URL`

必填（站点状态实时代理）：

- `PYTHONANYWHERE_BASE_URL`
- `PYTHONANYWHERE_ADMIN_TOKEN`

推荐：

- `PAYMENT_PAY_TYPES`
  逗号分隔，例如 `wxpay` 或 `wxpay,alipay`
- `CODEPAY_CHANNEL_ID`
  默认通道号
- `CODEPAY_CHANNEL_ID_WXPAY`
  微信专用通道号
- `CODEPAY_CHANNEL_ID_ALIPAY`
  支付宝专用通道号

可选兼容项：

- `PROVIDER_CREATE_PATH`
  默认 `/xpay/epay/mapi.php`
- `PROVIDER_QUERY_PATH`
  默认 `/xpay/epay/api.php`
- `PROVIDER_SIGN_MODE`
  `concat` 或 `amp_key`，默认 `concat`

## 本地开发

1. 复制 `.dev.vars.example` 为 `.dev.vars`
2. 填入真实参数
3. 运行：

```bash
npx wrangler dev
```

## 部署

```bash
npx wrangler deploy
```

部署完成后，把 Worker URL 写入：

```json
{
  "payment_mode": "balance",
  "payment_bridge_url": "https://zhongwang-payment-bridge.<your-subdomain>.workers.dev"
}
```

文件位置：

```text
config/pythonanywhere_secrets.json
```

如果要启用【站点状态】实时代理，请同时配置：

```json
{
  "socket_overview_bridge_url": "https://zhongwang-payment-bridge.<your-subdomain>.workers.dev"
}
```

## 前端接入方式

1. 网站前端调用 Worker 的 `POST /api/recharge/create`
2. 请求头带上 PythonAnywhere 登录态：`Authorization: Bearer <session_token>`
3. Worker 先在 PythonAnywhere 创建充值申请
4. 再向 XPay 下单，返回支付链接或二维码
5. 用户支付后，XPay 回调 Worker 的 `POST /api/payment/notify`
6. Worker 自动调用：
   `POST /api/admin/recharge-requests/{id}/approve`
7. 用户余额自动到账

站点状态：

1. 网站前端调用 Worker 的 `GET /api/socket-overview`
2. 请求头带上 PythonAnywhere 登录态：`Authorization: Bearer <session_token>`
3. Worker 会先去 PythonAnywhere 拉取站点配置，再访问官方实时接口，最后返回精简后的站点状态

## 现网建议

- 如果商户当前只开通了微信，请把 `PAYMENT_PAY_TYPES=wxpay`
- 如果支付宝未开通，不要在前端显示支付宝入口
- 回调地址要填 Worker 的 `/api/payment/notify`，不要直接填 PythonAnywhere
- 正式环境建议再补一层回调幂等日志和来源校验
