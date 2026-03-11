# -*- coding: utf-8 -*-
import subprocess
import json
import sys
import os

os.chdir(r"D:\zhongwangchong")

order = {
    "id": "test001",
    "station_name": "29号站成都大学综合楼二号充电区V3.0",
    "device_code": "13061856473",
    "socket_no": 2,
    "amount_yuan": 1
}

print("==============================")
print("中网充 RPA 测试脚本")
print("==============================")
print()
input("请确保微信已打开并停留在中网充小程序首页，然后按 Enter 开始测试...")
print()
print("正在运行测试订单...")
print()

order_json = json.dumps(order, ensure_ascii=False)

result = subprocess.run(
    [sys.executable, r"services\local_charge_runner.py"],
    input=order_json.encode("utf-8"),
    capture_output=True,
)
stdout = result.stdout.decode("utf-8", errors="replace")
stderr = result.stderr.decode("utf-8", errors="replace")

print("输出结果：")
print(stdout)
if stderr:
    print("错误信息：")
    print(stderr)

print()
print("==============================")
print("测试完成")
print("==============================")
input("按 Enter 退出...")
