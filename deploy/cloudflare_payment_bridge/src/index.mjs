import { createHash } from "node:crypto";

const jsonHeaders = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, OPTIONS",
};

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), { status, headers: { ...jsonHeaders, ...extraHeaders } });
}

function cleanEnvValue(value) {
  return String(value || "")
    .replace(/\u0000/g, "")
    .trim()
    .replace(/^['"]+/, "")
    .replace(/['"]+$/, "");
}

function providerPid(env) {
  return cleanEnvValue(env.XPAY_PID || env.CODEPAY_ID || env.CODEPAY_PID);
}

function providerKey(env) {
  return cleanEnvValue(env.XPAY_KEY || env.CODEPAY_KEY);
}

function providerBase(env) {
  return cleanEnvValue(env.XPAY_API_BASE || env.CODEPAY_API_BASE).replace(/\/$/, "");
}

function normalizePath(path, fallback) {
  const text = cleanEnvValue(path);
  if (!text) {
    return fallback;
  }
  return text.startsWith("/") ? text : `/${text}`;
}

function providerCreatePath(env) {
  return normalizePath(env.XPAY_CREATE_PATH || env.PROVIDER_CREATE_PATH, "/xpay/epay/mapi.php");
}

function providerQueryPath(env) {
  return normalizePath(env.XPAY_QUERY_PATH || env.PROVIDER_QUERY_PATH, "/xpay/epay/api.php");
}

function providerQueryMethod(env) {
  const method = cleanEnvValue(env.XPAY_QUERY_METHOD || env.PROVIDER_QUERY_METHOD || "get").toLowerCase();
  return method === "post" ? "post" : "get";
}

function providerQueryStyle(env) {
  return cleanEnvValue(env.XPAY_QUERY_STYLE || env.PROVIDER_QUERY_STYLE || "").toLowerCase();
}

function providerSignMode(env) {
  const mode = cleanEnvValue(env.XPAY_SIGN_MODE || env.PROVIDER_SIGN_MODE || "concat").toLowerCase();
  return mode === "amp_key" ? "amp_key" : "concat";
}

function providerSign(params, key, signMode = "concat") {
  const filtered = Object.entries(params)
    .filter(([key, value]) => !["sign", "sign_type"].includes(key) && value !== undefined && value !== null && String(value) !== "")
    .sort(([a], [b]) => a.localeCompare(b));
  const query = filtered.map(([key, value]) => `${key}=${value}`).join("&");
  const raw = signMode === "amp_key" ? `${query}&key=${key}` : `${query}${key}`;
  return createHash("md5").update(raw, "utf8").digest("hex");
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

const REALTIME_PARSECK_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_parseCk.action";
const REALTIME_USING_ORDERS_URL = "https://wx.jwnzn.com/mini_jwnzn/miniapp/mp_pileUsingOrders.action";
const REALTIME_HEADERS = {
  "content-type": "application/x-www-form-urlencoded; charset=utf-8",
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 " +
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI " +
    "MiniProgramEnv/Windows WindowsWechat/WMPF",
};

function optionalText(value) {
  return String(value || "").trim();
}

function optionalInt(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.trunc(n);
}

async function readJsonWithEncodingFallback(resp) {
  const buffer = await resp.arrayBuffer();
  const tryDecode = (encoding) => {
    try {
      return new TextDecoder(encoding).decode(buffer);
    } catch {
      return null;
    }
  };

  const first = tryDecode("utf-8") || "";
  try {
    return { ok: true, data: first ? JSON.parse(first) : {} };
  } catch {
    const alt = tryDecode("gb18030");
    if (alt) {
      try {
        return { ok: true, data: alt ? JSON.parse(alt) : {} };
      } catch {
        return { ok: false, data: { raw: alt } };
      }
    }
    return { ok: false, data: { raw: first } };
  }
}

async function postFormJson(url, payload, timeoutMs = 10000) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(payload || {})) {
    if (value === null || value === undefined || String(value) === "") continue;
    params.set(key, String(value));
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: REALTIME_HEADERS,
      body: params.toString(),
      signal: controller.signal,
    });
    const parsed = await readJsonWithEncodingFallback(resp);
    if (!resp.ok) {
      const detail = optionalText(parsed.data?.detail) || optionalText(parsed.data?.msg) || optionalText(parsed.data?.raw);
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    if (!parsed.ok) {
      throw new Error("invalid upstream json");
    }
    return parsed.data || {};
  } finally {
    clearTimeout(timer);
  }
}

async function mapWithConcurrency(list, limit, mapper) {
  const items = Array.isArray(list) ? list : [];
  const results = new Array(items.length);
  let cursor = 0;

  async function worker() {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const index = cursor++;
      if (index >= items.length) return;
      results[index] = await mapper(items[index], index);
    }
  }

  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, () => worker());
  await Promise.all(workers);
  return results;
}

