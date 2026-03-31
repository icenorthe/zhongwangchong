<?php
/**
 * 平安夜支付接口 - 同步跳转处理示例
 * 
 * 本文件用于处理支付完成后的页面跳转
 * 用户支付完成后会被跳转到此页面
 * 
 * @author 平安夜支付
 * @version 1.0.0
 * @date 2025-03-04
 */

// 设置时区
date_default_timezone_set('Asia/Shanghai');

// ===========================================
// 以下是您需要替换的配置信息
// ===========================================

// 商户密钥，必须与submit.php中的配置一致
$merchant_key = '您的商户密钥';

// 是否开启调试模式
$debug = true;

// 网站名称
$site_name = '您的网站名称';

// 网站首页URL
$home_url = 'http://您的域名/';

// ===========================================
// 以下代码无需修改
// ===========================================

// 设置错误显示
if ($debug) {
    ini_set('display_errors', 'On');
    error_reporting(E_ALL);
} else {
    ini_set('display_errors', 'Off');
    error_reporting(0);
}

// 设置日志目录
$log_dir = __DIR__ . '/logs/';
if (!is_dir($log_dir)) {
    mkdir($log_dir, 0755, true);
}

// 记录跳转日志
$log_file = $log_dir . date('Y-m-d') . '_return.log';
file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】收到同步跳转：" . json_encode($_GET, JSON_UNESCAPED_UNICODE) . PHP_EOL, FILE_APPEND);

// 获取跳转参数
$return_params = $_GET;


// 初始化变量
$trade_no = isset($return_params['trade_no']) ? $return_params['trade_no'] : '';
$out_trade_no = isset($return_params['out_trade_no']) ? $return_params['out_trade_no'] : '';
$type = isset($return_params['type']) ? $return_params['type'] : '';
$money = isset($return_params['money']) ? $return_params['money'] : '0.00';
$sign_verified = false;

// 验证签名（如果有签名参数）
if (isset($return_params['sign'])) {
    $sign_verified = verify_sign($return_params, $merchant_key);
    file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】签名验证结果：" . ($sign_verified ? '成功' : '失败') . PHP_EOL, FILE_APPEND);
}

// 获取支付方式名称
$pay_type_name = '在线支付';
if ($type == 'alipay') {
    $pay_type_name = '支付宝';
    $pay_type_icon = 'https://www.alipay.com/favicon.ico';
} elseif ($type == 'wxpay') {
    $pay_type_name = '微信支付';
    $pay_type_icon = 'https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico';
} elseif ($type == 'qqpay') {
    $pay_type_name = 'QQ钱包';
    $pay_type_icon = 'https://qzonestyle.gtimg.cn/qzone/qzact/act/external/tiqq/logo.png';
}

