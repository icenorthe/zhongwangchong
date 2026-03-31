<?php
/**
 * 平安夜支付接口 - 用户信息查询示例
 * 
 * 本文件演示如何使用平安夜支付接口的用户信息查询功能
 * 可用于查询商户的费率、余额等信息
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
 * 查询用户信息
 * 
 * @param string $out_trade_no 商户订单号（可选，如果提供则同时查询该订单信息）
 * @return array 查询结果
 */
function query_user($out_trade_no = '') {
    $config = get_config();
    
    // 构建请求参数
    $params = [
        'apiid' => $config['merchant']['pid'],      // 商户ID
        'apikey' => $config['merchant']['key'],     // 商户密钥
    ];
    
    // 如果提供了订单号，则同时查询订单信息
    if (!empty($out_trade_no)) {
        $params['out_trade_no'] = $out_trade_no;
    }
    
    // 发送请求
    $api_url = $config['api_url'] . '/qjt.php?act=query_user';
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
    // 获取订单号（可选）
    $out_trade_no = isset($_POST['out_trade_no']) ? $_POST['out_trade_no'] : '';
    
    // 查询用户信息
    $result = query_user($out_trade_no);
    
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
    <title>平安夜支付接口 - 用户信息查询示例</title>
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
        .user-info, .order-info {
            margin-top: 15px;
            border-collapse: collapse;
            width: 100%;
        }
        .user-info th, .user-info td,
        .order-info th, .order-info td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        .user-info th, .order-info th {
            background-color: #f2f2f2;
        }
        .note {
            margin-top: 20px;
            padding: 10px;
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            color: #856404;
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
        <h1>平安夜支付接口 - 用户信息查询示例</h1>
        <p>本示例演示如何使用平安夜支付接口的用户信息查询功能，获取商户的费率、余额等信息</p>
        
        
        <form id="queryForm">
            <div class="form-group">
                <label for="out_trade_no">商户订单号 (可选):</label>
                <input type="text" id="out_trade_no" name="out_trade_no" placeholder="如果提供订单号，则同时查询该订单信息">
            </div>
            
            <button type="submit">查询用户信息</button>
        </form>
        
        <div class="note">
            <p><strong>说明：</strong> 如果提供订单号，则同时查询该订单的支付链接和二维码等信息。</p>
        </div>
        
        <div id="result">
            <h2>查询结果</h2>
            <pre id="resultContent"></pre>
            
            <div id="userInfo" style="display:none;">
                <h3>用户信息</h3>
                <table class="user-info">
                    <tr>
                        <th>费率</th>
                        <td id="showRate"></td>
                    </tr>
                    <tr>
                        <th>账户余额</th>
                        <td id="showMoney"></td>
                    </tr>
                    <tr>
                        <th>订单超时时间</th>
                        <td id="showTimeoutTime"></td>
                    </tr>
                    <tr>
                        <th>语音播报</th>
                        <td id="showVoice"></td>
                    </tr>
                    <tr>
                        <th>语音内容模板</th>
                        <td id="showVoiceContent"></td>
                    </tr>
                    <tr>
                        <th>收银台提示信息</th>
                        <td id="showCashDeskTips"></td>
                    </tr>
                </table>
            </div>
            
            <div id="orderInfo" style="display:none;">
                <h3>订单信息</h3>
                <table class="order-info">
                    <tr>
                        <th>H5支付链接</th>
                        <td>
                            <span id="showH5QrUrl"></span>
                            <a href="#" id="openH5QrUrl" target="_blank" style="margin-left: 10px;">[打开]</a>
                        </td>
                    </tr>
                    <tr>
                        <th>支付二维码内容</th>
                        <td id="showQrcode"></td>
                    </tr>
                    <tr>
                        <th>订单状态</th>
                        <td id="showStatus"></td>
                    </tr>
                    <tr>
                        <th>二维码预览</th>
                        <td>
                            <div id="qrcode"></div>
                        </td>
                    </tr>
                </table>
            </div>
        </div>
        
        <a href="../index.php" class="btn-home">返回首页</a>
    </div>
    
    <!-- 引入用于生成二维码的库 -->
    <script src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
    
    <script>
        document.getElementById('queryForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            // 构建请求数据
            var formData = new FormData();
            formData.append('action', 'query');
            
            var out_trade_no = document.getElementById('out_trade_no').value;
            if (out_trade_no) {
                formData.append('out_trade_no', out_trade_no);
            }
            
            // 发送AJAX请求
            fetch('query_user.php', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // 显示原始结果
                document.getElementById('result').style.display = 'block';
                document.getElementById('resultContent').textContent = JSON.stringify(data, null, 2);
                
                // 如果查询成功，显示用户信息
                if (data.code === 1 && data.data) {
                    // 显示用户信息
                    document.getElementById('userInfo').style.display = 'block';
                    
                    // 填充用户信息
                    document.getElementById('showRate').textContent = data.data.rate ? data.data.rate + '%' : '-';
                    document.getElementById('showMoney').textContent = data.data.money ? data.data.money + ' 元' : '-';
                    document.getElementById('showTimeoutTime').textContent = data.data.timeout_time ? data.data.timeout_time + ' 秒' : '-';
                    document.getElementById('showVoice').textContent = data.data.voice === 1 ? '开启' : '关闭';
                    document.getElementById('showVoiceContent').textContent = data.data.voice_content || '-';
                    document.getElementById('showCashDeskTips').textContent = data.data.cash_desk_tips || '-';
                    
                    // 如果有订单信息，显示订单信息
                    if (data.order) {
                        document.getElementById('orderInfo').style.display = 'block';
                        
                        // 填充订单信息
                        document.getElementById('showH5QrUrl').textContent = data.order.h5_qrurl || '-';
                        document.getElementById('openH5QrUrl').href = data.order.h5_qrurl || '#';
                        document.getElementById('showQrcode').textContent = data.order.qrcode || '-';
                        
                        // 显示订单状态
                        var statusText = '未知';
                        if (data.order.status === 0) {
                            statusText = '未支付';
                        } else if (data.order.status === 1) {
                            statusText = '已支付';
                        }
                        document.getElementById('showStatus').textContent = statusText;
                        
                        // 如果有二维码内容，生成二维码
                        if (data.order.qrcode) {
                            var typeNumber = 0;
                            var errorCorrectionLevel = 'L';
                            var qr = qrcode(typeNumber, errorCorrectionLevel);
                            qr.addData(data.order.qrcode);
                            qr.make();
                            document.getElementById('qrcode').innerHTML = qr.createImgTag(5);
                        } else {
                            document.getElementById('qrcode').innerHTML = '无二维码信息';
                        }
                    } else {
                        document.getElementById('orderInfo').style.display = 'none';
                    }
                } else {
                    // 隐藏用户和订单信息
                    document.getElementById('userInfo').style.display = 'none';
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