function usingOrderKey(deviceCode, socketNo) {
  return `${deviceCode}#${socketNo}`;
}

function pickEndTime(item) {
  return (
    optionalText(item?.endTime) ||
    optionalText(item?.finishTime) ||
    optionalText(item?.stopTime) ||
    optionalText(item?.end_time) ||
    optionalText(item?.finish_time) ||
    optionalText(item?.stop_time)
  );
}

function pickRemainSeconds(item) {
  return (
    optionalInt(item?.remainSeconds) ??
    optionalInt(item?.leftSeconds) ??
    optionalInt(item?.remainingSeconds) ??
    optionalInt(item?.surplusSeconds) ??
    optionalInt(item?.remain_seconds) ??
    optionalInt(item?.left_seconds) ??
    optionalInt(item?.remaining_seconds)
  );
}

async function fetchUsingOrders(memberId) {
  const payload = await postFormJson(REALTIME_USING_ORDERS_URL, { memberId, miniAppType: "1" });
  const map = new Map();
  const rows = payload?.usingOrders;
  if (Array.isArray(rows)) {
    for (const item of rows) {
      if (!item || typeof item !== "object") continue;
      const deviceCode = optionalText(item.sn);
      const socketNo = optionalInt(item.sid);
      if (!deviceCode || !socketNo || socketNo <= 0) continue;
      const startTime = optionalText(item.startTime);
      const endTime = pickEndTime(item);
      const remainSeconds = pickRemainSeconds(item);
      const detail = startTime ? `开始时间：${startTime}` : "";
      map.set(usingOrderKey(deviceCode, socketNo), {
        status: "使用中",
        detail,
        station_name: optionalText(item.devName),
        start_time: startTime,
        end_time: endTime,
        remain_seconds: remainSeconds,
      });
    }
  }
  return map;
}

async function fetchStationRealtime(station, memberId) {
  const deviceCk = optionalText(station?.device_ck || station?.deviceCk);
  if (!memberId) return { ok: false, message: "配置缺少 member_id", products: [] };
  if (!deviceCk) return { ok: false, message: "缺少 device_ck", products: [] };
  const payload = await postFormJson(REALTIME_PARSECK_URL, { ck: deviceCk, memberId, miniAppType: "1" });
  const products = Array.isArray(payload?.products) ? payload.products : [];
  const ok = Number(payload?.normal || 0) === 1 && products.length > 0;
  let message = optionalText(payload?.msg);
  if (ok) return { ok: true, message, products };
  if (!message) message = "实时接口未返回插座状态";
  return { ok: false, message, products };
}

function disabledSocket(socketNo) {
  return { socket_no: socketNo, status: "故障", detail: "已标记故障" };
}

function unknownSocket(socketNo, detail) {
  return { socket_no: socketNo, status: "未查询到", detail: optionalText(detail) };
}

function socketFromProduct(socketNo, product, usingOrders, deviceCode) {
  const state = optionalInt(product?.state);
  if (state === 0) return { socket_no: socketNo, status: "空闲", detail: "" };
  if (state === 1) {
    const snapshot = usingOrders.get(usingOrderKey(deviceCode, socketNo)) || null;
    const data = { socket_no: socketNo, status: "使用中", detail: optionalText(snapshot?.detail) };
    if (snapshot && snapshot.start_time) data.start_time = snapshot.start_time;
    if (snapshot && snapshot.end_time) data.end_time = snapshot.end_time;
    if (snapshot && snapshot.remain_seconds !== null && snapshot.remain_seconds !== undefined) data.remain_seconds = snapshot.remain_seconds;
    return data;
  }
  return unknownSocket(socketNo, `未知状态: ${product?.state}`);
}

