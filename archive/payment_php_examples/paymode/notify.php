<?php
/**
 * 平安夜支付接口 - 异步通知处理示例
 * 
 * 本文件用于接收支付成功后的异步通知
 * 支付平台会向该地址发送POST请求，通知支付结果
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

// 订单处理成功后的操作
// 在这里编写您的业务逻辑，例如更新订单状态、发货等
function process_order($order_data) {
    // 示例：记录订单信息到文件
    $log_dir = __DIR__ . '/logs/';
    $log_file = $log_dir . date('Y-m-d') . '_success_orders.log';
    $log_content = "【" . date('Y-m-d H:i:s') . "】订单处理成功：" . json_encode($order_data, JSON_UNESCAPED_UNICODE) . PHP_EOL;
    file_put_contents($log_file, $log_content, FILE_APPEND);
    
    // TODO: 在这里添加您的业务逻辑
    // 例如：更新数据库中的订单状态
    // 例如：给用户增加会员权限
    // 例如：发送通知邮件
    
    return true;
}

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

// 获取通知参数
$notify_params = $_POST;

// 记录原始通知数据
$log_file = $log_dir . date('Y-m-d') . '_notify.log';
file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】收到通知：" . json_encode($notify_params, JSON_UNESCAPED_UNICODE) . PHP_EOL, FILE_APPEND);

// 验证通知参数
if (empty($notify_params)) {
    exit('error: empty notify params');
}

// 验证签名
if (!verify_sign($notify_params, $merchant_key)) {
    file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】签名验证失败" . PHP_EOL, FILE_APPEND);
    exit('error: sign verify fail');
}

// 验证交易状态
if (!isset($notify_params['trade_status']) || $notify_params['trade_status'] !== 'TRADE_SUCCESS') {
    file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】交易状态不正确：" . ($notify_params['trade_status'] ?? 'unknown') . PHP_EOL, FILE_APPEND);
    exit('error: trade status not success');
}

// 获取订单信息
$order_data = [
    'trade_no' => $notify_params['trade_no'] ?? '',           // 平台订单号
    'out_trade_no' => $notify_params['out_trade_no'] ?? '',   // 商户订单号
    'type' => $notify_params['type'] ?? '',                   // 支付方式
    'money' => $notify_params['money'] ?? 0,                  // 支付金额
    'trade_status' => $notify_params['trade_status'] ?? '',   // 交易状态
    'notify_time' => date('Y-m-d H:i:s')                      // 通知时间
];

// 处理订单
if (process_order($order_data)) {
    file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】订单处理成功：" . $order_data['out_trade_no'] . PHP_EOL, FILE_APPEND);
    echo 'success'; // 向平台返回成功，平台将不再重复通知
} else {
    file_put_contents($log_file, "【" . date('Y-m-d H:i:s') . "】订单处理失败：" . $order_data['out_trade_no'] . PHP_EOL, FILE_APPEND);
    exit('error: process order fail');
}

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