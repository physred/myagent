---
name: tomato-pick
description: "采摘番茄到文件夹内"
always: false
---

# 使用场景
当用户需要番茄时，按以下流程操作。

## 采摘流程

### step1：确定番茄个数

当用户需要番茄时，首先确定用户需要多少个番茄。如果没有，则默认100个

### step2：采摘番茄

使用CreateTool在workspace下创建若干个文件`tomato_x.txt`，x代表序号。

使用WriteFileTool在文件中写入若干个“番茄”，表示这个文件存放了这个数量番茄，一个文件最多存放10个番茄。

使用ListDirTool列出workspace下的所有文件，找到所有以`tomato_`开头的文件。

### step3：返回文件列表

输出一个包含所有`tomato_x.txt`文件名的列表，告诉用户这些文件中存放了他们需要的番茄。
