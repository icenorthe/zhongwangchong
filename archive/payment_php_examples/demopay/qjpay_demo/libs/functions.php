<?php
/**
 * 平安夜支付接口公共函数库
 * 
 * 本文件包含平安夜支付接口所需的各种工具函数
 * 包括签名算法、HTTP请求、日志记录等功能
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

/**
 * 获取配置
 * 
 * 如果存在会话中的临时配置，优先使用临时配置
 * 
 * @return array 配置数组
 */
function get_config() {
    static $config = null;
    
    if ($config === null) {
        // 加载基础配置
        $config = require dirname(__DIR__) . '/config.php';
        
        // 检查是否有临时配置
        if (session_status() === PHP_SESSION_NONE) {
            session_start();
        }
        
        if (isset($_SESSION['temp_config']) && is_array($_SESSION['temp_config'])) {
            $temp_config = $_SESSION['temp_config'];
            
            // 应用临时商户ID
            if (!empty($temp_config['merchant_id'])) {
                $config['merchant']['pid'] = $temp_config['merchant_id'];
            }
            
            // 应用临时商户密钥
            if (!empty($temp_config['merchant_key'])) {
                $config['merchant']['key'] = $temp_config['merchant_key'];
            }
        }
    }
    
    return $config;
}

/**
 * 记录日志
 * 
 * @param string $message 日志内容
 * @param string $level 日志级别 (info, warning, error)
 * @param array $context 上下文数据
 * @return bool 是否记录成功
 */
function write_log($message, $level = 'info', $context = []) {
    $config = get_config();
    
    // 检查是否启用日志
    if (!$config['log']['enabled']) {
        return false;
    }
    
    // 创建日志目录（如果不存在）
    $log_dir = $config['log']['path'];
    if (!is_dir($log_dir) && !mkdir($log_dir, 0755, true)) {
        return false;
    }
    
    // 生成日志文件名 (按日期分割)
    $log_file = $log_dir . date('Y-m-d') . '.log';
    
    // 格式化日志内容
    $log_content = '[' . date('Y-m-d H:i:s') . '] [' . strtoupper($level) . '] ' . $message;
    
    // 如果有上下文数据，添加到日志中
    if (!empty($context)) {
        $log_content .= ' - ' . json_encode($context, JSON_UNESCAPED_UNICODE);
    }
    
    $log_content .= PHP_EOL;
    
    // 写入日志文件
    return file_put_contents($log_file, $log_content, FILE_APPEND | LOCK_EX) !== false;
}

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
 * 数组转URL参数格式
 * 
 * @param array $array 需要转换的数组
 * @return string URL参数格式的字符串
 */
function array_to_url_params($array) {
    $params = [];
    foreach ($array as $key => $value) {
        $params[] = $key . '=' . $value;
    }
    return implode('&', $params);
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
 * @return string MD5签名
 */
function create_sign($params) {
    $config = get_config();
    
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
    
    // 4. 直接拼接商户密钥（不带&key=前缀）
    $signstr .= $config['merchant']['key'];
    
    // 5. MD5加密
    return md5($signstr);
}

/**
 * 验证签名
 * 
 * @param array $params 需要验证的参数数组（包含sign参数）
 * @return bool 签名是否正确
 */
function verify_sign($params) {
    // 获取参数中的签名
    $sign = isset($params['sign']) ? $params['sign'] : '';
    
    if (empty($sign)) {
        return false;
    }
    
    // 生成签名
    $calculated_sign = create_sign($params);
    
    // 比较签名
    return $calculated_sign === $sign;
}

/**
 * 发送HTTP POST请求
 * 
 * @param string $url 请求URL
 * @param array $params 请求参数
 * @param int $timeout 超时时间（秒）
 * @return array|bool 成功返回响应数组，失败返回false
 */
function http_post($url, $params = [], $timeout = 30) {
    // 记录请求日志
    write_log('HTTP POST请求', 'info', [
        'url' => $url,
        'params' => $params
    ]);
    
    // 初始化curl
    $ch = curl_init();
    
    // 设置curl选项
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($params));
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
    curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);
    
    // 执行请求
    $response = curl_exec($ch);
    $error = curl_error($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    
    // 关闭curl
    curl_close($ch);
    
    // 检查是否有错误
    if ($error) {
        write_log('HTTP请求失败', 'error', [
            'url' => $url,
            'error' => $error
        ]);
        return false;
    }
    
    // 检查HTTP状态码
    if ($http_code != 200) {
        write_log('HTTP请求返回错误状态码', 'error', [
            'url' => $url,
            'http_code' => $http_code,
            'response' => $response
        ]);
        return false;
    }
    
    // 尝试将响应解析为JSON
    $result = json_decode($response, true);
    
    // 记录响应日志
    write_log('HTTP请求成功', 'info', [
        'url' => $url,
        'response' => $result ?: $response
    ]);
    
    return $result ?: $response;
}

/**
 * 显示API错误信息
 * 
 * @param string $message 错误信息
 * @param int $code 错误代码
 * @return void
 */
function show_error($message, $code = 0) {
    // 记录错误日志
    write_log($message, 'error', ['code' => $code]);
    
    // 输出错误信息
    $response = [
        'code' => $code,
        'msg' => $message,
    ];
    
    header('Content-Type: application/json');
    echo json_encode($response, JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * 显示API成功信息
 * 
 * @param array $data 返回数据
 * @param string $message 成功信息
 * @return void
 */
function show_success($data = [], $message = '操作成功') {
    // 记录成功日志
    write_log($message, 'info', $data);
    
    // 输出成功信息
    $response = [
        'code' => 1,
        'msg' => $message,
        'data' => $data,
    ];
    
    header('Content-Type: application/json');
    echo json_encode($response, JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * 获取客户端IP地址
 * 
 * @return string IP地址
 */
function get_client_ip() {
    if (isset($_SERVER['HTTP_X_FORWARDED_FOR']) && $_SERVER['HTTP_X_FORWARDED_FOR']) {
        $ip = $_SERVER['HTTP_X_FORWARDED_FOR'];
    } elseif (isset($_SERVER['HTTP_CLIENT_IP']) && $_SERVER['HTTP_CLIENT_IP']) {
        $ip = $_SERVER['HTTP_CLIENT_IP'];
    } elseif (isset($_SERVER['REMOTE_ADDR']) && $_SERVER['REMOTE_ADDR']) {
        $ip = $_SERVER['REMOTE_ADDR'];
    } else {
        $ip = '0.0.0.0';
    }
    return $ip;
} 