# Cloudflare Workers 支付中转原型

这个原型的目标不是替代整个网站，而是把“第三方支付下单 / 签名 / 回调验签”这部分从 PythonAnywhere 免费版剥离出去。

## 解决什么问题

PythonAnywhere 免费账户对服务器端主动访问外部网站/API 有 allowlist 限制。  
如果第三方支付要求你在服务端先创建支付订单，再返回二维码或支付链接，就很容易卡住。

这个 Worker 原型负责：

1. 接收前端发来的充值金额
2. 先在 PythonAnywhere 创建一条 `recharge_request`
3. 再代表你去调用第三方支付接口
4. 收到支付回调后，自动调用 PythonAnywhere 后台接口审核通过该充值申请
5. 用户余额自动增加

## 当前实现

- 运行时：Cloudflare Workers
- 文件入口：`src/index.mjs`
- 配置：`wrangler.toml`
- 本地开发变量示例：`.dev.vars.example`

当前原型实现了 3 个接口：

- `GET /api/health`
- `POST /api/recharge/create`
- `POST /api/payment/notify`

## 环境变量

需要在 Cloudflare 中配置：

- `CODEPAY_ID`
- `CODEPAY_KEY`
- `CODEPAY_API_BASE`
- `PYTHONANYWHERE_BASE_URL`
- `PYTHONANYWHERE_ADMIN_TOKEN`
- `RETURN_URL`

## 本地开发

1. 安装 Wrangler
2. 复制 `.dev.vars.example` 为 `.dev.vars`
3. 填入真实参数
4. 启动：

```bash
npx wrangler dev
```

## 部署

```bash
npx wrangler deploy
```

部署后你会得到一个 Worker URL，例如：

```text
https://zhongwang-payment-bridge.<your-subdomain>.workers.dev
```

然后把这个 URL 写入 PythonAnywhere 的：

```json
{
  "payment_bridge_url": "https://zhongwang-payment-bridge.<your-subdomain>.workers.dev"
}
```

文件位置是：

```text
config/pythonanywhere_secrets.json
```

## 前端如何接

用户登录你的网站后：

1. 前端向 Worker 的 `POST /api/recharge/create` 发请求
2. 请求头带上 PythonAnywhere 用户登录后的 `Authorization: Bearer <session_token>`
3. Worker 会先到 PythonAnywhere 创建充值申请
4. 再去调第三方支付接口
5. 把支付二维码或支付链接返回前端

支付成功后：

1. 第三方支付平台回调 Worker `POST /api/payment/notify`
2. Worker 校验签名
3. Worker 调用 PythonAnywhere：
   `POST /api/admin/recharge-requests/{id}/approve`
4. 用户余额自动到账

## 当前限制

- 这是“充值自动入账”原型，不是“付款后直接创建充电订单”的完整闭环
- 默认按当前仓库里的旧版 `codepay/upaypro` 请求格式做桥接
- 如果支付平台字段或签名规则与你实际账号不一致，需要按官方文档再调整
- 真实生产还建议增加：
  - 回调幂等日志
  - 更严格的请求来源校验
  - 金额白名单
  - 用户限流
