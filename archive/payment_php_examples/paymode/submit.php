<?php
/**
 * 平安夜支付中转文件
 * 
 * 该文件用于快速集成平安夜支付功能，不需要跳转到支付平台即可完成付款。
 * 
 * 特点：
 * 1. 独立单文件集成，无需额外依赖
 * 2. 自适应PC端和移动端
 * 3. 支持支付宝、微信支付、QQ钱包等多种支付方式
 * 4. 内置回调验证功能
 * 5. 美观的支付界面
 * 
 * @author 平安夜支付
 * @version 1.0.0
 * @date 2025-03-04
 */

// ======== 基础配置（用户可修改）======== //

/**
 * 中转支付配置
 */
$config = [
    // API基础URL (正式环境)，可选择多个节点
    'api_url' => 'https://pro.qjpay.icu',  // 主节点
    // 'api_url' => 'https://pro1.qjpay.icu', // 备用节点1
    // 'api_url' => 'https://pro2.qjpay.icu', // 备用节点2
    // 'api_url' => 'https://pro3.qjpay.icu', // 备用节点3
    
    // 商户信息 - 必须修改为您自己的商户信息
    'merchant' => [
        'pid' => '1000', // 商户ID，请替换为您的实际商户ID
        'key' => '换成你自己的', // 商户密钥，请替换为您的实际商户密钥
    ],
    
    // 支付回调配置 - 必须修改为您自己的回调地址
    'callback' => [
        // 异步通知地址，服务器通知，不能带参数，换成你实际的，这里只是演示文件
        'notify_url' => 'http://' . $_SERVER['HTTP_HOST'] . '/notify.php',
        
        // 同步跳转地址，支付成功后跳转，可带参数，换成你实际的，这里只是演示文件
        'return_url' => 'http://' . $_SERVER['HTTP_HOST'] . '/return.php',
    ],
    
    // 网站名称 - 显示在支付页面
    'site_name' => '我的网站',
    
    // 支付超时时间（秒）
    'timeout' => 300,
    
    // 调试模式（开启后显示错误信息）
    'debug' => true,
    
    // 支付成功后是否自动关闭页面（仅适用于在iframe或弹窗中打开的情况）
    'auto_close' => false,

    // 支持的支付方式
    'pay_types' => [
        'alipay' => '支付宝',
        'wxpay' => '微信支付',
        'qqpay' => 'QQ钱包'
    ],
];

// ======== 功能实现（无需修改）======== //

// 设置时区
date_default_timezone_set('Asia/Shanghai');

// 设置错误显示
if ($config['debug']) {
    ini_set('display_errors', 'On');
    error_reporting(E_ALL);
} else {
    ini_set('display_errors', 'Off');
    error_reporting(0);
}

// 设置时区
date_default_timezone_set('Asia/Shanghai');

/**
 * 生成随机字符串
 * 
 * @param int $length 字符串长度
 * @return string 随机字符串
 */
function random_string($length = 32) {
    $chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    $result = '';
    $max = strlen($chars) - 1;
    for ($i = 0; $i < $length; $i++) {
        $result .= $chars[mt_rand(0, $max)];
    }
    return $result;
}

/**
 * 生成商户订单号
 * 
 * @param string $prefix 订单号前缀
 * @return string 商户订单号
 */
function generate_order_no($prefix = '') {
    return $prefix . date('YmdHis') . substr(microtime(), 2, 4) . random_string(8);
}

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
 * 发送HTTP POST请求
 * 
 * @param string $url 请求URL
 * @param array $params 请求参数
 * @param int $timeout 超时时间（秒）
 * @return string 响应内容
 */
function http_post($url, $params = [], $timeout = 30) {
    // 初始化curl
    $ch = curl_init();
    
    // 设置请求URL
    curl_setopt($ch, CURLOPT_URL, $url);
    
    // 设置为POST请求
    curl_setopt($ch, CURLOPT_POST, true);
    
    // 设置POST数据
    curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($params));
    
    // 设置返回结果为字符串而不是直接输出
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    // 设置超时时间
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    
    // 设置SSL验证
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
    curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);
    
    // 设置请求头
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/x-www-form-urlencoded',
        'User-Agent: Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; Trident/6.0)'
    ]);
    
    // 执行请求
    $response = curl_exec($ch);
    
    // 检查是否有错误
    if (curl_errno($ch)) {
        $error = curl_error($ch);
        curl_close($ch);
        return json_encode(['code' => 0, 'msg' => 'CURL错误: ' . $error]);
    }
    
    // 关闭curl
    curl_close($ch);
    
    // 返回响应结果
    return $response;
}

