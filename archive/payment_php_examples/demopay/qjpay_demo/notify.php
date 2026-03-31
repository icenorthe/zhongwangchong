<?php
/**
 * QJPay支付接口 - 异步通知处理
 * 
 * 本文件用于接收支付成功后的异步通知
 * 支付平台会向该地址发送POST请求，通知支付结果
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入公共函数库
require_once __DIR__ . '/libs/functions.php';

// 记录通知信息
write_log('收到异步通知', 'info', $_POST);

// 获取通知参数
$params = $_POST;

// 验证通知参数
if (empty($params)) {
    // 记录错误
    write_log('异步通知参数为空', 'error');
    exit('fail');
}

// 验证必要参数
$required_params = ['trade_no', 'out_trade_no', 'type', 'money', 'trade_status', 'sign', 'sign_type'];
foreach ($required_params as $param) {
    if (!isset($params[$param]) || $params[$param] === '') {
        // 记录错误
        write_log('异步通知缺少必要参数: ' . $param, 'error', $params);
        exit('fail');
    }
}

// 验证签名
if (!verify_sign($params)) {
    // 记录错误
    write_log('异步通知签名验证失败', 'error', [
        'received' => $params['sign'],
        'calculated' => create_sign($params)
    ]);
    exit('fail');
}

// 验证支付状态
if ($params['trade_status'] !== 'TRADE_SUCCESS') {
    // 记录信息
    write_log('支付未成功，状态: ' . $params['trade_status'], 'info', $params);
    exit('success'); // 仍然返回success，避免重复通知
}

// 提取通知数据
$trade_no = $params['trade_no'];           // 平台订单号
$out_trade_no = $params['out_trade_no'];   // 商户订单号
$type = $params['type'];                   // 支付方式
$money = $params['money'];                 // 支付金额

/**
 * 在此处理订单业务逻辑
 * 
 * 1. 查询订单是否存在
 * 2. 验证订单金额是否一致
 * 3. 检查订单是否已处理过（防止重复通知）
 * 4. 更新订单状态为已支付
 * 5. 发货或提供服务
 */

// 示例：模拟处理订单
$order_processed = true; // 假设订单处理成功

// 记录订单处理结果
if ($order_processed) {
    write_log('订单处理成功', 'info', [
        'trade_no' => $trade_no,
        'out_trade_no' => $out_trade_no,
        'money' => $money,
        'type' => $type
    ]);
    
    // 响应支付平台
    exit('success');
} else {
    write_log('订单处理失败', 'error', [
        'trade_no' => $trade_no,
        'out_trade_no' => $out_trade_no
    ]);
    
    // 响应支付平台，告知处理失败
    // 注意：实际业务中，即使处理失败，也应该返回success，避免重复通知
    // 这里为了演示，返回fail以便平台重新通知
    exit('fail');
} 