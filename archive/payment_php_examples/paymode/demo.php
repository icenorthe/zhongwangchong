<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>平安夜支付中转演示</title>
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
        .payment-card {
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            transition: all 0.3s ease;
        }
        .payment-card:hover {
            border-color: #007bff;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .payment-icon {
            width: 40px;
            height: 40px;
            margin-right: 10px;
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
        .feature-icon {
            width: 48px;
            height: 48px;
            background-color: #f8f9fa;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }
    </style>
</head>
<body>
    <div class="container demo-container">
        <h1 class="text-center mb-4">平安夜支付中转演示</h1>
        
        <div class="alert alert-info">
            <strong>说明：</strong> 本演示展示了如何使用平安夜支付中转文件进行支付集成，无需跳转到支付平台即可完成付款。
        </div>
        
        <div class="row mb-4">
            <div class="col-md-4 mb-3">
                <div class="text-center">
                    <div class="feature-icon mx-auto">
                        <i class="text-primary">✓</i>
                    </div>
                    <h5>简单集成</h5>
                    <p class="text-muted">单文件集成，无需复杂配置</p>
                </div>
            </div>
            <div class="col-md-4 mb-3">
                <div class="text-center">
                    <div class="feature-icon mx-auto">
                        <i class="text-primary">⚡</i>
                    </div>
                    <h5>多种支付方式</h5>
                    <p class="text-muted">支持支付宝、微信、QQ钱包</p>
                </div>
            </div>
            <div class="col-md-4 mb-3">
                <div class="text-center">
                    <div class="feature-icon mx-auto">
                        <i class="text-primary">📱</i>
                    </div>
                    <h5>自适应界面</h5>
                    <p class="text-muted">完美适配PC端和移动端</p>
                </div>
            </div>
        </div>
        
        <h2 class="mt-4 mb-3">1. 直接调用方式</h2>
        <p>通过直接链接或按钮跳转到支付页面，传递必要参数：</p>
        
        <div class="row mt-3">
            <div class="col-md-4 mb-3">
                <div class="payment-card">
                    <div class="d-flex align-items-center mb-3">
                        <img src="https://www.alipay.com/favicon.ico" alt="支付宝" class="payment-icon">
                        <h5 class="mb-0">支付宝支付</h5>
                    </div>
                    <p class="mb-2">商品：VIP会员</p>
                    <p class="mb-3">金额：<strong class="text-danger">0.01</strong> 元</p>
                    <a href="submit.php?type=alipay&name=VIP会员&money=0.01" class="btn btn-primary w-100">立即支付</a>
                </div>
            </div>
            
            <div class="col-md-4 mb-3">
                <div class="payment-card">
                    <div class="d-flex align-items-center mb-3">
                        <img src="https://res.wx.qq.com/a/wx_fed/assets/res/NTI4MWU5.ico" alt="微信支付" class="payment-icon">
                        <h5 class="mb-0">微信支付</h5>
                    </div>
                    <p class="mb-2">商品：高级会员</p>
                    <p class="mb-3">金额：<strong class="text-danger">0.01</strong> 元</p>
                    <a href="submit.php?type=wxpay&name=高级会员&money=0.01" class="btn btn-success w-100">立即支付</a>
                </div>
            </div>
            
            <div class="col-md-4 mb-3">
                <div class="payment-card">
                    <div class="d-flex align-items-center mb-3">
                        <img src="https://qzonestyle.gtimg.cn/qzone/qzact/act/external/tiqq/logo.png" alt="QQ钱包" class="payment-icon">
                        <h5 class="mb-0">QQ钱包</h5>
                    </div>
                    <p class="mb-2">商品：超级会员</p>
                    <p class="mb-3">金额：<strong class="text-danger">0.01</strong> 元</p>
                    <a href="submit.php?type=qqpay&name=超级会员&money=0.01" class="btn btn-info w-100">立即支付</a>
                </div>
            </div>
        </div>
        
        <div class="code-block">
            &lt;a href="submit.php?type=alipay&name=VIP会员&money=0.01" class="btn btn-primary"&gt;支付宝支付&lt;/a&gt;<br>
            &lt;a href="submit.php?type=wxpay&name=高级会员&money=0.01" class="btn btn-success"&gt;微信支付&lt;/a&gt;<br>
            &lt;a href="submit.php?type=qqpay&name=超级会员&money=0.01" class="btn btn-info"&gt;QQ钱包支付&lt;/a&gt;
        </div>
        
        <h2 class="mt-4 mb-3">2. 用户选择支付方式</h2>
        <p>如果不指定支付方式，用户可以自由选择：</p>
        
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">商品：自选支付方式演示</h5>
                <p class="card-text">金额：<strong class="text-danger">0.01</strong> 元</p>
                <a href="submit.php?name=自选支付方式演示&money=0.01" class="btn btn-primary">去支付</a>
            </div>
        </div>
        
        <div class="code-block">
            &lt;a href="submit.php?name=自选支付方式演示&money=0.01" class="btn btn-primary"&gt;去支付&lt;/a&gt;
        </div>
        
        <h2 class="mt-4 mb-3">3. 表单提交方式</h2>
        <p>通过表单提交支付参数：</p>
        
        <div class="card mb-4">
            <div class="card-body">
                <form action="submit.php" method="post">
                    <div class="mb-3">
                        <label for="type" class="form-label">支付方式</label>
                        <select name="type" id="type" class="form-select">
                            <option value="">用户自选</option>
                            <option value="alipay">支付宝</option>
                            <option value="wxpay">微信支付</option>
                            <option value="qqpay">QQ钱包</option>
                        </select>
                        <div class="form-text">如果不选择，将显示支付方式选择页面</div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="name" class="form-label">商品名称</label>
                        <input type="text" name="name" id="name" class="form-control" value="自定义商品" required>
                    </div>
                    
                    <div class="mb-3">
                        <label for="money" class="form-label">支付金额</label>
                        <div class="input-group">
                            <input type="number" name="money" id="money" class="form-control" value="0.01" min="0.01" step="0.01" required>
                            <span class="input-group-text">元</span>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="out_trade_no" class="form-label">订单号（可选）</label>
                        <input type="text" name="out_trade_no" id="out_trade_no" class="form-control" placeholder="留空自动生成">
                    </div>
                    
                    <button type="submit" class="btn btn-primary">提交支付</button>
                </form>
            </div>
        </div>
        
        <div class="code-block">
            &lt;form action="submit.php" method="post"&gt;<br>
            &nbsp;&nbsp;&lt;select name="type"&gt;<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&lt;option value=""&gt;用户自选&lt;/option&gt;<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&lt;option value="alipay"&gt;支付宝&lt;/option&gt;<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&lt;option value="wxpay"&gt;微信支付&lt;/option&gt;<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&lt;option value="qqpay"&gt;QQ钱包&lt;/option&gt;<br>
            &nbsp;&nbsp;&lt;/select&gt;<br>
            &nbsp;&nbsp;&lt;input type="text" name="name" value="自定义商品" required&gt;<br>
            &nbsp;&nbsp;&lt;input type="number" name="money" value="0.01" min="0.01" step="0.01" required&gt;<br>
            &nbsp;&nbsp;&lt;input type="text" name="out_trade_no" placeholder="留空自动生成"&gt;<br>
            &nbsp;&nbsp;&lt;button type="submit"&gt;提交支付&lt;/button&gt;<br>
            &lt;/form&gt;
        </div>
        
        <h2 class="mt-4 mb-3">4. API调用方式</h2>
        <p>在您的业务逻辑中通过PHP代码调用支付函数：</p>
        
        <div class="code-block">
            &lt;?php<br>
            // 引入支付中转文件<br>
            require_once 'submit.php';<br>
            <br>
            // 调用创建订单函数<br>
            $result = create_payment_order(<br>
            &nbsp;&nbsp;'alipay',       // 支付方式<br>
            &nbsp;&nbsp;'高级会员套餐', // 商品名称<br>
            &nbsp;&nbsp;9.99,          // 支付金额<br>
            &nbsp;&nbsp;'ORDER'.time()  // 订单号（可选）<br>
            );<br>
            <br>
            // 处理返回结果<br>
            if ($result['code'] == 1) {<br>
            &nbsp;&nbsp;// 获取支付二维码和H5链接<br>
            &nbsp;&nbsp;$qrcode = $result['qrcode'];<br>
            &nbsp;&nbsp;$h5_url = $result['h5_qrurl'];<br>
            &nbsp;&nbsp;// 自定义显示支付页面...<br>
            } else {<br>
            &nbsp;&nbsp;// 处理错误...<br>
            &nbsp;&nbsp;echo $result['msg'];<br>
            }<br>
            ?&gt;
        </div>
        
        <div class="text-center mt-4">
            <a href="api_demo.php" class="btn btn-primary">查看API调用演示</a>
        </div>
        
        <h2 class="mt-4 mb-3">5. 配置说明</h2>
        <p>在使用支付中转文件前，请确保已正确配置以下信息：</p>
        
        <div class="code-block">
            $config = [<br>
            &nbsp;&nbsp;// API基础URL<br>
            &nbsp;&nbsp;'api_url' => 'https://pro.qjpay.icu',<br>
            &nbsp;&nbsp;<br>
            &nbsp;&nbsp;// 商户信息<br>
            &nbsp;&nbsp;'merchant' => [<br>
            &nbsp;&nbsp;&nbsp;&nbsp;'pid' => '您的商户ID',<br>
            &nbsp;&nbsp;&nbsp;&nbsp;'key' => '您的商户密钥',<br>
            &nbsp;&nbsp;],<br>
            &nbsp;&nbsp;<br>
            &nbsp;&nbsp;// 回调地址<br>
            &nbsp;&nbsp;'callback' => [<br>
            &nbsp;&nbsp;&nbsp;&nbsp;'notify_url' => 'http://您的域名/notify.php',<br>
            &nbsp;&nbsp;&nbsp;&nbsp;'return_url' => 'http://您的域名/return.php',<br>
            &nbsp;&nbsp;],<br>
            &nbsp;&nbsp;<br>
            &nbsp;&nbsp;// 网站名称<br>
            &nbsp;&nbsp;'site_name' => '您的网站名称',<br>
            ];
        </div>
        
        <div class="alert alert-warning mt-4">
            <strong>注意：</strong> 本演示仅用于测试，实际支付请使用您自己的商户信息。支付成功后，平台会通过异步通知和同步跳转通知支付结果。
        </div>
        <div class="alert alert-warning mt-4">
            <strong>注意：</strong> 实际对接时，请将notify.php和return.php中的商户密钥替换为您的商户密钥，否则将无法正常回调。
        </div>
        <div class="alert alert-warning mt-4">
            <strong>注意：</strong> 提交到submit.php的订单号等各种参数，应该由你自己的网站来生成，否则不好根据回调的订单来处理订单，无法判断是谁的订单。
        </div>
    </div>
    
    <footer class="text-center py-4 text-muted">
        <p>平安夜支付中转演示 &copy; <?php echo date('Y'); ?></p>
    </footer>
    
    <script src="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.0/js/bootstrap.bundle.min.js"></script>
</body>
</html> 