/**
 * 获取客户端设备类型
 * 
 * @return string 设备类型，mobile 或 pc
 */
function get_device_type() {
    $agent = isset($_SERVER['HTTP_USER_AGENT']) ? strtolower($_SERVER['HTTP_USER_AGENT']) : '';
    $is_mobile = false;
    
    // 检测手机设备
    if (strpos($agent, 'mobile') !== false || strpos($agent, 'android') !== false || strpos($agent, 'iphone') !== false || strpos($agent, 'ipad') !== false || strpos($agent, 'ipod') !== false) {
        $is_mobile = true;
    }
    
    return $is_mobile ? 'mobile' : 'pc';
}

/**
 * 创建支付订单
 * 
 * @param string $type 支付方式
 * @param string $name 商品名称
 * @param float $money 支付金额
 * @param string $order_no 订单号（可选）
 * @return array 订单结果
 */
function create_payment_order($type, $name, $money, $order_no = '') {
    global $config;
    
    // 验证支付方式
    $valid_types = ['alipay', 'wxpay', 'qqpay'];
    if (!in_array($type, $valid_types)) {
        return ['code' => 0, 'msg' => '不支持的支付方式'];
    }
    
    // 验证金额
    if ($money <= 0) {
        return ['code' => 0, 'msg' => '支付金额必须大于0'];
    }
    
    // 生成订单号
    if (empty($order_no)) {
        $order_no = generate_order_no();
    }
    
    // 构建请求参数
    $params = [
        'pid' => $config['merchant']['pid'],
        'type' => $type,
        'out_trade_no' => $order_no,
        'notify_url' => $config['callback']['notify_url'],
        'return_url' => $config['callback']['return_url'],
        'name' => $name,
        'money' => number_format($money, 2, '.', ''),
        'sign_type' => 'MD5'
    ];
    
    // 生成签名
    $params['sign'] = create_sign($params, $config['merchant']['key']);
    
    if ($config['debug']) {
        error_log("请求参数：" . print_r($params, true));
    }
    
    // 发送请求
    $api_url = rtrim($config['api_url'], '/') . '/mapi.php';
    $response = http_post($api_url, $params);
    
    if ($config['debug']) {
        error_log("API响应：" . print_r($response, true));
    }
    
    // 解析响应
    $result = json_decode($response, true);
    
    if ($config['debug']) {
        error_log("解析结果：" . print_r($result, true));
    }
    
    // 检查响应是否有效
    if (!is_array($result)) {
        return ['code' => 0, 'msg' => '服务器响应异常: ' . $response, 'out_trade_no' => $order_no];
    }
    
    // 如果API返回成功
    if (isset($result['code']) && $result['code'] == 1) {
        // 添加订单号到结果中
        $result['out_trade_no'] = $order_no;
        return $result;
    }
    
    // 返回错误信息
    return [
        'code' => 0,
        'msg' => isset($result['msg']) ? $result['msg'] : '创建订单失败',
        'out_trade_no' => $order_no
    ];
}

/**
 * 查询订单状态
 * 
 * @param string $order_no 订单号
 * @return array 查询结果
 */
function query_order_status($order_no) {
    global $config;
    
    if (empty($order_no)) {
        return ['code' => 0, 'msg' => '订单号不能为空'];
    }
    
    // 构建请求参数
    $params = [
        'apiid' => $config['merchant']['pid'],
        'apikey' => $config['merchant']['key'],
        'out_trade_no' => $order_no
    ];
    
    // 发送请求
    $api_url = rtrim($config['api_url'], '/') . '/qjt.php?act=query_order';
    $response = http_post($api_url, $params);
    
    // 解析响应
    $result = json_decode($response, true);
    
    // 检查响应是否有效
    if (!is_array($result)) {
        return ['code' => 0, 'msg' => '服务器响应异常: ' . $response];
    }
    
    // 返回查询结果
    return $result;
}

/**
 * 验证支付通知
 * 
 * @param array $params 通知参数
 * @return array 验证结果
 */
