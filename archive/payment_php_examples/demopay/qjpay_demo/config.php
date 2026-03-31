<?php
/**
 * QJPay支付接口配置文件
 * 
 * 本文件包含了接入QJPay支付接口所需的基础配置信息
 * 请根据实际情况修改以下配置
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 开启错误显示，生产环境请设置为false
ini_set('display_errors', 'On');
error_reporting(E_ALL);

// 设置时区
date_default_timezone_set('Asia/Shanghai');

// 基础配置
return [
    // API基础URL (正式环境)
    'api_url' => 'https://pro.qjpay.icu',
    
    // 商户信息
    'merchant' => [
        'pid' => '1000', // 商户ID，请替换为您的实际商户ID
        'key' => 'xxxxxxxxxxxxx', // 商户密钥，请替换为您的实际商户密钥
    ],
    
    // 支付回调配置
    'callback' => [
        // 异步通知地址，服务器通知，不能带参数，记得改成实际的地址
        'notify_url' => 'http://你的域名/qjpay_demo/notify.php',
        
        // 同步跳转地址，支付成功后跳转，可带参数，记得改成实际的地址
        'return_url' => 'http://你的域名/qjpay_demo/return.php',
    ],
    
    // 支付方式
    'pay_types' => [
        'alipay' => '支付宝',
        'wxpay' => '微信支付',
        'qqpay' => 'QQ钱包',
    ],
    
    // 日志配置
    'log' => [
        'enabled' => true, // 是否启用日志
        'path' => __DIR__ . '/logs/', // 日志保存路径
    ],
    
    // 其他配置
    'site_name' => '演示商城', // 网站名称，用于在支付页面显示
    'time_out' => 300, // 订单超时时间（秒）
]; 