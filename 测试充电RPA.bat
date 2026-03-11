@echo off
chcp 65001 >nul
cd /d D:\zhongwangchong

echo ==============================
echo 中网充 RPA 测试脚本
echo ==============================
echo.
echo 请确保微信已打开并停留在中网充小程序首页，然后按任意键开始测试...
pause >nul

echo.
echo 正在运行测试订单...
echo.

echo {"id": "test001", "station_name": "29号站成都大学综合楼二号充电区V3.0", "device_code": "13061856473", "socket_no": 2, "amount_yuan": 1} | python services\local_charge_runner.py

echo.
echo ==============================
echo 测试完成，请查看上方结果。
echo ==============================
echo.
pause