function buildStationSockets(station, stationResult, usingOrders) {
  const socketCount = Math.max(1, Math.min(20, optionalInt(station?.socket_count) || 10));
  const disabled = new Set(Array.isArray(station?.disabled_sockets) ? station.disabled_sockets.map((x) => Number(x)) : []);
  const deviceCode = optionalText(station?.device_code);
  const products = Array.isArray(stationResult?.products) ? stationResult.products : [];
  const ok = Boolean(stationResult?.ok);

  const productBySid = new Map();
  if (ok) {
    for (const product of products) {
      if (!product || typeof product !== "object") continue;
      const sid = optionalInt(product.sid);
      if (!sid || sid <= 0) continue;
      productBySid.set(sid, product);
    }
  }

  const fallbackDetail = optionalText(stationResult?.message);
  const sockets = [];
  for (let socketNo = 1; socketNo <= socketCount; socketNo += 1) {
    if (disabled.has(socketNo)) {
      sockets.push(disabledSocket(socketNo));
      continue;
    }

    const product = productBySid.get(socketNo);
    if (product && ok) {
      sockets.push(socketFromProduct(socketNo, product, usingOrders, deviceCode));
      continue;
    }

    const snapshot = deviceCode ? usingOrders.get(usingOrderKey(deviceCode, socketNo)) : null;
    if (snapshot) {
      const data = { socket_no: socketNo, status: "使用中", detail: optionalText(snapshot.detail) };
      if (snapshot.start_time) data.start_time = snapshot.start_time;
      if (snapshot.end_time) data.end_time = snapshot.end_time;
      if (snapshot.remain_seconds !== null && snapshot.remain_seconds !== undefined) data.remain_seconds = snapshot.remain_seconds;
      sockets.push(data);
      continue;
    }

    if (ok) sockets.push(unknownSocket(socketNo, "实时接口未返回该插座"));
    else sockets.push(unknownSocket(socketNo, ""));
  }

  return { sockets, queryMessage: fallbackDetail };
}

function paymentEnvReady(env) {
  return Boolean(providerPid(env) && providerKey(env) && providerBase(env) && env.PYTHONANYWHERE_BASE_URL && env.PYTHONANYWHERE_ADMIN_TOKEN);
}

function realtimeEnvReady(env) {
  return Boolean(env.PYTHONANYWHERE_BASE_URL && env.PYTHONANYWHERE_ADMIN_TOKEN);
}

async function socketOverview(request, env, ctx) {
  if (!realtimeEnvReady(env)) {
    return json({ detail: "missing PYTHONANYWHERE_BASE_URL / PYTHONANYWHERE_ADMIN_TOKEN" }, 500);
  }

  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return json({ detail: "missing bearer token" }, 401);
  }
  try {
    await requestJson(`${env.PYTHONANYWHERE_BASE_URL}/api/me`, { method: "GET", headers: { authorization: auth } });
  } catch {
    return json({ detail: "invalid bearer token" }, 401);
  }

  const cacheKeyUrl = new URL(request.url);
  cacheKeyUrl.search = "";
  const cacheKey = new Request(cacheKeyUrl.toString(), { method: "GET" });
  const cache = caches.default;
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const cfg = await requestJson(
    `${env.PYTHONANYWHERE_BASE_URL}/api/admin/realtime-snapshot-config?token=${encodeURIComponent(env.PYTHONANYWHERE_ADMIN_TOKEN)}`,
    { method: "GET" }
  );
  const memberId = optionalText(cfg?.member_id);
  const stations = Array.isArray(cfg?.stations) ? cfg.stations : [];

  let usingOrders = new Map();
  if (memberId) {
    try {
      usingOrders = await fetchUsingOrders(memberId);
    } catch {
      usingOrders = new Map();
    }
  }

  const realtimeCandidates = stations.filter((station) => optionalText(station?.device_ck));
  const realtimeResults = await mapWithConcurrency(
    realtimeCandidates,
    8,
    async (station) => {
      try {
        return await fetchStationRealtime(station, memberId);
      } catch (err) {
        return { ok: false, message: `实时接口异常: ${optionalText(err.message)}`, products: [] };
      }
    }
  );
  const realtimeByDevice = new Map();
  for (let i = 0; i < realtimeCandidates.length; i += 1) {
    const deviceCode = optionalText(realtimeCandidates[i]?.device_code);
    if (!deviceCode) continue;
    realtimeByDevice.set(deviceCode, realtimeResults[i]);
  }

  const regions = new Map();
  for (const station of stations) {
    const regionName = optionalText(station?.region) || "未分区";
    if (!regions.has(regionName)) regions.set(regionName, { region: regionName, stations: [] });

    const deviceCode = optionalText(station?.device_code);
    const hasUsingOrder = deviceCode ? Array.from(usingOrders.keys()).some((key) => key.startsWith(`${deviceCode}#`)) : false;

    let stationResult = realtimeByDevice.get(deviceCode) || null;
    if (!stationResult) {
      if (!memberId) stationResult = { ok: false, message: "配置缺少 member_id", products: [] };
      else if (!deviceCode) stationResult = { ok: false, message: "仅录入站号，缺少 device_code / device_ck", products: [] };
      else if (optionalText(station?.device_ck)) stationResult = { ok: false, message: "实时接口未返回结果", products: [] };
      else if (hasUsingOrder) stationResult = { ok: false, message: "缺少 device_ck；仅能识别当前账号充电中的插座", products: [] };
      else stationResult = { ok: false, message: "缺少 device_ck", products: [] };
    }

    const { sockets, queryMessage } = buildStationSockets(station, stationResult, usingOrders);
    regions.get(regionName).stations.push({
      id: station?.id,
      name: station?.name,
      device_code: station?.device_code,
      region: regionName,
      query_message: stationResult.ok ? "" : queryMessage,
      realtime_ok: Boolean(stationResult.ok),
      sockets,
    });
  }

  const snapshot = Array.from(regions.values());
  const response = json(snapshot, 200, { "cache-control": "public, max-age=15" });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

