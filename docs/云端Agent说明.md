# 云端 Agent 说明

这个 Agent 运行在你的 Windows 电脑上，负责轮询 PythonAnywhere 上待处理的订单。  
一旦抢到订单，它就会调用本地微信执行器，并把执行结果再回写到云端订单。

## 相关文件

- `services/cloud_agent.py`
- `config/cloud_agent_config.json`
- `services/local_charge_runner.py`
- `启动云端Agent.bat`
- `停止云端Agent.bat`

## 启动

```bat
启动云端Agent.bat
```

## 停止

```bat
停止云端Agent.bat
```

## 单次测试

```bat
python ??\cloud_agent.py --once
```

## 当前流程

1. 用户在 PythonAnywhere 站点提交订单。
2. 订单状态保持为 `PENDING`。
3. `services/cloud_agent.py` 定时上报心跳，让网站知道“接单电脑是否在线”。
4. `services/cloud_agent.py` 抢占一条待处理订单。
5. Agent 调用 `services/local_charge_runner.py` 执行本地微信自动化。
6. Agent 把结果回写成 `SUCCESS` 或 `FAILED`。

## 配置位置

主配置在 `config/cloud_agent_config.json`，常见字段如下：

- `base_url`：PythonAnywhere 站点地址
- `agent_name`：这台电脑在云端显示的名称，不填默认用电脑主机名
- `agent_token`：本地 Agent 使用的令牌
- `poll_seconds`：轮询间隔秒数
- `runner_command`：本地执行器命令，默认是 `python ??\local_charge_runner.py`
- `runner_timeout_seconds`：单次执行超时时间

## 心跳和在线状态

- Agent 每次轮询都会调用 `POST /api/agent/heartbeat`
- 网站首页会根据最近一次心跳显示“电脑在线 / 离线”
- 如果你启用了 `REQUIRE_AGENT_ONLINE_FOR_ORDERS=1`，当电脑离线时网站会直接拒绝新订单

## 执行器返回格式

本地执行器必须输出一行 JSON，例如：

```json
{"success": true, "message": "完成", "order_id": "local-123"}
```

## 日志位置

- `runtime/logs/cloud_agent.log`
- `runtime/logs/local_charge_runner.log`

