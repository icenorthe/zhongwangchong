# 平安夜支付接口文档

## 目录

- [接口说明](#接口说明)
- [签名算法](#签名算法)
- [接口列表](#接口列表)
  - [API创建订单](#api创建订单)
  - [跳转支付](#跳转支付)
  - [订单查询](#订单查询)
  - [用户信息查询](#用户信息查询)
- [支付站点对接](#支付站点对接)

## 接口说明

- 接口基础域名: `https://pro.qjpay.icu`
- 备用节点:
  - 节点1: `https://pro1.qjpay.icu`
  - 节点2: `https://pro2.qjpay.icu`
  - 节点3: `https://pro3.qjpay.icu`
- 所有请求方式均为 POST，除非特别说明
- 编码格式：UTF-8
- 签名方式：MD5

## 签名算法

1. 对所有API参数(除sign和sign_type外)，按照参数名ASCII码从小到大排序
2. 把所有参数名和参数值拼接成字符串，格式为: `参数名=参数值&参数名=参数值...`
3. 在最后直接拼接上商户密钥: `原字符串+商户密钥`
4. 对拼接后的字符串进行MD5加密，得到32位小写签名

示例:
```php
/**
 * 生成签名
 * 
 * @param array $params 要签名的参数数组
 * @param string $key 商户密钥
 * @return string MD5签名
 */
function getSign($params, $key) {
    // 1. 过滤掉空值和签名参数
    $filter_params = [];
    foreach ($params as $k => $v) {
        if ($k != "sign" && $k != "sign_type" && $v !== '') {
            $filter_params[$k] = $v;
        }
    }
    
    // 2. 按照参数名ASCII码从小到大排序
    ksort($filter_params);
    reset($filter_params);
    
    // 3. 拼接成字符串
    $signstr = '';
    foreach ($filter_params as $k => $v) {
        $signstr .= $k . '=' . $v . '&';
    }
    $signstr = substr($signstr, 0, -1);  // 去掉最后的&
    
    // 4. 拼接商户密钥
    $signstr .= $key;
    
    // 5. MD5加密
    return md5($signstr);
}
```

## 接口列表

### API创建订单

**请求URL:** `/mapi.php`

**请求方式:** POST

**请求参数:**

| 参数名 | 必选 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| pid | 是 | string | 商户ID |
| type | 是 | string | 支付方式(alipay/wxpay/qqpay) |
| out_trade_no | 是 | string | 商户订单号 |
| notify_url | 是 | string | 异步通知地址 |
| return_url | 是 | string | 同步跳转地址 |
| name | 是 | string | 商品名称 |
| money | 是 | string | 金额，精确到小数点后2位 |
| sign | 是 | string | 签名 |
| sign_type | 是 | string | 签名方式，固定值：MD5 |

**返回参数:**

| 参数名 | 类型 | 说明 |
| :--- | :--- | :--- |
| code | int | 状态码，1=成功，0=失败 |
| msg | string | 返回信息 |
| qrcode | string | 支付二维码内容 |
| h5_qrurl | string | H5支付跳转链接 |
| money | string | 实际支付金额 |
| status | int | 订单状态，0=未支付，1=已支付 |

### 跳转支付

**请求URL:** `/submit.php`

**说明:** 此接口用于跳转到支付站点进行支付，会展示收银台页面。

**请求方式:** POST

**请求参数:**

| 参数名 | 必选 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| pid | 是 | string | 商户ID |
| type | 是 | string | 支付方式(alipay/wxpay/qqpay) |
| out_trade_no | 是 | string | 商户订单号 |
| notify_url | 是 | string | 异步通知地址 |
| return_url | 是 | string | 同步跳转地址 |
| name | 是 | string | 商品名称 |
| money | 是 | string | 金额，精确到小数点后2位 |
| sitename | 否 | string | 网站名称 |
| sign | 是 | string | 签名 |
| sign_type | 是 | string | 签名方式，固定值：MD5 |

**返回说明:**
- 接口会返回一个 HTML 页面，自动跳转到支付站点的收银台
- 用户可以在收银台页面选择支付方式并完成支付
- 支付完成后会跳转到 return_url 指定的地址

### 订单查询

**请求URL:** `/qjt.php?act=query_order`

**请求方式:** POST

**请求参数:**

| 参数名 | 必选 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| apiid | 是 | string | 商户ID |
| apikey | 是 | string | 商户密钥 |
| out_trade_no | 是 | string | 商户订单号 |

**返回参数:**

| 参数名 | 类型 | 说明 |
| :--- | :--- | :--- |
| code | int | 状态码，1=成功，0=失败 |
| msg | string | 返回信息 |
| status | int | 订单状态，0=未支付，1=已支付 |
| out_trade_no | string | 商户订单号 |
| trade_no | string | 平台订单号 |
| money | string | 支付金额 |
| end_time | string | 支付完成时间 |

### 用户信息查询

**请求URL:** `/qjt.php?act=query_user`

**请求方式:** POST

**请求参数:**

| 参数名 | 必选 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| apiid | 是 | string | 商户ID |
| apikey | 是 | string | 商户密钥 |
| out_trade_no | 否 | string | 商户订单号（可选） |

**返回参数:**

| 参数名 | 类型 | 说明 |
| :--- | :--- | :--- |
| code | int | 状态码，1=成功，0=失败 |
| msg | string | 返回信息 |
| data | object | 用户信息 |
| data.rate | float | 费率(百分比) |
| data.money | float | 账户余额 |
| data.timeout_time | int | 订单超时时间(秒) |
| data.voice | int | 是否开启语音播报，1=开启，0=关闭 |
| data.voice_content | string | 语音播报内容模板 |
| data.cash_desk_tips | string | 收银台提示信息 |
| order | object | 订单信息（如果提供了订单号） |
| order.h5_qrurl | string | H5支付链接 |
| order.qrcode | string | 支付二维码内容 |
| order.status | int | 订单状态 |

## 支付站点对接

### 支付页面

支付站点提供了一个标准的支付页面，包含以下功能：

1. 显示订单信息
   - 支付金额
   - 商品名称
   - 订单号
   - 支付方式(支付宝/微信/QQ)

2. 二维码显示
   - 支持自定义二维码生成接口
   - 支持H5支付链接

3. 订单状态检测
   - 自动检测订单支付状态
   - 支持语音播报功能
   - 订单超时自动关闭

### 异步通知

支付成功后，平台会向您的异步通知地址(notify_url)发送支付结果。

**通知参数:**

| 参数名 | 类型 | 说明 |
| :--- | :--- | :--- |
| trade_no | string | 平台订单号 |
| out_trade_no | string | 商户订单号 |
| type | string | 支付方式 |
| money | string | 支付金额 |
| trade_status | string | 交易状态，TRADE_SUCCESS=支付成功 |
| sign | string | 签名 |
| sign_type | string | 签名类型 |

商户收到通知后，需要验证签名是否正确，验证通过后需要返回字符串 "success"，否则平台会重复发送通知。

### 同步跳转

支付成功后，用户会被跳转到同步跳转地址(return_url)，参数与异步通知相同。商户同样需要验证签名正确性。 