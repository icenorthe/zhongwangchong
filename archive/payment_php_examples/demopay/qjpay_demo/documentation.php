<?php
/**
 * 平安夜支付接口 - 接口文档
 * 
 * 本文件提供平安夜支付接口的详细文档说明
 * 包括API接口说明和签名算法详解
 * 
 * @author Demo Creator
 * @version 1.0.0
 * @date 2025-03-04
 */

// 引入公共函数库
require_once __DIR__ . '/libs/functions.php';

// 获取配置
$config = get_config();
?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付接口 - 接口文档</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }
        .container {
            max-width: 1200px;
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
        h3 {
            color: #333;
            margin-top: 20px;
        }
        p {
            color: #666;
            line-height: 1.6;
        }
        code {
            background-color: #f8f9fa;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: Consolas, Monaco, 'Andale Mono', monospace;
            font-size: 0.9em;
        }
        pre {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid #ddd;
        }
        pre code {
            background-color: transparent;
            padding: 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        table, th, td {
            border: 1px solid #ddd;
        }
        th, td {
            padding: 12px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
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
        .tab {
            overflow: hidden;
            border: 1px solid #ccc;
            background-color: #f1f1f1;
            border-radius: 5px 5px 0 0;
        }
        .tab button {
            background-color: inherit;
            float: left;
            border: none;
            outline: none;
            cursor: pointer;
            padding: 14px 16px;
            transition: 0.3s;
            font-size: 16px;
        }
        .tab button:hover {
            background-color: #ddd;
        }
        .tab button.active {
            background-color: #4CAF50;
            color: white;
        }
        .tabcontent {
            display: none;
            padding: 20px;
            border: 1px solid #ccc;
            border-top: none;
            border-radius: 0 0 5px 5px;
        }
        .btn {
            display: inline-block;
            padding: 8px 16px;
            background-color: #4CAF50;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.3s;
            margin-top: 20px;
        }
        .btn:hover {
            background-color: #45a049;
        }
        .btn-home {
            background-color: #2196F3;
        }
        .btn-home:hover {
            background-color: #0b7dda;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>平安夜支付接口文档</h1>
        
        <div class="tab">
            <button class="tablinks active" onclick="openTab(event, 'ApiDoc')">API接口说明</button>
            <button class="tablinks" onclick="openTab(event, 'SignDoc')">签名算法详解</button>
        </div>
        
        <div id="ApiDoc" class="tabcontent" style="display: block;">
            <h2>接口说明</h2>
            <p>平安夜支付接口提供了一系列API，用于创建订单、查询订单、获取用户信息等操作。以下是详细说明。</p>
            
            <div class="note">
                <p><strong>基础信息：</strong></p>
                <ul>
                    <li>接口基础域名: <code>https://pro.qjpay.icu</code></li>
                    <li>备用节点:
                        <ul>
                            <li>🔗 节点1: <code>https://pro1.qjpay.icu</code></li>
                            <li>🔗 节点2: <code>https://pro2.qjpay.icu</code></li>
                            <li>🔗 节点3: <code>https://pro3.qjpay.icu</code></li>
                        </ul>
                    </li>
                    <li>请求方式: POST</li>
                    <li>编码格式: UTF-8</li>
                    <li>签名方式: MD5</li>
                </ul>
            </div>
            
            <h3>1. API创建订单</h3>
            <p>通过API接口创建支付订单，获取支付二维码和支付链接。</p>
            
            <h4>请求URL:</h4>
            <pre><code>https://pro.qjpay.icu/mapi.php</code></pre>
            
            <h4>请求参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>必选</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>pid</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户ID</td>
                </tr>
                <tr>
                    <td>type</td>
                    <td>是</td>
                    <td>string</td>
                    <td>支付方式(alipay/wxpay/qqpay)</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户订单号</td>
                </tr>
                <tr>
                    <td>notify_url</td>
                    <td>是</td>
                    <td>string</td>
                    <td>异步通知地址</td>
                </tr>
                <tr>
                    <td>return_url</td>
                    <td>是</td>
                    <td>string</td>
                    <td>同步跳转地址</td>
                </tr>
                <tr>
                    <td>name</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商品名称</td>
                </tr>
                <tr>
                    <td>money</td>
                    <td>是</td>
                    <td>string</td>
                    <td>金额，精确到小数点后2位</td>
                </tr>
                <tr>
                    <td>sign</td>
                    <td>是</td>
                    <td>string</td>
                    <td>签名</td>
                </tr>
                <tr>
                    <td>sign_type</td>
                    <td>是</td>
                    <td>string</td>
                    <td>签名方式，固定值：MD5</td>
                </tr>
            </table>
            
            <h4>返回参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>code</td>
                    <td>int</td>
                    <td>状态码，1=成功，0=失败</td>
                </tr>
                <tr>
                    <td>msg</td>
                    <td>string</td>
                    <td>返回信息</td>
                </tr>
                <tr>
                    <td>qrcode</td>
                    <td>string</td>
                    <td>支付二维码内容</td>
                </tr>
                <tr>
                    <td>h5_qrurl</td>
                    <td>string</td>
                    <td>H5支付跳转链接</td>
                </tr>
                <tr>
                    <td>money</td>
                    <td>string</td>
                    <td>实际支付金额</td>
                </tr>
                <tr>
                    <td>status</td>
                    <td>int</td>
                    <td>订单状态，0=未支付，1=已支付</td>
                </tr>
            </table>
            
            <h3>2. 跳转支付</h3>
            <p>创建订单并跳转到平安夜收银台页面进行支付。</p>
            
            <h4>请求URL:</h4>
            <pre><code>https://pro.qjpay.icu/submit.php</code></pre>
            
            <h4>请求参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>必选</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>pid</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户ID</td>
                </tr>
                <tr>
                    <td>type</td>
                    <td>是</td>
                    <td>string</td>
                    <td>支付方式(alipay/wxpay/qqpay)</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户订单号</td>
                </tr>
                <tr>
                    <td>notify_url</td>
                    <td>是</td>
                    <td>string</td>
                    <td>异步通知地址</td>
                </tr>
                <tr>
                    <td>return_url</td>
                    <td>是</td>
                    <td>string</td>
                    <td>同步跳转地址</td>
                </tr>
                <tr>
                    <td>name</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商品名称</td>
                </tr>
                <tr>
                    <td>money</td>
                    <td>是</td>
                    <td>string</td>
                    <td>金额，精确到小数点后2位</td>
                </tr>
                <tr>
                    <td>sitename</td>
                    <td>否</td>
                    <td>string</td>
                    <td>网站名称</td>
                </tr>
                <tr>
                    <td>sign</td>
                    <td>是</td>
                    <td>string</td>
                    <td>签名</td>
                </tr>
                <tr>
                    <td>sign_type</td>
                    <td>是</td>
                    <td>string</td>
                    <td>签名方式，固定值：MD5</td>
                </tr>
            </table>
            
            <p>此接口会返回一个HTML页面，自动跳转到支付站点的收银台。</p>
            
            <h3>3. 订单查询</h3>
            <p>查询订单的支付状态、金额等信息。</p>
            
            <h4>请求URL:</h4>
            <pre><code>https://pro.qjpay.icu/qjt.php?act=query_order</code></pre>
            
            <h4>请求参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>必选</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>apiid</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户ID</td>
                </tr>
                <tr>
                    <td>apikey</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户密钥</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户订单号</td>
                </tr>
            </table>
            
            <h4>返回参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>code</td>
                    <td>int</td>
                    <td>状态码，1=成功，0=失败</td>
                </tr>
                <tr>
                    <td>msg</td>
                    <td>string</td>
                    <td>返回信息</td>
                </tr>
                <tr>
                    <td>status</td>
                    <td>int</td>
                    <td>订单状态，0=未支付，1=已支付</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>string</td>
                    <td>商户订单号</td>
                </tr>
                <tr>
                    <td>trade_no</td>
                    <td>string</td>
                    <td>平台订单号</td>
                </tr>
                <tr>
                    <td>money</td>
                    <td>string</td>
                    <td>支付金额</td>
                </tr>
                <tr>
                    <td>end_time</td>
                    <td>string</td>
                    <td>支付完成时间</td>
                </tr>
            </table>
            
            <h3>4. 用户信息查询</h3>
            <p>查询商户的费率、余额等信息。</p>
            
            <h4>请求URL:</h4>
            <pre><code>https://pro.qjpay.icu/qjt.php?act=query_user</code></pre>
            
            <h4>请求参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>必选</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>apiid</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户ID</td>
                </tr>
                <tr>
                    <td>apikey</td>
                    <td>是</td>
                    <td>string</td>
                    <td>商户密钥</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>否</td>
                    <td>string</td>
                    <td>商户订单号（可选）</td>
                </tr>
            </table>
            
            <h4>返回参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>code</td>
                    <td>int</td>
                    <td>状态码，1=成功，0=失败</td>
                </tr>
                <tr>
                    <td>msg</td>
                    <td>string</td>
                    <td>返回信息</td>
                </tr>
                <tr>
                    <td>data</td>
                    <td>object</td>
                    <td>用户信息</td>
                </tr>
                <tr>
                    <td>data.rate</td>
                    <td>float</td>
                    <td>费率(百分比)</td>
                </tr>
                <tr>
                    <td>data.money</td>
                    <td>float</td>
                    <td>账户余额</td>
                </tr>
                <tr>
                    <td>data.timeout_time</td>
                    <td>int</td>
                    <td>订单超时时间(秒)</td>
                </tr>
                <tr>
                    <td>data.voice</td>
                    <td>int</td>
                    <td>是否开启语音播报，1=开启，0=关闭</td>
                </tr>
                <tr>
                    <td>data.voice_content</td>
                    <td>string</td>
                    <td>语音播报内容模板</td>
                </tr>
                <tr>
                    <td>data.cash_desk_tips</td>
                    <td>string</td>
                    <td>收银台提示信息</td>
                </tr>
                <tr>
                    <td>order</td>
                    <td>object</td>
                    <td>订单信息（如果提供了订单号）</td>
                </tr>
                <tr>
                    <td>order.h5_qrurl</td>
                    <td>string</td>
                    <td>H5支付链接</td>
                </tr>
                <tr>
                    <td>order.qrcode</td>
                    <td>string</td>
                    <td>支付二维码内容</td>
                </tr>
                <tr>
                    <td>order.status</td>
                    <td>int</td>
                    <td>订单状态</td>
                </tr>
            </table>
            
            <h3>5. 异步通知</h3>
            <p>支付成功后，平台会向您的异步通知地址(notify_url)发送支付结果。</p>
            
            <h4>通知参数:</h4>
            <table>
                <tr>
                    <th>参数名</th>
                    <th>类型</th>
                    <th>说明</th>
                </tr>
                <tr>
                    <td>trade_no</td>
                    <td>string</td>
                    <td>平台订单号</td>
                </tr>
                <tr>
                    <td>out_trade_no</td>
                    <td>string</td>
                    <td>商户订单号</td>
                </tr>
                <tr>
                    <td>type</td>
                    <td>string</td>
                    <td>支付方式</td>
                </tr>
                <tr>
                    <td>money</td>
                    <td>string</td>
                    <td>支付金额</td>
                </tr>
                <tr>
                    <td>trade_status</td>
                    <td>string</td>
                    <td>交易状态，TRADE_SUCCESS=支付成功</td>
                </tr>
                <tr>
                    <td>sign</td>
                    <td>string</td>
                    <td>签名</td>
                </tr>
                <tr>
                    <td>sign_type</td>
                    <td>string</td>
                    <td>签名类型</td>
                </tr>
            </table>
            
            <p>商户收到通知后，需要验证签名是否正确，验证通过后需要返回字符串 "success"，否则平台会重复发送通知。</p>
        </div>
        
        <div id="SignDoc" class="tabcontent">
            <h2>签名算法详解</h2>
            <p>平安夜支付接口使用MD5签名算法来确保数据的安全性和完整性。以下是签名算法的详细说明。</p>
            
            <div class="note">
                <p><strong>签名流程：</strong></p>
                <ol>
                    <li>对所有API参数(除sign和sign_type外)，按照参数名ASCII码从小到大排序</li>
                    <li>把所有参数名和参数值拼接成字符串，格式为: <code>参数名=参数值&参数名=参数值...</code></li>
                    <li>在最后直接拼接上商户密钥: <code>原字符串+商户密钥</code></li>
                    <li>对拼接后的字符串进行MD5加密，得到32位小写签名</li>
                </ol>
            </div>
            
            <h3>签名算法代码示例</h3>
            
            <pre><code>/**
 * 生成签名
 * 
 * @param array $params 要签名的参数数组
 * @param string $key 商户密钥
 * @return string MD5签名
 */
function getSign($params, $key) {
    // 1. 过滤掉空值和签名参数
    $filter_params = [];
    foreach ($params as $k => $v) {
        if ($k != "sign" && $k != "sign_type" && $v !== '') {
            $filter_params[$k] = $v;
        }
    }
    
    // 2. 按照参数名ASCII码从小到大排序
    ksort($filter_params);
    reset($filter_params);
    
    // 3. 拼接成字符串
    $signstr = '';
    foreach ($filter_params as $k => $v) {
        $signstr .= $k . '=' . $v . '&';
    }
    $signstr = substr($signstr, 0, -1);  // 去掉最后的&
    
    // 4. 拼接商户密钥
    $signstr .= $key;
    
    // 5. MD5加密
    return md5($signstr);
}
</code></pre>
            
            <h3>签名验证</h3>
            
            <pre><code>/**
 * 验证签名
 * 
 * @param array $params 接收到的参数数组
 * @param string $key 商户密钥
 * @return bool 是否验证通过
 */
function verifySign($params, $key) {
    // 获取接收到的签名
    $sign = isset($params['sign']) ? $params['sign'] : '';
    
    if (empty($sign)) {
        return false;
    }
    
    // 计算签名
    $expected_sign = getSign($params, $key);
    
    // 比较签名
    return $expected_sign === $sign;
}
</code></pre>
            
            <h3>注意事项</h3>
            <div class="warning">
                <p><strong>特别提醒：</strong></p>
                <ul>
                    <li>参数值为空的参数不参与签名</li>
                    <li>参数名区分大小写</li>
                    <li>商户密钥不能泄露给客户端</li>
                    <li>签名验证必须在服务器端完成</li>
                    <li>拼接密钥时是直接拼接，不带任何前缀</li>
                </ul>
            </div>
            
            <h3>常见问题</h3>
            <p><strong>1. 签名验证失败的常见原因</strong></p>
            <ul>
                <li>商户密钥错误</li>
                <li>参数值编码不一致（建议统一使用UTF-8编码）</li>
                <li>参数排序方式不正确</li>
                <li>签名算法与文档不一致（如拼接方式不同）</li>
                <li>参数值包含特殊字符，未正确处理</li>
            </ul>
            
            <p><strong>2. 如何调试签名问题</strong></p>
            <ul>
                <li>打印出签名前的原始字符串，确认是否与预期一致</li>
                <li>使用相同的参数和密钥在多个环境下计算签名，比较结果</li>
                <li>确认商户密钥没有多余的空格或换行符</li>
                <li>检查参数值是否有特殊字符需要进行URL编码</li>
            </ul>
        </div>
        
        <div style="text-align: center; margin-top: 30px;">
            <a href="index.php" class="btn btn-home">返回首页</a>
        </div>
    </div>
    
    <script>
        function openTab(evt, tabName) {
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {
                tabcontent[i].style.display = "none";
            }
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
    </script>
</body>
</html> 