from __future__ import annotations

import time

import pyautogui


def main() -> None:
    print("把鼠标移动到目标位置，按 Ctrl+C 结束。")
    try:
        while True:
            x, y = pyautogui.position()
            print(f"\rX={x:4d}  Y={y:4d}", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
