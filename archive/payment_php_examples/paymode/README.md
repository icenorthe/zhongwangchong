# 平安夜支付中转集成方案

本目录包含平安夜支付的中转集成方案，让用户无需跳转到支付平台即可完成付款，极大降低了集成门槛。

## 文件说明

- **submit.php**: 主要的支付中转文件，包含所有支付功能
- **notify.php**: 异步通知处理示例
- **return.php**: 同步跳转处理示例
- **demo.php**: 支付中转演示页面
- **api_demo.php**: API调用演示页面

## 快速开始

1. 修改 `submit.php` 中的配置信息：

```php
$config = [
    // API基础URL
    'api_url' => 'https://pro.qjpay.icu',
    
    // 商户信息
    'merchant' => [
        'pid' => '您的商户ID',
        'key' => '您的商户密钥',
    ],
    
    // 回调地址
    'callback' => [
        'notify_url' => 'http://您的域名/notify.php',
        'return_url' => 'http://您的域名/return.php',
    ],
    
    // 网站名称
    'site_name' => '您的网站名称',
];
```

2. 确保 `notify.php` 和 `return.php` 中的商户密钥与 `submit.php` 中的一致。

3. 访问 `demo.php` 查看演示页面，或访问 `api_demo.php` 查看API调用示例。

## 使用方法

### 1. 直接调用方式

通过链接或按钮直接跳转到支付页面：

```html
<a href="submit.php?type=alipay&name=VIP会员&money=0.01">支付宝支付</a>
<a href="submit.php?type=wxpay&name=高级会员&money=0.01">微信支付</a>
<a href="submit.php?type=qqpay&name=超级会员&money=0.01">QQ钱包支付</a>
```

### 2. 用户自选支付方式

如果不指定支付方式，用户可以自由选择：

```html
<a href="submit.php?name=VIP会员&money=0.01">去支付</a>
```

### 3. 表单提交方式

通过表单提交支付参数：

```html
<form action="submit.php" method="post">
    <select name="type">
        <option value="">用户自选</option>
        <option value="alipay">支付宝</option>
        <option value="wxpay">微信支付</option>
        <option value="qqpay">QQ钱包</option>
    </select>
    <input type="text" name="name" value="自定义商品" required>
    <input type="number" name="money" value="0.01" min="0.01" step="0.01" required>
    <input type="text" name="out_trade_no" placeholder="留空自动生成">
    <button type="submit">提交支付</button>
</form>
```

### 4. API调用方式

在PHP代码中调用支付函数：

```php
// 引入支付中转文件
require_once 'submit.php';

// 调用创建订单函数
$result = create_payment_order(
    'alipay',       // 支付方式
    '高级会员套餐', // 商品名称
    9.99,          // 支付金额
    'ORDER'.time()  // 订单号（可选）
);

// 处理返回结果
if ($result['code'] == 1) {
    // 获取支付二维码和H5链接
    $qrcode = $result['qrcode'];
    $h5_url = $result['h5_qrurl'];
    // 自定义显示支付页面...
} else {
    // 处理错误...
    echo $result['msg'];
}
```

## 回调处理

### 异步通知处理

平安夜支付平台会向您配置的 `notify_url` 发送异步通知，通知支付结果。您需要在 `notify.php` 中验证通知的合法性，并处理相应的业务逻辑。

```php
// 验证异步通知
$notify_result = validate_payment_notify($_POST);

if ($notify_result['verified']) {
    // 支付成功，更新订单状态
    $order_no = $notify_result['out_trade_no'];
    $trade_no = $notify_result['trade_no'];
    $money = $notify_result['money'];
    
    // 处理业务逻辑...
    
    // 返回成功
    echo 'success';
}
```

### 同步跳转处理

用户支付完成后会被跳转到您配置的 `return_url`，您可以在 `return.php` 中显示支付结果页面。

## 主要功能

1. **多种支付方式**：支持支付宝、微信支付、QQ钱包等多种支付方式
2. **用户自选支付方式**：可以让用户自由选择支付方式
3. **自适应界面**：自动适配PC端和移动端
4. **二维码生成**：使用腾讯二维码生成API
5. **订单状态查询**：支持查询订单支付状态
6. **回调验证**：内置签名验证功能，确保支付通知的安全性
7. **日志记录**：详细记录支付过程，方便排查问题

## 新增特性

1. **用户自选支付方式**：如果不指定支付方式，系统会显示支付方式选择页面，让用户自由选择
2. **纯付款界面**：用户无法修改支付参数，只能查看和支付
3. **参数验证优化**：更严格的参数验证，避免错误
4. **错误处理优化**：更友好的错误提示
5. **界面美化**：更美观的支付界面

## 注意事项

1. 请确保您的服务器能够被外网访问，否则无法接收异步通知
2. 商户密钥等敏感信息应妥善保管，避免泄露
3. 生产环境中建议使用HTTPS协议保证数据传输安全
4. 异步通知处理应做好防重复处理的措施

## 常见问题

1. **支付后没有收到异步通知**
   - 检查异步通知地址是否正确
   - 检查服务器是否能被外网访问
   - 检查防火墙设置
   - 检查 `notify.php` 是否有报错

2. **签名验证失败**
   - 检查商户密钥是否正确
   - 检查签名算法是否与文档一致
   - 检查参数格式是否正确

3. **二维码无法显示**
   - 确保网络可以访问腾讯二维码生成API
   - 检查二维码内容是否正确

## 技术支持

如有任何问题，请联系平安夜技术支持或参考官方接口文档。 