function validate_payment_notify($params) {
    global $config;
    
    // 验证必要参数
    $required_params = ['trade_no', 'out_trade_no', 'type', 'money', 'trade_status', 'sign'];
    foreach ($required_params as $param) {
        if (!isset($params[$param]) || $params[$param] === '') {
            return ['verified' => false, 'msg' => '缺少必要参数: ' . $param];
        }
    }
    
    // 验证签名
    if (!verify_sign($params, $config['merchant']['key'])) {
        return ['verified' => false, 'msg' => '签名验证失败'];
    }
    
    // 验证支付状态
    if ($params['trade_status'] !== 'TRADE_SUCCESS') {
        return ['verified' => false, 'msg' => '支付未成功，状态: ' . $params['trade_status']];
    }
    
    // 返回验证成功结果
    return [
        'verified' => true,
        'trade_no' => $params['trade_no'],
        'out_trade_no' => $params['out_trade_no'],
        'type' => $params['type'],
        'money' => $params['money'],
        'trade_status' => $params['trade_status']
    ];
}

// ======== 主要处理逻辑 ======== //

// 初始化变量
$error_msg = '';
$success_msg = '';
$pay_result = null;
$order_info = null;
$out_trade_no = '';
$device_type = get_device_type();

// ======== 处理请求参数 ======== //

// 获取请求参数（同时支持GET和POST）
$request_data = array_merge($_GET, $_POST);

// 支付参数
$type = isset($request_data['type']) ? trim($request_data['type']) : '';
$name = isset($request_data['name']) ? trim($request_data['name']) : '';
$money = isset($request_data['money']) ? floatval($request_data['money']) : 0;
$out_trade_no = isset($request_data['out_trade_no']) ? trim($request_data['out_trade_no']) : '';

// 验证必填参数
$errors = [];
if (empty($name)) {
    $errors[] = '商品名称不能为空';
}
if ($money <= 0) {
    $errors[] = '支付金额必须大于0';
}
if (!empty($type) && !isset($config['pay_types'][$type])) {
    $errors[] = '不支持的支付方式：' . $type;
}

// 如果是API请求（通过AJAX或其他方式）
$is_api_request = isset($request_data['is_api']) || (isset($_SERVER['HTTP_X_REQUESTED_WITH']) && strtolower($_SERVER['HTTP_X_REQUESTED_WITH']) == 'xmlhttprequest');

// 如果是直接函数调用，不处理请求
if (count(get_included_files()) > 1 && !isset($GLOBALS['_is_submit_entry'])) {
    $GLOBALS['_is_submit_entry'] = true;
    return;
}

// 处理订单状态查询请求
if (isset($request_data['check_order']) && !empty($request_data['out_trade_no'])) {
    $order_status = query_order_status($request_data['out_trade_no']);
    header('Content-Type: application/json');
    echo json_encode($order_status);
    exit;
}

// 如果有错误且是API请求，返回JSON错误信息
if (!empty($errors) && $is_api_request) {
    header('Content-Type: application/json');
    echo json_encode(['code' => 0, 'msg' => implode(', ', $errors)]);
    exit;
}

// 如果没有提供支付方式，但其他参数都有，显示支付方式选择页面
if (empty($type) && !empty($name) && $money > 0) {
    // 显示支付方式选择页面
    $show_payment_selection = true;
} else if (!empty($type) && !empty($name) && $money > 0) {
    // 如果所有参数都满足，创建订单并显示支付页面
    $result = create_payment_order($type, $name, $money, $out_trade_no);
    
    // 如果是API请求，直接返回JSON结果
    if ($is_api_request) {
        header('Content-Type: application/json');
        echo json_encode($result);
        exit;
    }
    
    // 否则显示支付页面
    $order_data = $result;
    $show_payment_selection = false;
} else if ($is_api_request) {
    // API请求但参数不完整
    header('Content-Type: application/json');
    echo json_encode(['code' => 0, 'msg' => '参数不完整']);
    exit;
} else {
    // 参数不完整，显示错误信息
    $error_msg = '参数不完整，请提供商品名称和支付金额';
    $show_payment_selection = false;
}

// 如果是直接访问且没有提交参数，显示表单页面
if (empty($name) && $money <= 0 && !$is_api_request) {
    // 显示表单页面
    include_once 'demo.php';
    exit;
}

