<?php
/**
 * 平安夜支付中转 - API调用演示
 * 
 * 本文件演示如何在PHP代码中调用支付中转文件的函数
 * 适用于需要在业务逻辑中集成支付功能的场景
 * 
 * @author 平安夜支付
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入支付中转文件
require_once 'submit.php';

// 设置页面编码
header('Content-Type: text/html; charset=UTF-8');

// 处理表单提交
$type = '';
$name = '';
$money = 0.01;
$out_trade_no = '';
$result = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // 获取表单数据
    $type = isset($_POST['type']) ? trim($_POST['type']) : 'alipay';
    $name = isset($_POST['name']) ? trim($_POST['name']) : '测试商品';
    $money = isset($_POST['money']) ? floatval($_POST['money']) : 0.01;
    $out_trade_no = isset($_POST['out_trade_no']) ? trim($_POST['out_trade_no']) : '';
    
    // 调用创建订单函数
    $result = create_payment_order($type, $name, $money, $out_trade_no);
}
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付 - API调用演示</title>
    <link href="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: #f8f9fa;
            padding-top: 2rem;
        }
        .demo-container {
            max-width: 800px;
            margin: 0 auto;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 15px rgba(0,0,0,0.1);
            padding: 2rem;
        }
        .code-block {
            background-color: #f8f9fa;
            border-radius: 5px;
            padding: 1rem;
            margin: 1rem 0;
            font-family: SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            font-size: 0.9rem;
            overflow-x: auto;
        }
        #qrcode-container {
            text-align: center;
            margin: 20px 0;
        }
        #qrcode-container img {
            max-width: 200px;
            margin: 0 auto;
        }
        .payment-result {
            border-left: 4px solid #007bff;
            padding: 1rem;
            background-color: #f8f9fa;
            margin: 1rem 0;
        }
        .payment-type-icon {
            width: 24px;
            height: 24px;
            margin-right: 8px;
            vertical-align: middle;
        }
    </style>
</head>
<body>
    <div class="container demo-container">
        <h1 class="text-center mb-4">平安夜支付 - API调用演示</h1>
        
        <div class="alert alert-info">
            <strong>说明：</strong> 本演示展示了如何在PHP代码中调用支付中转文件的函数，适用于需要在业务逻辑中集成支付功能的场景。
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <h2 class="mt-4 mb-3">创建支付订单</h2>
                
                <form method="post" action="">
                    <div class="mb-3">
                        <label for="type" class="form-label">支付方式</label>
                        <select name="type" id="type" class="form-select" required>
                            <option value="alipay" <?php echo $type == 'alipay' ? 'selected' : ''; ?>>支付宝</option>
                            <option value="wxpay" <?php echo $type == 'wxpay' ? 'selected' : ''; ?>>微信支付</option>
                            <option value="qqpay" <?php echo $type == 'qqpay' ? 'selected' : ''; ?>>QQ钱包</option>
                        </select>
                    </div>
                    
                    <div class="mb-3">
                        <label for="name" class="form-label">商品名称</label>
                        <input type="text" name="name" id="name" class="form-control" value="<?php echo htmlspecialchars($name ?: '测试商品'); ?>" required>
                    </div>
                    
                    <div class="mb-3">
                        <label for="money" class="form-label">支付金额</label>
                        <div class="input-group">
                            <input type="number" name="money" id="money" class="form-control" value="<?php echo $money ?: '0.01'; ?>" min="0.01" step="0.01" required>
                            <span class="input-group-text">元</span>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="out_trade_no" class="form-label">订单号（可选）</label>
                        <input type="text" name="out_trade_no" id="out_trade_no" class="form-control" value="<?php echo htmlspecialchars($out_trade_no); ?>" placeholder="留空自动生成">
                    </div>
                    
                    <button type="submit" class="btn btn-primary">创建订单</button>
                </form>
                
                <h3 class="mt-4">PHP代码示例</h3>
                <div class="code-block">
                    // 引入支付中转文件<br>
                    require_once 'submit.php';<br>
                    <br>
                    // 调用创建订单函数<br>
                    $result = create_payment_order(<br>
                    &nbsp;&nbsp;'alipay',       // 支付方式<br>
                    &nbsp;&nbsp;'测试商品',     // 商品名称<br>
                    &nbsp;&nbsp;0.01,          // 支付金额<br>
                    &nbsp;&nbsp;'ORDER'.time()  // 订单号（可选）<br>
                    );<br>
                    <br>
                    // 处理返回结果<br>
                    if ($result['code'] == 1) {<br>
                    &nbsp;&nbsp;// 获取支付二维码和H5链接<br>
                    &nbsp;&nbsp;$qrcode = $result['qrcode'];<br>
                    &nbsp;&nbsp;$h5_url = $result['h5_qrurl'];<br>
                    &nbsp;&nbsp;// 自定义显示支付页面...<br>
                    }
                </div>
            </div>
            
            <div class="col-md-6">
                <?php if ($result): ?>
                <h2 class="mt-4 mb-3">支付结果</h2>
                
                <?php if (isset($result['code']) && $result['code'] == 1): ?>
                <div class="alert alert-success">
                    <strong>订单创建成功！</strong> 请使用
                    <?php if ($type == 'alipay'): ?>
                    <img src="https://www.alipay.com/favicon.ico" alt="支付宝" class="payment-type-icon">支付宝
                    <?php elseif ($type == 'wxpay'): ?>
                    <img src="https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico" alt="微信支付" class="payment-type-icon">微信
                    <?php elseif ($type == 'qqpay'): ?>
                    <img src="https://qzonestyle.gtimg.cn/qzone/qzact/act/external/tiqq/logo.png" alt="QQ钱包" class="payment-type-icon">QQ钱包
                    <?php endif; ?>
                    扫描下方二维码完成支付。
                </div>
                
                <div class="card mb-4">
                    <div class="card-body">
                        <h5 class="card-title">订单信息</h5>
                        <p class="card-text">商品名称：<?php echo htmlspecialchars($name); ?></p>
                        <p class="card-text">支付金额：<strong class="text-danger"><?php echo number_format($money, 2); ?></strong> 元</p>
                        <p class="card-text">订单号：<?php echo htmlspecialchars($result['out_trade_no'] ?? ''); ?></p>
                        
                        <div id="qrcode-container">
                            <?php if (isset($result['qrcode'])): ?>
                            <img src="https://minico.qq.com/qrcode/get?type=2&r=2&size=250&text=<?php echo urlencode($result['qrcode']); ?>" alt="支付二维码">
                            <p class="mt-2">请使用
                                <?php if ($type == 'alipay'): ?>
                                支付宝
                                <?php elseif ($type == 'wxpay'): ?>
                                微信
                                <?php elseif ($type == 'qqpay'): ?>
                                QQ钱包
                                <?php endif; ?>
                                扫描二维码支付
                            </p>
                            <?php endif; ?>
                        </div>
                        
                        <?php if (isset($result['h5_qrurl'])): ?>
                        <div class="text-center mt-3">
                            <a href="<?php echo htmlspecialchars($result['h5_qrurl']); ?>" class="btn btn-primary" target="_blank">打开H5支付页面</a>
                        </div>
                        <?php endif; ?>
                    </div>
                </div>
                
                <div class="payment-result">
                    <h5>API返回结果：</h5>
                    <pre><?php print_r($result); ?></pre>
                </div>
                
                <?php else: ?>
                <div class="alert alert-danger">
                    <strong>订单创建失败！</strong> <?php echo htmlspecialchars($result['msg'] ?? '未知错误'); ?>
                </div>
                <?php endif; ?>
                
                <?php endif; ?>
                
                <h3 class="mt-4">查询订单状态</h3>
                <div class="code-block">
                    // 查询订单状态<br>
                    $order_status = query_order_status('订单号');<br>
                    <br>
                    if ($order_status['code'] == 1) {<br>
                    &nbsp;&nbsp;if ($order_status['status'] == 1) {<br>
                    &nbsp;&nbsp;&nbsp;&nbsp;echo '订单已支付';<br>
                    &nbsp;&nbsp;} else {<br>
                    &nbsp;&nbsp;&nbsp;&nbsp;echo '订单未支付';<br>
                    &nbsp;&nbsp;}<br>
                    }
                </div>
                
                <h3 class="mt-4">验证支付通知</h3>
                <div class="code-block">
                    // 验证异步通知<br>
                    $notify_result = validate_payment_notify($_POST);<br>
                    <br>
                    if ($notify_result['verified']) {<br>
                    &nbsp;&nbsp;// 支付成功，更新订单状态<br>
                    &nbsp;&nbsp;$order_no = $notify_result['out_trade_no'];<br>
                    &nbsp;&nbsp;$trade_no = $notify_result['trade_no'];<br>
                    &nbsp;&nbsp;$money = $notify_result['money'];<br>
                    &nbsp;&nbsp;<br>
                    &nbsp;&nbsp;// 处理业务逻辑...<br>
                    &nbsp;&nbsp;<br>
                    &nbsp;&nbsp;// 返回成功<br>
                    &nbsp;&nbsp;echo 'success';<br>
                    }
                </div>
            </div>
        </div>
        
        <div class="alert alert-warning mt-4">
            <strong>注意：</strong> 本演示仅用于测试，实际支付请使用您自己的商户信息。支付成功后，平台会通过 notify.php 和 return.php 通知支付结果。
        </div>
        
        <div class="text-center mt-4">
            <a href="demo.php" class="btn btn-secondary">返回演示首页</a>
        </div>
    </div>
    
    <footer class="text-center py-4 text-muted">
        <p>平安夜支付中转演示 &copy; <?php echo date('Y'); ?></p>
    </footer>
    
    <script src="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body>
</html> 