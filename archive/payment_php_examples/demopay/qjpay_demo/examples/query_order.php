<?php
/**
 * 平安夜支付接口 - 订单查询示例
 * 
 * 本文件演示如何使用平安夜支付接口的订单查询功能
 * 可用于查询订单的支付状态、金额等信息
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
 * 查询订单
 * 
 * @param string $out_trade_no 商户订单号
 * @return array 查询结果
 */
function query_order($out_trade_no) {
    $config = get_config();
    
    // 参数验证
    if (empty($out_trade_no)) {
        return ['code' => 0, 'msg' => '商户订单号不能为空'];
    }
    
    // 构建请求参数
    $params = [
        'apiid' => $config['merchant']['pid'],       // 商户ID
        'apikey' => $config['merchant']['key'],      // 商户密钥
        'out_trade_no' => $out_trade_no,             // 商户订单号
    ];
    
    // 发送请求
    $api_url = $config['api_url'] . '/qjt.php?act=query_order';
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

// 示例：处理AJAX查询请求
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'query') {
    // 获取订单号
    $out_trade_no = isset($_POST['out_trade_no']) ? $_POST['out_trade_no'] : '';
    
    // 查询订单
    $result = query_order($out_trade_no);
    
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
    <title>平安夜支付接口 - 订单查询示例</title>
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
        input[type="text"] {
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
        .order-info {
            margin-top: 15px;
            border-collapse: collapse;
            width: 100%;
        }
        .order-info th, .order-info td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        .order-info th {
            background-color: #f2f2f2;
        }
        .status-0 {
            color: #dc3545;
        }
        .status-1 {
            color: #28a745;
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
        <h1>平安夜支付接口 - 订单查询示例</h1>
        <p>本示例演示如何使用平安夜支付接口的订单查询功能，查询订单的支付状态和详细信息</p>
        
        
        <form id="queryForm">
            <div class="form-group">
                <label for="out_trade_no">商户订单号:</label>
                <input type="text" id="out_trade_no" name="out_trade_no" required>
            </div>
            
            <button type="submit">查询订单</button>
        </form>
        
        <div id="result">
            <h2>查询结果</h2>
            <pre id="resultContent"></pre>
            
            <div id="orderInfo" style="display:none;">
                <h3>订单详情</h3>
                <table class="order-info">
                    <tr>
                        <th>商户订单号</th>
                        <td id="showOutTradeNo"></td>
                    </tr>
                    <tr>
                        <th>平台订单号</th>
                        <td id="showTradeNo"></td>
                    </tr>
                    <tr>
                        <th>支付金额</th>
                        <td id="showMoney"></td>
                    </tr>
                    <tr>
                        <th>订单状态</th>
                        <td id="showStatus"></td>
                    </tr>
                    <tr>
                        <th>支付时间</th>
                        <td id="showEndTime"></td>
                    </tr>
                </table>
            </div>
        </div>
        
        <a href="../index.php" class="btn-home">返回首页</a>
    </div>
    
    <script>
        document.getElementById('queryForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            var out_trade_no = document.getElementById('out_trade_no').value;
            
            // 检查订单号是否为空
            if (!out_trade_no) {
                alert('请输入商户订单号');
                return;
            }
            
            // 构建请求数据
            var formData = new FormData();
            formData.append('action', 'query');
            formData.append('out_trade_no', out_trade_no);
            
            // 发送AJAX请求
            fetch('query_order.php', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // 显示原始结果
                document.getElementById('result').style.display = 'block';
                document.getElementById('resultContent').textContent = JSON.stringify(data, null, 2);
                
                // 如果查询成功，显示订单详情
                if (data.code === 1) {
                    // 显示订单详情
                    document.getElementById('orderInfo').style.display = 'block';
                    
                    // 填充订单信息
                    document.getElementById('showOutTradeNo').textContent = data.out_trade_no || '-';
                    document.getElementById('showTradeNo').textContent = data.trade_no || '-';
                    document.getElementById('showMoney').textContent = data.money ? data.money + ' 元' : '-';
                    
                    // 显示订单状态
                    var statusText = '未知';
                    var statusClass = '';
                    
                    if (data.status === 0) {
                        statusText = '未支付';
                        statusClass = 'status-0';
                    } else if (data.status === 1) {
                        statusText = '已支付';
                        statusClass = 'status-1';
                    }
                    
                    var statusElement = document.getElementById('showStatus');
                    statusElement.textContent = statusText;
                    statusElement.className = statusClass;
                    
                    // 显示支付时间
                    document.getElementById('showEndTime').textContent = data.end_time || '-';
                } else {
                    // 隐藏订单详情
                    document.getElementById('orderInfo').style.display = 'none';
                }
            })
            .catch(error => {
                console.error('请求失败:', error);
                alert('请求失败，请查看控制台了解详情');
            });
        });
    </script>
</body>
</html> 