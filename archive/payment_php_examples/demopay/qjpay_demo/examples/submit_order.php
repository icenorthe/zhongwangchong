<?php
/**
 * 平安夜支付接口 - 跳转支付示例
 * 
 * 本文件演示如何使用平安夜支付接口的跳转支付功能
 * 跳转支付会将用户重定向到支付站点的收银台页面
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入公共函数库
require_once dirname(__DIR__) . '/libs/functions.php';

// 获取配置
$config = get_config();

/**
 * 生成跳转表单HTML
 * 
 * @param string $type 支付方式，可选值：alipay(支付宝)、wxpay(微信支付)、qqpay(QQ钱包)
 * @param string $out_trade_no 商户订单号，不传则自动生成
 * @param float $money 支付金额
 * @param string $name 商品名称
 * @return string HTML表单
 */
function generate_submit_form($type, $out_trade_no = '', $money = 0.01, $name = '测试商品') {
    $config = get_config();
    
    // 参数验证
    if (!in_array($type, array_keys($config['pay_types']))) {
        return '不支持的支付方式';
    }
    
    if ($money <= 0) {
        return '支付金额必须大于0';
    }
    
    // 生成商户订单号（如果未提供）
    if (empty($out_trade_no)) {
        $out_trade_no = generate_order_no('QJ');
    }
    
    // 构建请求参数
    $params = [
        'pid' => $config['merchant']['pid'],                // 商户ID
        'type' => $type,                                    // 支付方式
        'out_trade_no' => $out_trade_no,                    // 商户订单号
        'notify_url' => $config['callback']['notify_url'],  // 异步通知地址
        'return_url' => $config['callback']['return_url'],  // 同步跳转地址
        'name' => $name,                                    // 商品名称
        'money' => number_format($money, 2, '.', ''),       // 金额，精确到小数点后2位
        'sitename' => $config['site_name'],                 // 网站名称
        'sign_type' => 'MD5',                               // 签名方式，固定为MD5
    ];
    
    // 生成签名
    $params['sign'] = create_sign($params);
    
    // 生成表单HTML
    $html = '<form id="payForm" action="' . $config['api_url'] . '/submit.php" method="post">';
    foreach ($params as $key => $value) {
        $html .= '<input type="hidden" name="' . $key . '" value="' . htmlspecialchars($value) . '">';
    }
    $html .= '</form>';
    $html .= '<script>document.getElementById("payForm").submit();</script>';
    
    return $html;
}

// 示例：处理表单提交的支付请求
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // 获取表单参数
    $type = isset($_POST['type']) ? $_POST['type'] : '';
    $out_trade_no = isset($_POST['out_trade_no']) ? $_POST['out_trade_no'] : '';
    $money = isset($_POST['money']) ? floatval($_POST['money']) : 0.01;
    $name = isset($_POST['name']) ? $_POST['name'] : '测试商品';
    
    // 输出跳转表单
    echo generate_submit_form($type, $out_trade_no, $money, $name);
    exit;
}

// 如果是GET请求，显示表单
?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付接口 - 跳转支付示例</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background-color: #fff;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        }
        h1 {
            color: #333;
        }
        .form-group {
            margin-bottom: 15px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        input[type="text"],
        input[type="number"],
        select {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        button {
            background-color: #4CAF50;
            color: white;
            padding: 10px 15px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        button:hover {
            background-color: #45a049;
        }
        .note {
            margin-top: 20px;
            padding: 15px;
            background-color: #f8f9fa;
            border-left: 4px solid #4CAF50;
        }
        .btn-home {
            display: inline-block;
            padding: 8px 16px;
            background-color: #2196F3;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.3s;
            margin-top: 20px;
        }
        .btn-home:hover {
            background-color: #0b7dda;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>平安夜支付接口 - 跳转支付示例</h1>
        <p>本示例演示如何使用平安夜支付接口的跳转支付功能，跳转到平安夜收银台页面进行支付</p>
        
        
        <form action="submit_order.php" method="POST">
            <div class="form-group">
                <label for="type">支付方式:</label>
                <select id="type" name="type" required>
                    <?php foreach ($config['pay_types'] as $key => $value): ?>
                    <option value="<?php echo $key; ?>"><?php echo $value; ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            
            <div class="form-group">
                <label for="out_trade_no">商户订单号 (留空自动生成):</label>
                <input type="text" id="out_trade_no" name="out_trade_no" placeholder="留空则自动生成">
            </div>
            
            <div class="form-group">
                <label for="money">支付金额 (元):</label>
                <input type="number" id="money" name="money" value="0.01" min="0.01" step="0.01" required>
            </div>
            
            <div class="form-group">
                <label for="name">商品名称:</label>
                <input type="text" id="name" name="name" value="测试商品" required>
            </div>
            
            <button type="submit">提交订单</button>
        </form>
        
        <div class="note">
            <p><strong>提示：</strong> 点击提交后，页面将跳转到平安夜收银台页面进行支付。支付完成后，将根据配置的同步跳转地址返回商户网站。</p>
        </div>
        
        <a href="../index.php" class="btn-home">返回首页</a>
    </div>
</body>
</html> 