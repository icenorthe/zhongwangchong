<?php
/**
 * QJPay支付接口 - 同步跳转处理
 * 
 * 本文件用于接收支付成功后的同步跳转
 * 支付完成后，用户会被跳转到该页面
 * 
 * 注意：此页面主要用于向用户展示支付结果
 * 真正的订单处理应该在异步通知中完成
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入公共函数库
require_once __DIR__ . '/libs/functions.php';

// 记录跳转信息
write_log('收到同步跳转', 'info', $_GET);

// 获取通知参数
$params = $_GET;

// 初始化支付结果
$payment_success = false;
$payment_message = '支付失败';
$order_info = [
    'out_trade_no' => isset($params['out_trade_no']) ? $params['out_trade_no'] : '未知',
    'trade_no' => isset($params['trade_no']) ? $params['trade_no'] : '未知',
    'type' => isset($params['type']) ? $params['type'] : '未知',
    'money' => isset($params['money']) ? $params['money'] : '0.00',
    'trade_status' => isset($params['trade_status']) ? $params['trade_status'] : '未知',
];

// 验证参数
if (!empty($params) && isset($params['sign'])) {
    // 验证签名
    if (verify_sign($params)) {
        // 验证支付状态
        if (isset($params['trade_status']) && $params['trade_status'] === 'TRADE_SUCCESS') {
            $payment_success = true;
            $payment_message = '支付成功';
        } else {
            $payment_message = '支付未完成';
        }
    } else {
        $payment_message = '数据校验失败';
        write_log('同步跳转签名验证失败', 'error', [
            'received' => $params['sign'],
            'calculated' => create_sign($params)
        ]);
    }
} else {
    $payment_message = '参数不完整';
}

// 获取支付方式名称
$config = get_config();
$payment_type = isset($params['type']) && isset($config['pay_types'][$params['type']]) 
                ? $config['pay_types'][$params['type']] 
                : '未知支付方式';

// 记录处理结果
write_log('同步跳转处理结果', 'info', [
    'success' => $payment_success,
    'message' => $payment_message,
    'order_info' => $order_info
]);

?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>支付结果 - QJPay支付演示</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 800px;
            margin: 20px auto;
            background-color: #fff;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            text-align: center;
        }
        .success-icon {
            font-size: 60px;
            color: #28a745;
            margin-bottom: 20px;
        }
        .fail-icon {
            font-size: 60px;
            color: #dc3545;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        p {
            margin-bottom: 10px;
            color: #666;
            line-height: 1.5;
        }
        .order-info {
            background-color: #f9f9f9;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            margin: 20px 0;
            text-align: left;
        }
        .order-info p {
            margin: 5px 0;
        }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            background-color: #4CAF50;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            margin-top: 20px;
            transition: background-color 0.3s;
        }
        .btn:hover {
            background-color: #45a049;
        }
    </style>
</head>
<body>
    <div class="container">
        <?php if ($payment_success): ?>
        <div class="success-icon">✅</div>
        <h1>支付成功</h1>
        <p>您的订单已支付完成，感谢您的购买！</p>
        <?php else: ?>
        <div class="fail-icon">❌</div>
        <h1>支付结果：<?php echo $payment_message; ?></h1>
        <p>抱歉，您的支付尚未完成，请稍后查看订单状态或联系客服。</p>
        <?php endif; ?>
        
        <div class="order-info">
            <h2>订单信息</h2>
            <p><strong>商户订单号：</strong><?php echo htmlspecialchars($order_info['out_trade_no']); ?></p>
            <p><strong>平台订单号：</strong><?php echo htmlspecialchars($order_info['trade_no']); ?></p>
            <p><strong>支付方式：</strong><?php echo htmlspecialchars($payment_type); ?></p>
            <p><strong>支付金额：</strong><?php echo htmlspecialchars($order_info['money']); ?> 元</p>
            <p><strong>支付状态：</strong><?php echo $payment_success ? '已支付' : '未支付'; ?></p>
        </div>
        
        <p>本页面仅用于显示支付结果，真实订单处理将在后台完成。</p>
        <a href="index.php" class="btn">返回首页</a>
    </div>
</body>
</html> 