<?php
/**
 * 平安夜支付接口 - 演示首页
 * 
 * 本文件是平安夜支付接口演示程序的首页
 * 展示了各种支付方式和功能的入口
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入公共函数库
require_once __DIR__ . '/libs/functions.php';

// 获取配置
$config = get_config();

// 处理临时配置设置
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action']) && $_POST['action'] === 'update_config') {
    $temp_config = [
        'merchant_id' => isset($_POST['merchant_id']) ? trim($_POST['merchant_id']) : '',
        'merchant_key' => isset($_POST['merchant_key']) ? trim($_POST['merchant_key']) : ''
    ];
    
    // 保存到会话
    session_start();
    $_SESSION['temp_config'] = $temp_config;
    
    // 重定向以避免表单重复提交
    header('Location: ' . $_SERVER['PHP_SELF']);
    exit;
}

// 获取临时配置
if (session_status() === PHP_SESSION_NONE) {
    session_start();
}
$temp_config = isset($_SESSION['temp_config']) ? $_SESSION['temp_config'] : ['merchant_id' => '', 'merchant_key' => ''];
?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付接口演示</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background-color: #fff;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        h2 {
            color: #333;
            border-bottom: 1px solid #ddd;
            padding-bottom: 10px;
            margin-top: 30px;
        }
        p {
            color: #666;
            line-height: 1.5;
        }
        .cards {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-top: 20px;
        }
        .card {
            flex: 1;
            min-width: 300px;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            background-color: #fff;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }
        .card h3 {
            margin-top: 0;
            color: #333;
        }
        .card p {
            margin-bottom: 20px;
        }
        .card-footer {
            margin-top: 20px;
            text-align: right;
        }
        .btn {
            display: inline-block;
            padding: 8px 16px;
            background-color: #4CAF50;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.3s;
        }
        .btn:hover {
            background-color: #45a049;
        }
        .btn-doc {
            background-color: #2196F3;
        }
        .btn-doc:hover {
            background-color: #0b7dda;
        }
        .note {
            background-color: #f8f9fa;
            border-left: 4px solid #4CAF50;
            padding: 15px;
            margin: 20px 0;
        }
        .warning {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
            color: #856404;
        }
        footer {
            margin-top: 40px;
            text-align: center;
            color: #777;
            font-size: 14px;
        }
        .config-form {
            background-color: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            margin: 20px 0;
        }
        .form-row {
            margin-bottom: 15px;
        }
        .form-row label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        .form-row input[type="text"] {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        .form-buttons {
            display: flex;
            justify-content: space-between;
        }
        .btn-reset {
            background-color: #f44336;
        }
        .btn-reset:hover {
            background-color: #d32f2f;
        }
        .config-status {
            margin-top: 15px;
            padding: 10px;
            border-radius: 4px;
            background-color: #e8f5e9;
            color: #2e7d32;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>平安夜支付接口演示</h1>
        
        <div class="note">
            <p><strong>说明：</strong> 本演示程序基于平安夜支付接口文档开发，展示了如何集成平安夜支付功能到您的网站。</p>
            <p>您可以通过本演示程序了解平安夜支付接口的基本用法，包括创建订单、查询订单、处理回调等功能。</p>
        </div>
        
        <div class="warning">
            <p><strong>重要提示：</strong> 在实际应用中，请务必将商户密钥等敏感信息妥善保管，不要暴露在前端代码中。</p>
            <p>本演示程序仅供参考，实际使用时请根据您的业务需求进行适当调整和安全加固。</p>
        </div>
        
        <h2>商户配置</h2>
        <p>您可以在此设置临时的商户ID和密钥，用于测试您自己的接口。如果不设置，将使用默认配置。</p>
        
        <div class="config-form">
            <form method="POST" action="<?php echo $_SERVER['PHP_SELF']; ?>">
                <input type="hidden" name="action" value="update_config">
                
                <div class="form-row">
                    <label for="merchant_id">商户ID:</label>
                    <input type="text" id="merchant_id" name="merchant_id" value="<?php echo htmlspecialchars($temp_config['merchant_id']); ?>" placeholder="请输入您的商户ID">
                </div>
                
                <div class="form-row">
                    <label for="merchant_key">商户密钥:</label>
                    <input type="text" id="merchant_key" name="merchant_key" value="<?php echo htmlspecialchars($temp_config['merchant_key']); ?>" placeholder="请输入您的商户密钥">
                </div>
                
                <div class="form-buttons">
                    <button type="submit" class="btn">保存配置</button>
                    <a href="<?php echo $_SERVER['PHP_SELF']; ?>?clear_config=1" class="btn btn-reset">重置为默认</a>
                </div>
                
                <?php if (!empty($temp_config['merchant_id']) || !empty($temp_config['merchant_key'])): ?>
                <div class="config-status">
                    <p><strong>当前状态:</strong> 使用临时配置进行测试</p>
                </div>
                <?php endif; ?>
            </form>
        </div>
        
        <h2>接口演示</h2>
        <p>以下是平安夜支付接口的各种功能演示，点击对应的卡片查看详细示例。</p>
        
        <div class="cards">
            <div class="card">
                <h3>API创建订单</h3>
                <p>通过API接口创建支付订单，获取支付二维码和支付链接。适用于需要自定义支付页面的场景。</p>
                <div class="card-footer">
                    <a href="examples/create_order.php" class="btn">查看示例</a>
                </div>
            </div>
            
            <div class="card">
                <h3>跳转支付</h3>
                <p>创建订单并跳转到平安夜收银台页面进行支付。适用于不需要自定义支付页面的场景。</p>
                <div class="card-footer">
                    <a href="examples/submit_order.php" class="btn">查看示例</a>
                </div>
            </div>
            
            <div class="card">
                <h3>订单查询</h3>
                <p>查询订单的支付状态、金额等信息。可用于检查订单是否已支付。</p>
                <div class="card-footer">
                    <a href="examples/query_order.php" class="btn">查看示例</a>
                </div>
            </div>
            
            <div class="card">
                <h3>用户信息查询</h3>
                <p>查询商户的费率、余额等信息。同时可查询指定订单的支付链接和二维码。</p>
                <div class="card-footer">
                    <a href="examples/query_user.php" class="btn">查看示例</a>
                </div>
            </div>
            
            <div class="card">
                <h3>接口文档</h3>
                <p>查看平安夜支付接口的详细API文档和签名算法说明，帮助开发者理解和集成支付功能。</p>
                <div class="card-footer">
                    <a href="documentation.php" class="btn btn-doc">查看文档</a>
                </div>
            </div>
        </div>
        
        <h2>接口说明</h2>
        <p>平安夜支付接口提供了以下主要功能：</p>
        <ul>
            <li><strong>API创建订单</strong>：通过API接口创建订单，获取支付二维码和支付链接</li>
            <li><strong>跳转支付</strong>：将用户跳转到平安夜收银台页面进行支付</li>
            <li><strong>订单查询</strong>：查询订单的支付状态和详细信息</li>
            <li><strong>用户信息查询</strong>：查询商户的费率、余额等信息</li>
            <li><strong>异步通知</strong>：支付成功后，平安夜会发送异步通知到指定地址</li>
            <li><strong>同步跳转</strong>：支付成功后，用户会被跳转到指定页面</li>
        </ul>
        
        <h2>配置说明</h2>
        <p>使用平安夜支付接口前，需要进行以下配置：</p>
        <ol>
            <li>修改<code>config.php</code>文件中的商户ID和密钥，或者使用上方的临时配置功能</li>
            <li>设置正确的回调地址（异步通知地址和同步跳转地址）</li>
            <li>根据需要调整其他配置项</li>
        </ol>
        
        <div class="note">
            <p><strong>技术支持：</strong> 如有任何问题，请联系平安夜技术支持或参考<a href="documentation.php">接口文档</a>。</p>
        </div>
        
        <footer>
            <p>平安夜支付接口演示程序 &copy; 2025. 仅供学习和参考使用。</p>
        </footer>
    </div>
    
    <script>
        // 处理重置为默认配置的请求
        document.addEventListener('DOMContentLoaded', function() {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('clear_config')) {
                // 发送清除会话的请求
                fetch('clear_session.php')
                    .then(response => {
                        window.location.href = '<?php echo $_SERVER['PHP_SELF']; ?>';
                    })
                    .catch(error => console.error('无法清除会话:', error));
            }
        });
    </script>
</body>
</html> 