function buildOutTradeNo(requestId) {
  return `rr_${requestId}_${Date.now()}`;
}

function parseRequestId(outTradeNo) {
  const match = /^rr_(\d+)_/.exec(String(outTradeNo || ""));
  return match ? Number(match[1]) : 0;
}

function parsePayTypes(value) {
  const items = String(value || "")
    .split(",")
    .map((chunk) => chunk.trim().toLowerCase())
    .filter(Boolean);
  const set = new Set();
  for (const item of items) {
    if (item === "wxpay" || item === "wechat" || item === "weixin" || item === "2") {
      set.add("wxpay");
      continue;
    }
    if (item === "alipay" || item === "ali" || item === "1") {
      set.add("alipay");
      continue;
    }
  }
  if (!set.size) {
    return ["wxpay", "alipay"];
  }
  return Array.from(set);
}

function allowedPayTypes(env) {
  return parsePayTypes(env.PAYMENT_PAY_TYPES || env.XPAY_PAY_TYPES || "wxpay,alipay");
}

function normalizePayType(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "alipay" || text === "ali" || text === "1") {
    return "alipay";
  }
  if (text === "wxpay" || text === "wechat" || text === "weixin" || text === "2") {
    return "wxpay";
  }
  return "wxpay";
}

function channelIdFor(payType, env) {
  const any = cleanEnvValue(env.XPAY_CHANNEL_ID || env.CODEPAY_CHANNEL_ID);
  const wxpay = cleanEnvValue(env.XPAY_CHANNEL_ID_WXPAY || env.CODEPAY_CHANNEL_ID_WXPAY) || any;
  const alipay = cleanEnvValue(env.XPAY_CHANNEL_ID_ALIPAY || env.CODEPAY_CHANNEL_ID_ALIPAY) || any;
  if (payType === "alipay") {
    return alipay;
  }
  return wxpay;
}

