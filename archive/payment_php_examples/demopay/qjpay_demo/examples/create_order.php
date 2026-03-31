<?php
/**
 * 平安夜支付接口 - API创建订单示例
 * 
 * 本文件演示如何使用平安夜支付接口的API创建订单功能
 * API创建订单会返回支付二维码和链接，可在商户自己的网站上展示
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
 * 创建订单
 * 
 * @param string $type 支付方式，可选值：alipay(支付宝)、wxpay(微信支付)、qqpay(QQ钱包)
 * @param string $out_trade_no 商户订单号，不传则自动生成
 * @param float $money 支付金额
 * @param string $name 商品名称
 * @return array 创建结果
 */
function create_qjpay_order($type, $out_trade_no = '', $money = 0.01, $name = '测试商品') {
    $config = get_config();
    
    // 参数验证
    if (!in_array($type, array_keys($config['pay_types']))) {
        return ['code' => 0, 'msg' => '不支持的支付方式'];
    }
    
    if ($money <= 0) {
        return ['code' => 0, 'msg' => '支付金额必须大于0'];
    }
    
    // 生成商户订单号（如果未提供）
    if (empty($out_trade_no)) {
        $out_trade_no = generate_order_no('QJ');
    }
    
    // 构建请求参数
    $params = [
        'pid' => $config['merchant']['pid'],              // 商户ID
        'type' => $type,                                  // 支付方式
        'out_trade_no' => $out_trade_no,                  // 商户订单号
        'notify_url' => $config['callback']['notify_url'],// 异步通知地址
        'return_url' => $config['callback']['return_url'],// 同步跳转地址
        'name' => $name,                                  // 商品名称
        'money' => number_format($money, 2, '.', ''),     // 金额，精确到小数点后2位
        'sign_type' => 'MD5',                             // 签名方式，固定为MD5
    ];
    
    // 生成签名
    $params['sign'] = create_sign($params);
    
    // 发送请求
    $api_url = $config['api_url'] . '/mapi.php';
    $result = http_post($api_url, $params);
    
    // 处理响应
    if ($result === false) {
        return ['code' => 0, 'msg' => '网络请求失败'];
    }
    
    if (!is_array($result)) {
        return ['code' => 0, 'msg' => '响应格式错误'];
    }
    
    // 返回结果
    return $result;
}

// 示例：处理表单提交的支付请求
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // 获取表单参数
    $type = isset($_POST['type']) ? $_POST['type'] : '';
    $out_trade_no = isset($_POST['out_trade_no']) ? $_POST['out_trade_no'] : '';
    $money = isset($_POST['money']) ? floatval($_POST['money']) : 0.01;
    $name = isset($_POST['name']) ? $_POST['name'] : '测试商品';
    
    // 创建订单
    $result = create_qjpay_order($type, $out_trade_no, $money, $name);
    
    // 返回JSON结果
    header('Content-Type: application/json');
    echo json_encode($result, JSON_UNESCAPED_UNICODE);
    exit;
}

// 如果是GET请求，显示表单
?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付接口 - API创建订单示例</title>
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
        #result {
            margin-top: 20px;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: #f9f9f9;
            display: none;
        }
        .qrcode-container {
            text-align: center;
            margin-top: 20px;
        }
        .payment-info {
            margin-top: 15px;
            padding: 10px;
            background-color: #eaf7ff;
            border-radius: 4px;
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
        <h1>平安夜支付接口 - API创建订单示例</h1>
        <p>本示例演示如何使用平安夜支付接口的API创建订单功能，获取支付二维码和链接</p>
        
        <a href="../index.php" class="btn-home">返回首页</a>
        
        <form id="payForm">
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
            
            <button type="submit">创建订单</button>
        </form>
        
        <div id="result">
            <h2>创建结果</h2>
            <pre id="resultContent"></pre>
            
            <div class="qrcode-container" id="qrcodeContainer" style="display:none;">
                <h3>扫码支付</h3>
                <div id="qrcode"></div>
                <div class="payment-info">
                    <p>订单金额: <span id="orderMoney"></span> 元</p>
                    <p>订单状态: <span id="orderStatus">未支付</span></p>
                    <p><a href="#" id="h5PayUrl" target="_blank">点击跳转到H5支付页面</a></p>
                </div>
            </div>
            
            <div class="panel qr-code-panel" style="display:none;">
                <div class="panel-heading">扫码支付</div>
                <div class="panel-body">
                    <div class="row">
                        <div class="col-md-6">
                            <div id="qrcode-container" class="text-center"></div>
                            <p class="text-center mt-2">请使用平安夜App扫描二维码进行支付</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="note">
                <p><strong>提示：</strong> API创建订单成功后，可以获取支付二维码和H5支付链接。用户可以通过扫描二维码或点击H5链接完成支付。</p>
                <p>支付完成后，平安夜会通过异步通知接口通知商户支付结果，同时用户也会被重定向到同步跳转地址。</p>
            </div>
        </div>
    </div>
    
    <!-- 引入用于生成二维码的库 -->
    <!-- 注意：使用腾讯二维码生成API，不需要引入JS库 -->
    
    <script>
        document.getElementById('payForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            // 获取表单数据
            var formData = new FormData(this);
            
            // 发送AJAX请求
            fetch('create_order.php', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // 显示原始结果
                document.getElementById('result').style.display = 'block';
                document.getElementById('resultContent').textContent = JSON.stringify(data, null, 2);
                
                // 如果创建成功，显示二维码
                if (data.code === 1 && data.qrcode) {
                    // 显示二维码容器
                    document.getElementById('qrcodeContainer').style.display = 'block';
                    
                    // 使用腾讯二维码生成API
                    var qrcodeUrl = 'https://minico.qq.com/qrcode/get?type=2&r=2&size=250&text=' + encodeURIComponent(data.qrcode);
                    document.getElementById('qrcode').innerHTML = '<img src="' + qrcodeUrl + '" alt="支付二维码" />';
                    
                    // 显示订单信息
                    document.getElementById('orderMoney').textContent = data.money;
                    
                    // 设置H5支付链接
                    if (data.h5_qrurl) {
                        var h5PayLink = document.getElementById('h5PayUrl');
                        h5PayLink.href = data.h5_qrurl;
                        h5PayLink.style.display = 'inline';
                    }
                    
                    // 启动轮询检查订单状态
                    var orderId = document.getElementById('out_trade_no').value || data.out_trade_no;
                    if (orderId) {
                        checkOrderStatus(orderId);
                    }
                }
            })
            .catch(error => {
                console.error('请求失败:', error);
                alert('请求失败，请查看控制台了解详情');
            });
        });
        
        // 轮询检查订单状态
        function checkOrderStatus(out_trade_no) {
            if (!out_trade_no) return;
            
            // 定时器，每5秒检查一次
            var statusTimer = setInterval(function() {
                // 构建表单数据
                var formData = new FormData();
                formData.append('out_trade_no', out_trade_no);
                
                // 发送查询请求
                fetch('../examples/query_order.php', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    console.log('订单状态查询结果:', data);
                    if (data.code === 1) {
                        if (data.status === 1) {
                            // 订单已支付
                            document.getElementById('orderStatus').textContent = '已支付';
                            document.getElementById('orderStatus').style.color = '#28a745';
                            clearInterval(statusTimer);
                            alert('订单支付成功！');
                        }
                    }
                })
                .catch(error => {
                    console.error('检查订单状态失败:', error);
                });
            }, 5000);
        }
    </script>
</body>
</html> 