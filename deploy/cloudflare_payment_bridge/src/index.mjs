import { createHash } from "node:crypto";

const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, OPTIONS",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: jsonHeaders });
}

function providerSign(params, codepayKey) {
  const filtered = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && String(value) !== "")
    .sort(([a], [b]) => a.localeCompare(b));
  const query = filtered.map(([key, value]) => `${key}=${value}`).join("&");
  return createHash("md5").update(`${query}&key=${codepayKey}`, "utf8").digest("hex");
}

async function requestJson(url, options = {}) {
  const resp = await fetch(url, options);
  const text = await resp.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!resp.ok) {
    throw new Error(data.detail || data.raw || `HTTP ${resp.status}`);
  }
  return data;
}

function buildOutTradeNo(requestId) {
  return `rr_${requestId}_${Date.now()}`;
}

function parseRequestId(outTradeNo) {
  const match = /^rr_(\d+)_/.exec(String(outTradeNo || ""));
  return match ? Number(match[1]) : 0;
}

async function createRechargeOrder(request, env) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return json({ detail: "missing bearer token" }, 401);
  }

  const body = await request.json();
  const amountYuan = Number(body.amount_yuan || 0);
  const payType = Number(body.pay_type || 2);
  if (!Number.isFinite(amountYuan) || amountYuan <= 0) {
    return json({ detail: "invalid amount_yuan" }, 400);
  }

  const rechargeRequest = await requestJson(`${env.PYTHONANYWHERE_BASE_URL}/api/me/recharge-requests`, {
    method: "POST",
    headers: {
      authorization: auth,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      amount_yuan: amountYuan,
      note: body.note || "serverless bridge recharge",
    }),
  });

  const outTradeNo = buildOutTradeNo(rechargeRequest.id);
  const notifyUrl = new URL("/api/payment/notify", request.url).toString();
  const params = {
    id: env.CODEPAY_ID,
    type: String(payType),
    out_trade_no: outTradeNo,
    money: amountYuan.toFixed(2),
    name: "Recharge Topup",
    notify_url: notifyUrl,
    return_url: env.RETURN_URL || body.return_url || env.PYTHONANYWHERE_BASE_URL,
  };
  params.sign = providerSign(params, env.CODEPAY_KEY);

  const providerResp = await fetch(`${env.CODEPAY_API_BASE.replace(/\/$/, "")}/pay/index.php`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params).toString(),
  });
  const providerText = await providerResp.text();
  let providerJson = {};
  try {
    providerJson = providerText ? JSON.parse(providerText) : {};
  } catch {
    providerJson = { raw: providerText };
  }
  if (!providerResp.ok) {
    return json({ detail: providerJson.msg || providerJson.raw || "provider request failed" }, 502);
  }
  if (String(providerJson.code || "") !== "1") {
    return json({ detail: providerJson.msg || "provider create order failed", provider: providerJson }, 502);
  }

  return json({
    ok: true,
    recharge_request_id: rechargeRequest.id,
    out_trade_no: outTradeNo,
    pay_url: providerJson.pay_url || "",
    qrcode: providerJson.qrcode || "",
    provider: providerJson,
  });
}

async function paymentNotify(request, env) {
  const raw = await request.text();
  const params = Object.fromEntries(new URLSearchParams(raw));
  const { sign = "", ...unsigned } = params;
  const expected = providerSign(unsigned, env.CODEPAY_KEY);
  if (String(sign).toLowerCase() !== expected.toLowerCase()) {
    return json({ code: 0, msg: "sign error" }, 400);
  }

  if (params.trade_status !== "TRADE_SUCCESS") {
    return json({ code: 1, msg: "ok" });
  }

  const requestId = parseRequestId(params.out_trade_no);
  if (!requestId) {
    return json({ code: 0, msg: "invalid out_trade_no" }, 400);
  }

  try {
    await requestJson(
      `${env.PYTHONANYWHERE_BASE_URL}/api/admin/recharge-requests/${requestId}/approve?token=${encodeURIComponent(env.PYTHONANYWHERE_ADMIN_TOKEN)}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          review_note: `auto approved by serverless bridge, trade_no=${params.trade_no || ""}`,
        }),
      }
    );
  } catch (err) {
    const message = String(err.message || "");
    if (!message.includes("already reviewed")) {
      return json({ code: 0, msg: message }, 500);
    }
  }

  return json({ code: 1, msg: "ok" });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: jsonHeaders });
    }

    if (!env.CODEPAY_ID || !env.CODEPAY_KEY || !env.CODEPAY_API_BASE || !env.PYTHONANYWHERE_BASE_URL || !env.PYTHONANYWHERE_ADMIN_TOKEN) {
      return json({ detail: "missing required environment variables" }, 500);
    }

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/health") {
      return json({ ok: true, provider: env.PAYMENT_PROVIDER || "codepay_legacy" });
    }
    if (request.method === "POST" && url.pathname === "/api/recharge/create") {
      return createRechargeOrder(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/payment/notify") {
      return paymentNotify(request, env);
    }
    return json({ detail: "not found" }, 404);
  },
};
