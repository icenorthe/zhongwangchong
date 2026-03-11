# 微信 RPA 说明

这是当前项目里最快的整链路测试方式：  
云端接单，本地 Windows 电脑自动执行微信小程序页面操作。

目前本地执行器已经支持：

- 模板图识别优先
- 坐标点击兜底

## 支持的页面流程

本地执行器现在可以覆盖这条微信小程序路径：

1. 打开小程序
2. 可选广告页
3. 首页或站点列表页
4. 插座选择页
5. 金额选择页
6. 支付方式页

对应配置项含义：

- `launch_ad_skip_*`：广告页“跳过”
- `vehicle_tab_*`：首页页签，例如“电动自行车”
- `search_station_*`：站点搜索框
- `station_result_*`：站点列表结果卡片
- `socket_*`：插座选择
- `go_charge_*`：插座页底部“去充电”
- `amount_*`：金额按钮，例如 `¥1.00`
- `submit_order_*`：金额页“立即支付”
- `wechat_pay_*`：支付方式中的“微信支付”
- `pay_confirm_*`：最终“开始充电”

## 重要说明

- 广告页不要点广告内容本身。
- 如果广告页经常出现，可以二选一：
  - 设置 `launch_ad_wait_seconds` 等待倒计时结束
  - 配置 `launch_ad_skip_point` 或 `launch_ad_skip_image`
- 如果你打算先手动进入站点页，再让脚本接着往下跑，那么前面那些搜索步骤都可以保留为 `null`

## 第一轮最快测试方式

先这样做：

1. 手动打开 Windows 微信
2. 手动进入目标小程序
3. 手动打开目标站点页
4. 固定窗口大小和位置

然后只让脚本自动处理：

- 选插座
- 可选点一次 `去充电`
- 选金额
- 点 `立即支付`
- 选 `微信支付`
- 点 `开始充电`

## 相关文件

- `services/local_charge_runner.py`
- `config/wechat_rpa_config.json`
- `assets/wechat_rpa`
- `查看鼠标坐标.bat`
- `services/cloud_agent.py`

## 1）测量坐标

运行：

```bat
查看鼠标坐标.bat
```

把鼠标移动到目标按钮上，记录 `X` 和 `Y`。

第一轮通常至少要填这些：

- `socket_points`
- `amount_points`
- `go_charge_point`
- `submit_order_point`
- `wechat_pay_point`
- `pay_confirm_point`

如果还想让脚本自动搜索站点，再补：

- `launch_ad_skip_point` 或 `launch_ad_wait_seconds`
- `vehicle_tab_point`
- `search_station_point`
- `station_result_point`

如果要启用模板图识别，就把截图裁好后放进 `assets/wechat_rpa`，并在 `config/wechat_rpa_config.json` 里引用，例如：

- `launch_ad_skip_image`
- `ready_state_image`
- `vehicle_tab_image`
- `go_charge_image`
- `submit_order_image`
- `wechat_pay_image`
- `pay_confirm_image`
- `socket_2_image`
- `amount_1_image`

## 2）修改配置

打开 `config/wechat_rpa_config.json`。

第一轮建议：

- 如果你从站点页开始测，就把前面页面步骤保留为 `null`
- 如果你已经知道搜索点位，可以保留 `search_station_point` 和 `station_result_point`
- 不知道的就先设为 `null`
- 把实际测到的坐标填进去
- 保持 `"enabled": true`

示例：

```json
{
  "enabled": true,
  "wechat_window_title_keywords": ["微信"],
  "step_delay_seconds": 0.8,
  "template_confidence": 0.9,
  "after_submit_wait_seconds": 3,
  "manual_payment_confirm_seconds": 0,
  "launch_ad_wait_seconds": 3.5,
  "payment_method": "wechat",
  "ready_state_image": null,
  "launch_ad_skip_point": null,
  "vehicle_tab_point": null,
  "search_station_point": null,
  "station_result_point": null,
  "go_charge_point": { "x": 490, "y": 745 },
  "submit_order_point": { "x": 490, "y": 745 },
  "wechat_pay_point": { "x": 470, "y": 648 },
  "pay_confirm_point": { "x": 500, "y": 810 },
  "socket_points": {
    "1": { "x": 126, "y": 410 },
    "2": { "x": 243, "y": 410 }
  },
  "amount_points": {
    "1": { "x": 430, "y": 437 },
    "2": { "x": 590, "y": 437 }
  }
}
```

补充说明：

- `station_search_text_template` 默认用 `$station_name`
- 如果订单里只有 `device_code`，执行器会尝试从 `config/stations.json` 反查站点名
- 如果支付方式页固定不变，`payment_method` 保持 `"wechat"` 就可以

## 3）执行一次本地联调

先创建一条云端测试订单，再运行：

```bat
python ??\cloud_agent.py --once
```

如果失败，优先查看：

- `runtime/logs/cloud_agent.log`
- `runtime/logs/local_charge_runner.log`
- `runtime/runner_screenshots`

## 4）启动持续轮询

```bat
启动云端Agent.bat
```

## 额外提醒

- 本地执行器默认假设 Windows 微信已经打开
- 模板图找不到时，会自动退回到坐标点击
- 如果支付最后还需要人工确认，可以设置 `manual_payment_confirm_seconds`
- 如果你还想用半手动模式，这些字段可以继续留空：
  - `launch_ad_skip_*`
  - `vehicle_tab_*`
  - `search_station_*`
  - `station_result_*`
  - `go_charge_*`
  - `wechat_pay_*`