// 设置页面编码
header('Content-Type: text/html; charset=UTF-8');
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo htmlspecialchars($name); ?> - 支付</title>
    <link href="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: #f8f9fa;
            padding-top: 2rem;
        }
        .payment-container {
            max-width: 800px;
            margin: 0 auto;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 15px rgba(0,0,0,0.1);
            padding: 2rem;
        }
        .payment-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .payment-amount {
            font-size: 2rem;
            color: #f60;
            font-weight: bold;
        }
        .payment-info {
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1.5rem;
        }
        .qrcode-container {
            text-align: center;
            margin: 2rem 0;
        }
        .qrcode-container img {
            max-width: 200px;
            margin: 0 auto;
        }
        .payment-footer {
            text-align: center;
            margin-top: 2rem;
            color: #6c757d;
        }
        .countdown {
            font-size: 1.2rem;
            color: #dc3545;
            font-weight: bold;
        }
        .payment-type-icon {
            width: 32px;
            height: 32px;
            margin-right: 8px;
        }
        .payment-method-card {
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            transition: all 0.3s ease;
            text-align: center;
            cursor: pointer;
        }
        .payment-method-card:hover {
            border-color: #007bff;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .payment-method-icon {
            width: 48px;
            height: 48px;
            margin-bottom: 1rem;
        }
        @media (max-width: 576px) {
            .payment-container {
                padding: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="container payment-container">
        <?php if (isset($show_payment_selection) && $show_payment_selection): ?>
        <!-- 支付方式选择页面 -->
        <div class="payment-header">
            <h1>选择支付方式</h1>
            <div class="payment-amount">￥<?php echo number_format($money, 2); ?></div>
            <p class="text-muted">商品：<?php echo htmlspecialchars($name); ?></p>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-4 mb-3">
                <a href="submit.php?type=alipay&name=<?php echo urlencode($name); ?>&money=<?php echo $money; ?><?php echo !empty($out_trade_no) ? '&out_trade_no='.urlencode($out_trade_no) : ''; ?>" class="text-decoration-none">
                    <div class="payment-method-card">
                        <img src="https://www.alipay.com/favicon.ico" alt="支付宝" class="payment-method-icon">
                        <h5>支付宝支付</h5>
                        <p class="text-muted mb-0">推荐有支付宝的用户使用</p>
                    </div>
                </a>
            </div>
            
            <div class="col-md-4 mb-3">
                <a href="submit.php?type=wxpay&name=<?php echo urlencode($name); ?>&money=<?php echo $money; ?><?php echo !empty($out_trade_no) ? '&out_trade_no='.urlencode($out_trade_no) : ''; ?>" class="text-decoration-none">
                    <div class="payment-method-card">
                        <img src="https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico" alt="微信支付" class="payment-method-icon">
                        <h5>微信支付</h5>
                        <p class="text-muted mb-0">推荐有微信的用户使用</p>
                    </div>
                </a>
            </div>
            
            <div class="col-md-4 mb-3">
                <a href="submit.php?type=qqpay&name=<?php echo urlencode($name); ?>&money=<?php echo $money; ?><?php echo !empty($out_trade_no) ? '&out_trade_no='.urlencode($out_trade_no) : ''; ?>" class="text-decoration-none">
                    <div class="payment-method-card">
                        <img src="https://qzonestyle.gtimg.cn/qzone/qzact/act/external/tiqq/logo.png" alt="QQ钱包" class="payment-method-icon">
                        <h5>QQ钱包支付</h5>
                        <p class="text-muted mb-0">推荐有QQ的用户使用</p>
                    </div>
                </a>
            </div>
        </div>
        
        <div class="payment-footer">
            <p>请选择一种支付方式完成付款</p>
            <p>如有问题，请联系客服</p>
        </div>
        
        <?php elseif (isset($order_data) && isset($order_data['code']) && $order_data['code'] == 1): ?>
        <!-- 支付页面 -->
        <div class="payment-header">
            <h1>
                <?php if ($type == 'alipay'): ?>
                <img src="https://www.alipay.com/favicon.ico" alt="支付宝" class="payment-type-icon">支付宝支付
                <?php elseif ($type == 'wxpay'): ?>
                <img src="https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico" alt="微信支付" class="payment-type-icon">微信支付
                <?php elseif ($type == 'qqpay'): ?>
                <img src="https://qzonestyle.gtimg.cn/qzone/qzact/act/external/tiqq/logo.png" alt="QQ钱包" class="payment-type-icon">QQ钱包支付
                <?php endif; ?>
            </h1>
            <div class="payment-amount">￥<?php echo number_format($money, 2); ?></div>
            <p class="text-muted">订单号：<?php echo htmlspecialchars($order_data['out_trade_no'] ?? $out_trade_no); ?></p>
        </div>
        
        <div class="payment-info">
            <div class="row">
                <div class="col-4">商品名称：</div>
                <div class="col-8"><?php echo htmlspecialchars($name); ?></div>
            </div>
            <div class="row mt-2">
                <div class="col-4">支付方式：</div>
                <div class="col-8">
                    <?php if ($type == 'alipay'): ?>
                    支付宝
                    <?php elseif ($type == 'wxpay'): ?>
                    微信支付
                    <?php elseif ($type == 'qqpay'): ?>
                    QQ钱包
                    <?php endif; ?>
                </div>
            </div>
            <div class="row mt-2">
                <div class="col-4">创建时间：</div>
                <div class="col-8"><?php echo date('Y-m-d H:i:s'); ?></div>
            </div>
        </div>
        
        <div class="qrcode-container">
            <?php if (isset($order_data['qrcode'])): ?>
            <img src="https://minico.qq.com/qrcode/get?type=2&r=2&size=250&text=<?php echo urlencode($order_data['qrcode']); ?>" alt="支付二维码">
            <p class="mt-2">请使用
                <?php if ($type == 'alipay'): ?>
                支付宝
                <?php elseif ($type == 'wxpay'): ?>
                微信
                <?php elseif ($type == 'qqpay'): ?>
                QQ钱包
                <?php endif; ?>
            扫描二维码完成支付</p>
            
            <div class="mt-3">
                <p>支付倒计时：<span id="countdown" class="countdown">05:00</span></p>
            </div>
            
            <?php if (isset($order_data['h5_qrurl'])): ?>
            <div class="mt-3">
                <a href="<?php echo htmlspecialchars($order_data['h5_qrurl']); ?>" class="btn btn-primary" target="_blank">打开H5支付页面</a>
            </div>
            <?php endif; ?>
            <?php else: ?>
            <div class="alert alert-danger">
                获取支付二维码失败，请重试或联系客服。
            </div>
            <?php endif; ?>
        </div>
        
        <div class="payment-footer">
            <p>订单创建成功后，请在5分钟内完成支付</p>
            <p>如有问题，请联系客服</p>
        </div>
        
        <script>
            // 倒计时功能
            function startCountdown(minutes) {
                var seconds = minutes * 60;
                var countdownElement = document.getElementById('countdown');
                
                var timer = setInterval(function() {
                    seconds--;
                    
                    if (seconds <= 0) {
                        clearInterval(timer);
                        countdownElement.textContent = "已超时";
                        alert("支付已超时，请重新发起支付");
                        window.location.href = "demo.php";
                        return;
                    }
                    
                    var minutesLeft = Math.floor(seconds / 60);
                    var secondsLeft = seconds % 60;
                    
                    countdownElement.textContent = 
                        (minutesLeft < 10 ? "0" + minutesLeft : minutesLeft) + ":" + 
                        (secondsLeft < 10 ? "0" + secondsLeft : secondsLeft);
                }, 1000);
            }
            
            // 检查订单状态
            function checkOrderStatus() {
                var orderNo = "<?php echo htmlspecialchars($order_data['out_trade_no'] ?? $out_trade_no); ?>";
                
                if (!orderNo) return;
                
                var xhr = new XMLHttpRequest();
                xhr.open("POST", "submit.php", true);
                xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
                xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
                
                xhr.onreadystatechange = function() {
                    if (xhr.readyState === 4 && xhr.status === 200) {
                        try {
                            var response = JSON.parse(xhr.responseText);
                            
                            if (response && response.code === 1 && response.status === 1) {
                                // 支付成功，跳转到同步通知页面
                                window.location.href = "<?php echo $config['callback']['return_url']; ?>?trade_no=" + (response.trade_no || '') + "&out_trade_no=" + orderNo + "&type=<?php echo $type; ?>&money=<?php echo $money; ?>";
                            }
                        } catch (e) {
                            console.error("解析响应失败", e);
                        }
                    }
                };
                
                xhr.send("check_order=1&out_trade_no=" + orderNo);
            }
            
            // 启动倒计时
            startCountdown(5);
            
            // 定时检查订单状态
            setInterval(checkOrderStatus, 3000);
        </script>
        
        <?php else: ?>
        <!-- 错误信息 -->
        <div class="payment-header">
            <h1>支付失败</h1>
        </div>
        
        <div class="alert alert-danger">
            <?php echo isset($order_data['msg']) ? htmlspecialchars($order_data['msg']) : (isset($error_msg) ? htmlspecialchars($error_msg) : '创建订单失败，请重试'); ?>
        </div>
        
        <div class="text-center mt-4">
            <a href="demo.php" class="btn btn-primary">返回重试</a>
        </div>
        <?php endif; ?>
    </div>
    
    <script src="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body>
</html> 