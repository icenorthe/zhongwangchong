# -*- coding: utf-8 -*-
"""单独测试模板图匹配"""
import pyautogui
import time
from pathlib import Path

ASSETS = Path(r"D:\zhongwangchong\assets\wechat_rpa")

print("3秒后开始截屏并测试模板匹配，请确保小程序首页可见...")
time.sleep(3)

screen = pyautogui.screenshot()
screen.save(r"D:\zhongwangchong\runtime\test_screen.png")
print("截屏已保存到 runtime/test_screen.png")

templates = ["search_box.png", "search_btn.png", "station_result.png"]
for name in templates:
    path = ASSETS / name
    for conf in [0.9, 0.8, 0.7, 0.6]:
        loc = pyautogui.locateOnScreen(str(path), confidence=conf, grayscale=True)
        if loc:
            print(f"[找到] {name} confidence={conf} 位置={loc}")
            break
    else:
        print(f"[未找到] {name} (0.6以上置信度均失败)")

input("按Enter退出...")
