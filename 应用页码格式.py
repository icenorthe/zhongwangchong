# -*- coding: utf-8 -*-
"""
应用页码格式.py
直接双击运行，弹出文件选择框选择Word文档即可。
也支持把Word文档拖到脚本上运行。
"""

import sys
import os

# ── 获取文件路径 ─────────────────────────────────────────────────────
if len(sys.argv) >= 2 and os.path.isfile(sys.argv[1]):
    doc_path = sys.argv[1]
    print(f"已接收文件：{doc_path}")
else:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        doc_path = filedialog.askopenfilename(
            title="选择要应用页码格式的Word文档",
            filetypes=[("Word文档", "*.docx *.doc"), ("所有文件", "*.*")]
        )
        root.destroy()
    except Exception as e:
        print(f"无法打开文件选择框：{e}")
        doc_path = input("请手动输入Word文档完整路径：").strip().strip('"')

if not doc_path:
    print("未选择文件，退出。")
    input("按回车退出...")
    sys.exit(0)

doc_path = os.path.abspath(doc_path)

if not os.path.isfile(doc_path):
    print(f"文件不存在：{doc_path}")
    input("按回车退出...")
    sys.exit(1)

print(f"目标文件：{doc_path}")

# ── 检查 win32com ────────────────────────────────────────────────────
try:
    import win32com.client as win32
except ImportError:
    print("\n缺少 pywin32，正在自动安装...")
    import subprocess
    subprocess.call([sys.executable, "-m", "pip", "install", "pywin32"])
    try:
        import win32com.client as win32
    except ImportError:
        print("安装失败，请手动运行：pip install pywin32")
        input("按回车退出...")
        sys.exit(1)

# Word 常量
wdAlignParagraphCenter      = 1
wdPageNumberStyleArabic     = 0
wdPageNumberStyleUpperRoman = 8
wdHeaderFooterPrimary       = 1
wdHeaderFooterFirstPage     = 3
wdFieldPage                 = 33

# ── 启动 Word ────────────────────────────────────────────────────────
print("\n正在启动 Word...")
try:
    word = win32.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
except Exception as e:
    print(f"无法启动Word：{e}")
    input("按回车退出...")
    sys.exit(1)

try:
    print("正在打开文档...")
    doc = word.Documents.Open(doc_path)
except Exception as e:
    print(f"无法打开文件：{e}")
    word.Quit()
    input("按回车退出...")
    sys.exit(1)

def clear_footer(section):
    for ftype in [wdHeaderFooterPrimary, wdHeaderFooterFirstPage]:
        try:
            f = section.Footers(ftype)
            f.LinkToPrevious = False
            f.Range.Delete()
        except:
            pass
    print("    -> 已清空页脚")

def set_footer_font(footer):
    rng = footer.Range
    rng.Font.Name        = "Times New Roman"
    rng.Font.NameAscii   = "Times New Roman"
    rng.Font.NameFarEast = "宋体"
    rng.Font.Size        = 9
    rng.Font.Bold        = False
    rng.Font.Italic      = False
    rng.Font.Color       = 0
    rng.Font.Underline   = 0

def set_page_number(section, doc, fmt, start_num, label):
    ps = section.PageSetup
    ps.PageNumberingStyle   = fmt
    ps.RestartPageNumbering = True
    ps.PageStartingNumber   = start_num

    footer = section.Footers(wdHeaderFooterPrimary)
    footer.LinkToPrevious = False
    footer.Range.Delete()

    rng = footer.Range
    rng.ParagraphFormat.Alignment = wdAlignParagraphCenter
    doc.Fields.Add(rng, wdFieldPage, " PAGE \\* MERGEFORMAT ", True)
    set_footer_font(footer)
    print(f"    -> 已设置{label}页码（Times New Roman 9磅 居中）")

try:
    sections = doc.Sections
    n = sections.Count
    print(f"\n文档共 {n} 节，开始处理...\n")

    for i in range(1, n + 1):
        sect = sections(i)
        print(f"  第 {i} 节：", end="")

        if i == 1:
            print("封面节")
            clear_footer(sect)
        elif i < n:
            print("前置节（目录/摘要）")
            set_page_number(sect, doc, wdPageNumberStyleUpperRoman, 1, "罗马数字")
        else:
            print("正文节")
            set_page_number(sect, doc, wdPageNumberStyleArabic, 1, "阿拉伯数字")

    print("\n正在保存...")
    doc.Save()
    doc.Close()
    word.Quit()
    print(f"\n完成！文件已保存：\n  {doc_path}")

except Exception as e:
    print(f"\n处理出错：{e}")
    import traceback
    traceback.print_exc()
    try:
        doc.Close(SaveChanges=False)
        word.Quit()
    except:
        pass

input("\n按回车退出...")
