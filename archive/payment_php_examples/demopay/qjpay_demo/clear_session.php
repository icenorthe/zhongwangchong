<?php
/**
 * 平安夜支付接口 - 清除会话
 * 
 * 本文件用于清除临时的商户配置
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 启动会话
session_start();

// 清除临时配置
if (isset($_SESSION['temp_config'])) {
    unset($_SESSION['temp_config']);
}

// 返回成功状态
header('Content-Type: application/json');
echo json_encode(['success' => true]);
?> 