function cleanProviderValue(value) {
  return String(value || "")
    .replace(/\u0000/g, "")
    .trim()
    .replace(/^['"]+/, "")
    .replace(/['"]+$/, "");
}

async function approveRechargeRequest(requestId, params, env) {
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
    return { ok: true };
  } catch (err) {
    const message = String(err.message || "");
    if (message.includes("already reviewed")) {
      return { ok: true, alreadyReviewed: true };
    }
    throw err;
  }
}

async function rejectRechargeRequest(requestId, reason, env) {
  try {
    await requestJson(
      `${env.PYTHONANYWHERE_BASE_URL}/api/admin/recharge-requests/${requestId}/reject?token=${encodeURIComponent(env.PYTHONANYWHERE_ADMIN_TOKEN)}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          review_note: String(reason || "payment create failed").slice(0, 180),
        }),
      }
    );
  } catch {
    // Best-effort cleanup. If it fails, the admin can still review manually.
  }
}

async function providerCreateOrder(params, env) {
  const resp = await fetch(`${providerBase(env)}${providerCreatePath(env)}`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params).toString(),
  });
  const text = await resp.text();
  let json = {};
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = { raw: text };
  }
  return { ok: resp.ok, status: resp.status, json };
}

async function createRechargeOrder(request, env) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.toLowerCase().startsWith("bearer ")) {
    return json({ detail: "missing bearer token" }, 401);
  }

  const body = await request.json();
  const amountYuan = Number(body.amount_yuan || 0);
  const payType = normalizePayType(body.pay_type);
  if (!Number.isFinite(amountYuan) || amountYuan <= 0) {
    return json({ detail: "invalid amount_yuan" }, 400);
  }
  const allowedTypes = allowedPayTypes(env);
  if (!allowedTypes.includes(payType)) {
    return json({ detail: `pay_type not allowed: ${payType}`, allowed_pay_types: allowedTypes }, 400);
  }

  const rechargeRequest = await requestJson(`${env.PYTHONANYWHERE_BASE_URL}/api/me/recharge-requests`, {
    method: "POST",
    headers: {
      authorization: auth,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      amount_yuan: amountYuan,
      payment_method: payType === "alipay" ? "alipay_auto" : "wxpay_auto",
      note: body.note || "serverless bridge recharge",
    }),
  });

  const outTradeNo = buildOutTradeNo(rechargeRequest.id);
  const notifyUrl = new URL("/api/payment/notify", request.url).toString();
  const pid = providerPid(env);
  const key = providerKey(env);
  const signMode = providerSignMode(env);
  const params = {
    pid,
    type: payType,
    out_trade_no: outTradeNo,
    money: amountYuan.toFixed(2),
    name: "Recharge Topup",
    notify_url: notifyUrl,
    return_url: env.RETURN_URL || body.return_url || env.PYTHONANYWHERE_BASE_URL,
    clientip: request.headers.get("cf-connecting-ip") || "127.0.0.1",
    device: body.device || "pc",
    param: String(rechargeRequest.id),
    sign_type: "MD5",
  };
  const channelId = channelIdFor(payType, env);
  if (channelId) {
    params.channel_id = channelId;
  }
  params.sign = providerSign(params, key, signMode);

  let providerResult = await providerCreateOrder(params, env);
  let providerJson = providerResult.json;
  const providerMsg = String(providerJson.msg || providerJson.raw || "");
  if (!providerResult.ok) {
    await rejectRechargeRequest(rechargeRequest.id, providerMsg || `provider request failed (${providerResult.status})`, env);
    return json({ detail: providerMsg || `provider request failed (${providerResult.status})` }, 502);
  }
  if (String(providerJson.code || "") !== "1") {
    // Some providers require different channel_id per payType. If Alipay fails with a channel_id,
    // try once without channel_id before giving up.
    if (
      payType === "alipay" &&
      params.channel_id &&
      providerMsg.includes("不支持此支付方式")
    ) {
      const retryParams = { ...params };
      delete retryParams.channel_id;
      retryParams.sign = providerSign(retryParams, key, signMode);
      providerResult = await providerCreateOrder(retryParams, env);
      providerJson = providerResult.json;
      if (providerResult.ok && String(providerJson.code || "") === "1") {
        return json({
          ok: true,
          recharge_request_id: rechargeRequest.id,
          out_trade_no: outTradeNo,
          pay_url:
            cleanProviderValue(providerJson.payurl) ||
            cleanProviderValue(providerJson.h5_qrurl) ||
            (providerJson.trade_no ? `${providerBase(env)}/pay/${providerJson.trade_no}` : ""),
          qrcode: cleanProviderValue(providerJson.qrcode),
          urlscheme: cleanProviderValue(providerJson.urlscheme),
          provider: providerJson,
          retry: { without_channel_id: true },
        });
      }
    }

    await rejectRechargeRequest(rechargeRequest.id, providerJson.msg || "provider create order failed", env);
    return json({ detail: providerJson.msg || "provider create order failed", provider: providerJson }, 502);
  }

  return json({
    ok: true,
    recharge_request_id: rechargeRequest.id,
    out_trade_no: outTradeNo,
    pay_url:
      cleanProviderValue(providerJson.payurl) ||
      cleanProviderValue(providerJson.h5_qrurl) ||
      (providerJson.trade_no ? `${providerBase(env)}/pay/${providerJson.trade_no}` : ""),
    qrcode: cleanProviderValue(providerJson.qrcode),
    urlscheme: cleanProviderValue(providerJson.urlscheme),
    provider: providerJson,
  });
}

async function queryRechargeStatus(request, env) {
  const url = new URL(request.url);
  const outTradeNo = String(url.searchParams.get("out_trade_no") || "").trim();
  if (!outTradeNo) {
    return json({ detail: "missing out_trade_no" }, 400);
  }
  const queryPath = providerQueryPath(env);
  const queryMethod = providerQueryMethod(env);
  const queryStyle = providerQueryStyle(env);
  let provider;

  if (queryMethod === "post" || queryStyle === "qjpay") {
    const providerUrl = new URL(`${providerBase(env)}${queryPath}`);
    const payload =
      queryStyle === "qjpay"
        ? { apiid: providerPid(env), apikey: providerKey(env), out_trade_no: outTradeNo }
        : { pid: providerPid(env), key: providerKey(env), out_trade_no: outTradeNo };
    provider = await requestJson(providerUrl.toString(), {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(payload).toString(),
    });
  } else {
    const providerUrl = new URL(`${providerBase(env)}${queryPath}`);
    providerUrl.searchParams.set("act", "order");
    providerUrl.searchParams.set("pid", providerPid(env));
    providerUrl.searchParams.set("key", providerKey(env));
    providerUrl.searchParams.set("out_trade_no", outTradeNo);
    provider = await requestJson(providerUrl.toString(), { method: "GET" });
  }
  const requestId = parseRequestId(outTradeNo);
  const paid = String(provider.status || "") === "1";
  if (paid && requestId) {
    await approveRechargeRequest(requestId, provider, env);
  }
  return json({
    ok: true,
    out_trade_no: outTradeNo,
    recharge_request_id: requestId,
    paid,
    provider,
  });
}

async function paymentNotify(request, env) {
  const raw = await request.text();
  const params = Object.fromEntries(new URLSearchParams(raw));
  const { sign = "", ...unsigned } = params;
  const expected = providerSign(unsigned, providerKey(env), providerSignMode(env));
  if (String(sign).toLowerCase() !== expected.toLowerCase()) {
    return new Response("sign error", { status: 400 });
  }

  if (params.trade_status !== "TRADE_SUCCESS") {
    return new Response("success", { status: 200 });
  }

  const requestId = parseRequestId(params.out_trade_no);
  if (!requestId) {
    return new Response("invalid out_trade_no", { status: 400 });
  }

  try {
    await approveRechargeRequest(requestId, params, env);
  } catch (err) {
    return new Response(String(err.message || "notify failed"), { status: 500 });
  }

  return new Response("success", { status: 200 });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: jsonHeaders });
    }

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/health") {
      return json({
        ok: true,
        provider: env.PAYMENT_PROVIDER || "xpay_epay",
        pay_types: allowedPayTypes(env),
        payment_configured: paymentEnvReady(env),
        realtime_configured: realtimeEnvReady(env),
      });
    }
    if (request.method === "GET" && url.pathname === "/api/socket-overview") {
      return socketOverview(request, env, ctx);
    }
    if (request.method === "POST" && url.pathname === "/api/recharge/create") {
      if (!paymentEnvReady(env)) {
        return json({ detail: "missing required environment variables" }, 500);
      }
      return createRechargeOrder(request, env);
    }
    if (request.method === "GET" && url.pathname === "/api/recharge/status") {
      if (!paymentEnvReady(env)) {
        return json({ detail: "missing required environment variables" }, 500);
      }
      return queryRechargeStatus(request, env);
    }
    if (request.method === "POST" && url.pathname === "/api/payment/notify") {
      if (!paymentEnvReady(env)) {
        return json({ detail: "missing required environment variables" }, 500);
      }
      return paymentNotify(request, env);
    }
    return json({ detail: "not found" }, 404);
  },
};