// 设置页面编码
header('Content-Type: text/html; charset=UTF-8');
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>支付结果 - <?php echo htmlspecialchars($site_name); ?></title>
    <link href="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: #f8f9fa;
            padding-top: 2rem;
        }
        .result-container {
            max-width: 600px;
            margin: 0 auto;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 15px rgba(0,0,0,0.1);
            padding: 2rem;
            text-align: center;
        }
        .result-icon {
            font-size: 4rem;
            margin-bottom: 1rem;
        }
        .result-success {
            color: #28a745;
        }
        .result-warning {
            color: #ffc107;
        }
        .result-error {
            color: #dc3545;
        }
        .result-title {
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }
        .result-info {
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 1rem;
            margin: 1.5rem 0;
            text-align: left;
        }
        .payment-type-icon {
            width: 24px;
            height: 24px;
            margin-right: 8px;
            vertical-align: middle;
        }
        @media (max-width: 576px) {
            .result-container {
                padding: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="container result-container">
        <?php if (!empty($trade_no) && !empty($out_trade_no)): ?>
        <!-- 支付成功 -->
        <div class="result-icon result-success">✓</div>
        <h1 class="result-title">支付成功</h1>
        <p>您的订单已支付成功，感谢您的购买！</p>
        
        <div class="result-info">
            <div class="row mb-2">
                <div class="col-4">订单号：</div>
                <div class="col-8"><?php echo htmlspecialchars($out_trade_no); ?></div>
            </div>
            <div class="row mb-2">
                <div class="col-4">支付金额：</div>
                <div class="col-8">￥<?php echo htmlspecialchars($money); ?></div>
            </div>
            <div class="row mb-2">
                <div class="col-4">支付方式：</div>
                <div class="col-8">
                    <?php if (!empty($pay_type_icon)): ?>
                    <img src="<?php echo $pay_type_icon; ?>" alt="<?php echo htmlspecialchars($pay_type_name); ?>" class="payment-type-icon">
                    <?php endif; ?>
                    <?php echo htmlspecialchars($pay_type_name); ?>
                </div>
            </div>
            <div class="row mb-2">
                <div class="col-4">支付时间：</div>
                <div class="col-8"><?php echo date('Y-m-d H:i:s'); ?></div>
            </div>
        </div>
        
        <?php elseif (!empty($out_trade_no)): ?>
        <!-- 支付状态未知 -->
        <div class="result-icon result-warning">?</div>
        <h1 class="result-title">支付状态未知</h1>
        <p>我们无法确认您的支付状态，请稍后查看订单状态。</p>
        
        <div class="result-info">
            <div class="row mb-2">
                <div class="col-4">订单号：</div>
                <div class="col-8"><?php echo htmlspecialchars($out_trade_no); ?></div>
            </div>
            <?php if (!empty($money)): ?>
            <div class="row mb-2">
                <div class="col-4">支付金额：</div>
                <div class="col-8">￥<?php echo htmlspecialchars($money); ?></div>
            </div>
            <?php endif; ?>
            <?php if (!empty($type)): ?>
            <div class="row mb-2">
                <div class="col-4">支付方式：</div>
                <div class="col-8">
                    <?php if (!empty($pay_type_icon)): ?>
                    <img src="<?php echo $pay_type_icon; ?>" alt="<?php echo htmlspecialchars($pay_type_name); ?>" class="payment-type-icon">
                    <?php endif; ?>
                    <?php echo htmlspecialchars($pay_type_name); ?>
                </div>
            </div>
            <?php endif; ?>
        </div>
        
        <?php else: ?>
        <!-- 支付失败或参数错误 -->
        <div class="result-icon result-error">✗</div>
        <h1 class="result-title">支付失败</h1>
        <p>很抱歉，您的支付未完成或发生错误。</p>
        <?php endif; ?>
        
        <div class="mt-4">
            <a href="<?php echo htmlspecialchars($home_url); ?>" class="btn btn-primary">返回首页</a>
        </div>
    </div>
    
    <script src="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body>
</html>

<?php
// ===========================================
// 以下是辅助函数，与pay.php中的函数保持一致
// ===========================================

/**
 * 移除数组中的空值和签名参数
 * 
 * @param array $params 需要处理的参数数组
 * @return array 处理后的数组
 */
function para_filter($params) {
    $para_filter = [];
    foreach ($params as $key => $val) {
        if ($key == 'sign' || $key == 'sign_type' || $val === '') {
            continue;
        }
        $para_filter[$key] = $params[$key];
    }
    return $para_filter;
}

/**
 * 对数组按键名进行ASCII码从小到大排序
 * 
 * @param array $params 需要排序的数组
 * @return array 排序后的数组
 */
function arg_sort($params) {
    ksort($params);
    reset($params);
    return $params;
}

/**
 * 验证签名
 * 
 * @param array $params 需要验证的参数数组（包含sign参数）
 * @param string $key 商户密钥
 * @return bool 签名是否正确
 */
function verify_sign($params, $key) {
    // 获取参数中的签名
    $sign = isset($params['sign']) ? $params['sign'] : '';
    
    if (empty($sign)) {
        return false;
    }
    
    // 生成签名
    $calculated_sign = create_sign($params, $key);
    
    // 比较签名
    return $calculated_sign === $sign;
}

/**
 * 生成MD5签名
 * 
 * @param array $params 参数数组
 * @param string $key 商户密钥
 * @return string MD5签名
 */
function create_sign($params, $key) {
    // 1. 过滤掉空值和签名参数
    $filter_params = para_filter($params);
    
    // 2. 按照参数名ASCII码从小到大排序
    $sort_params = arg_sort($filter_params);
    
    // 3. 拼接成键值对字符串
    $signstr = '';
    foreach ($sort_params as $k => $v) {
        $signstr .= $k . '=' . $v . '&';
    }
    $signstr = substr($signstr, 0, -1);  // 去掉最后一个&符号
    
    // 4. 直接拼接商户密钥
    $signstr .= $key;
    
    // 5. MD5加密
    return md5($signstr);
} 