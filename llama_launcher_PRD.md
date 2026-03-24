# llama launcher — 产品需求与技术实现文档

> **版本**: v3.1  
> **更新日期**: 2026-03  
> **开发环境**: Windows 11 · i9-14900HX · RTX 5060 8G · 32GB RAM  
> **技术栈**: Python 3.8+ · tkinter · llama.cpp (b8388+) · psutil · nvidia-smi

---

## 一、产品概述

### 1.1 背景与目标

llama launcher 是一个面向 Windows 用户的本地 AI 模型图形化管理工具，基于 llama.cpp 运行引擎。核心目标是消除本地模型运行的命令行门槛，让用户通过图形界面完成模型的加载、参数调优、服务部署和监控。

### 1.2 核心用户场景

| 场景 | 描述 |
|------|------|
| 本地对话 | 选模型 → 调参数 → 启动 PowerShell 黑框对话 |
| API 服务 | 启动 llama-server，供 OpenWebUI 等前端调用 |
| 参数调优 | 调整 gpu_layers/ctx 等参数，记忆到模型配置 |
| 角色切换 | 快速切换预设 system prompt，适应不同任务场景 |

### 1.3 文件结构

```
E:/models/
├── llama_launcher.py       # 主程序（单文件）
├── config.json             # 全局配置（路径/服务/角色/硬件信息）
├── models_config.json      # 模型参数记忆 + 专属 prompt
├── CHANGELOG.md            # 版本日志
└── logs/                   # 自动生成的运行日志
    ├── server_YYYYMMDD_HHMMSS_模型名.log
    └── chat_YYYYMMDD_HHMMSS_模型名.log
```

---

## 二、界面布局

### 2.1 三栏布局

```
窗口总宽: 1400px（最小 1100px）
┌─────────────────┬──────────────────┬──────────────────┐
│  左栏 550px      │  中栏 420px       │  右栏（自适应）   │
│  模型目录        │  启动模式         │  服务状态         │
│  模型列表        │  推理参数         │  加载进度         │
│  命令预览        │  extra_args       │  服务日志         │
│  System Prompt  │  启动按钮         │  系统资源仪表盘   │
│                  │  强制终止按钮     │  服务参数         │
└─────────────────┴──────────────────┴──────────────────┘
```

### 2.2 顶部工具栏

从左到右：`⚡ llama launcher`（标题）· `本地 AI 模型管理器 · Windows`  
从右到左：`↻ 重新扫描` · `☠ 终止所有llama` · `📂 日志目录` · `🖥 硬件信息` · `⚙ 编辑 config.json`

### 2.3 System Prompt 面板（左栏下半）

```
[ 角色预设按钮行: 🤖AI助手  🔧Agent  🏢数据中心  📚百科  💻代码  🌐翻译  🔬分析  📝写作 ]
来源: 全局 config.json                              [ ↩ 重置 ][ 💾 保存 ]
┌─────────────────────────────────────────────────────────┐
│ 你是一个高效、精准的本地 AI 助手。                          │
│ 【回答规则】                                              │
│ 1. 直接给出结论...                                        │
│                                                          │
│ ─────────────── EN ───────────────                       │
│ You are an efficient and precise local AI assistant.     │
│ Rules: 1. Give the conclusion directly...                │
└─────────────────────────────────────────────────────────┘
[ 📋 复制中文 ][ 📋 复制英文 ]   传参语言: ● 中文  ● 英文  ○ 不传
```

---

## 三、功能需求

### 3.1 模型管理

| 功能 | 描述 | 状态 |
|------|------|------|
| 目录扫描 | 递归扫描配置的目录，发现所有 `.gguf` 文件 | ✅ |
| 多目录支持 | 可添加/删除多个扫描目录 | ✅ |
| 自动参数匹配 | 按文件名关键词（7b/14b/35b/qwen等）匹配推荐参数 | ✅ |
| 参数记忆 | 调整并保存后，下次选中自动恢复 | ✅ |
| 命令预览 | 实时显示完整启动命令，可一键复制 | ✅ |

### 3.2 对话模式

| 功能 | 描述 | 状态 |
|------|------|------|
| PowerShell 启动 | 通过临时 `.ps1` 脚本启动黑框对话 | ✅ |
| System Prompt 注入 | 通过 `-f` 参数传入临时 UTF-8 文本文件 | ✅ |
| 中英文传参切换 | 界面显示中文，可选传中文/英文/不传 | ✅ |
| 隐藏 thinking | PowerShell 脚本层过滤 `<think>...</think>` | ✅ |
| 停止对话 | `⏹ 停止` 按钮调用 `taskkill /F /IM llama-cli.exe` | ✅ |
| 启动日志 | 记录启动参数到 `logs/chat_*.log` | ✅ |

### 3.3 服务模式

| 功能 | 描述 | 状态 |
|------|------|------|
| llama-server 启动 | 启动 API Server，暴露 OpenAI 兼容接口 | ✅ |
| 实时日志流 | 后台线程读取 stdout，100ms 批量刷新 UI | ✅ |
| 服务就绪检测 | 检测到 `listening` 关键词自动推进度到 100% | ✅ |
| 停止/重启/切换 | 三个控制按钮，切换时弹确认对话框 | ✅ |
| API Key 管理 | 自动保存修改的 Key 到 config.json | ✅ |
| 复制访问地址 | 浏览器地址 / 带 Bearer Token 的 API 地址 | ✅ |
| 复制 API Key | 单独复制 Key，供客户端配置 | ✅ |
| 服务日志归档 | 完整日志保存到 `logs/server_*.log`，保留最近 10 份 | ✅ |
| System Prompt | b8388 版不支持命令行注入，通过复制功能手动配置 | ⚠️ |

> **⚠️ 注**: llama-server b8388 不支持 `--system-prompt` 参数。升级到 b8500+ 后可自动传入。

### 3.4 参数配置

| 参数 | 范围 | 说明 |
|------|------|------|
| gpu_layers | 0–200 | GPU 卸载层数，不是越高越好，超显存溢出变慢 |
| threads | 1–64 | CPU 推理线程数 |
| ctx | 512–131072 | 上下文窗口大小，越大越耗显存/内存 |
| batch | 64–2048 | 批处理 token 数 |
| temp | 0.0–2.0 | 温度，越高越随机 |
| top_p | 0.0–1.0 | 核采样概率 |
| top_k | 1–200 | 候选 token 数量 |
| repeat_penalty | 1.0–1.5 | 重复惩罚系数 |
| stop_tokens | — | 停止词，逗号分隔 |
| extra_args | — | 自由传入额外参数 |

**extra_args 快捷按钮（三行）**

```
行1: ⊘不思考(--reasoning off)  🧠思考  chatml  llama3
行2: mistral  ⚡flash-attn  🔒mlock  🗑清空
行3: ↔ctx-shift  📌min-p  ♻cache-reuse
```

### 3.5 角色与 Prompt 管理

**8 个内置角色（中英双语）**

| 角色 | 适用场景 | 英文版用途 |
|------|---------|-----------|
| 🤖 AI助手 | 通用对话 | 服务模式传参 |
| 🔧 Agent | 任务拆解执行 | 服务模式传参 |
| 🏢 数据中心运维专家 | IDC 运维故障诊断 | 服务模式传参 |
| 📚 百科全书 | 知识查询 | 服务模式传参 |
| 💻 代码专家 | 编程开发 | 服务模式传参 |
| 🌐 翻译专家 | 多语言互译 | 服务模式传参 |
| 🔬 数据分析师 | 数据分析可视化 | 服务模式传参 |
| 📝 写作助手 | 文案创作润色 | 服务模式传参 |

**Prompt 保存逻辑**

```
点击角色按钮后点💾保存  →  写入 config.json: roles[角色名] + roles_en[角色名]
未点角色按钮（模型专属）→  写入 models_config.json: models[模型名].system_prompt
                                                   + system_prompt_en
↩ 重置（角色状态）       →  恢复程序内置 DEFAULT_ROLES + PROMPT_EN
↩ 重置（模型状态）       →  清除专属配置，回退全局 config.json
```

### 3.6 系统监控仪表盘

**设备信息（顶部，首次扫描后缓存）**
- CPU 型号 + 核心/线程数（wmic）
- 内存总量 + 各条规格（wmic memorychip）
- GPU 型号 + 显存（nvidia-smi）

**实时监控（每秒刷新）**

| 指标 | 来源 | 显示 |
|------|------|------|
| CPU 利用率 | psutil.cpu_percent | 进度条 + 百分比 + 频率 |
| RAM 占用 | psutil.virtual_memory | 进度条 + 已用/总量 |
| GPU 利用率 | nvidia-smi | 进度条 + 百分比 + 温度 |
| VRAM 占用 | nvidia-smi | 进度条 + 已用/总量 |
| Token 速度 | 解析服务日志 | 当前 t/s + 峰值 t/s |
| 累计 Token | 解析 `total time` 日志行 | 累加输出 token 数 |

**颜色规则**: <70% 绿色 · 70-90% 琥珀 · >90% 红色

### 3.7 稳定性与可靠性

| 机制 | 实现 |
|------|------|
| 配置原子写入 | 先写临时文件再重命名替换，防写入中断损坏 |
| 进程真实退出检测 | stdout 关闭后 poll() 确认进程状态，防误报停止 |
| 强制终止 | taskkill + psutil 双重保障，杀死所有 llama 进程 |
| 关闭保护 | 服务运行时关窗口弹确认，可选停止后退出 |
| 日志归档 | 每次服务/对话生成独立日志文件，最多保留 10 份 |
| 资源监控异常隔离 | 所有监控操作包裹 try/except，不影响主程序 |

---

## 四、配置文件规范

### 4.1 config.json 结构

```json
{
  "_comment": "说明",
  "llama_cli_path":    "E:/llama-xxx/llama-cli.exe",
  "llama_server_path": "E:/llama-xxx/llama-server.exe",
  "model_dirs":        ["E:/models"],

  "server": {
    "host":     "0.0.0.0",
    "port":     8080,
    "api_keys": { "default": "sk-xxx" },
    "slots":    1
  },

  "chat": {
    "powershell_keep_open": true
  },

  "system_prompt": "全局默认 system prompt（中文）",

  "roles": {
    "🤖 AI助手": "中文 prompt...",
    "💻 代码专家": "中文 prompt..."
  },

  "roles_en": {
    "🤖 AI助手": "English prompt...",
    "💻 代码专家": "English prompt..."
  },

  "hardware": {
    "cpu_name":   "Intel Core i9-14900HX",
    "cpu_cores":  "8P+16E 共32线程",
    "ram_total":  "31.6 GB",
    "ram_sticks": "16GB@4800MHz  16GB@4800MHz",
    "gpu_name":   "NVIDIA GeForce RTX 5060 Laptop GPU",
    "gpu_vram":   "8.0 GB",
    "scanned_at": "2026-03-24 22:30"
  }
}
```

### 4.2 models_config.json 结构

```json
{
  "_profiles": {
    "qwen-35b-moe": {
      "_match": ["qwen", "35b"],
      "gpu_layers": 20,
      "ctx": 2048,
      "extra_args": "--chat-template chatml"
    },
    "default": { ... }
  },

  "models": {
    "Qwen3.5-9B-Q5_K_M.gguf": {
      "gpu_layers": 97,
      "ctx": 16128,
      "extra_args": "--reasoning off",
      "last_mode": "server",
      "hide_think": true,
      "system_prompt":    "模型专属中文 prompt（可选）",
      "system_prompt_en": "Model-specific English prompt（可选）"
    }
  }
}
```

---

## 五、核心代码结构

### 5.1 全局函数（模块级）

```
配置IO:         _load_json / _save_json（原子写入）
配置管理:       load_config / save_config / load_models_cfg / save_models_cfg
模型扫描:       scan_models
参数匹配:       match_profile / _strip_meta / _hardcoded_default
命令构建:       build_chat_cmd / build_server_cmd / cmd_to_display
PowerShell:    _launch_powershell（生成 .ps1 脚本）
时间工具:       _ts（时间戳字符串）
硬件扫描:       scan_hardware_info / get_or_scan_hardware
日志管理:       _ensure_logs_dir / _new_log_path / _rotate_logs
英文Prompt:    get_prompt_en（中英文 prompt 转换）
```

### 5.2 App 类（tkinter.Tk 子类）

```
UI构建:
  _build_ui         → 顶部栏 + 三栏布局
  _build_topbar     → 标题栏 + 工具按钮
  _build_left       → 模型目录/列表/命令预览/Prompt编辑
  _build_right      → 启动模式/推理参数/extra_args/启动按钮
  _build_monitor    → 服务状态/加载进度/服务日志/系统资源
  _param_row        → 单行参数（标签+滑块+输入框+trace同步）
  _card / _btn      → 通用卡片/按钮控件

模型操作:
  _do_scan          → 后台线程扫描模型
  _on_model_select  → 选中模型时加载参数
  _collect_params   → 从UI控件收集当前参数
  _save_params      → 保存参数到 models_config

对话/服务:
  _launch           → 分发到 chat 或 server
  _launch_chat      → 启动 PowerShell 对话
  _launch_server    → 启动 llama-server
  _stop_current     → 停止按钮（兼容两种模式）
  _stop_server      → terminate + kill 双重停止
  _restart_server   → 停止 + 重启
  _switch_model     → 停止 + 切换 + 重启
  _kill_all_llama   → taskkill + psutil 强制清除

日志流:
  _stream_server_log   → 后台线程读 stdout 放入队列
  _poll_log_queue      → 主线程 100ms 定时器消费队列
  _srv_log_append      → 解析日志行（颜色/进度/token速度）
  _on_server_exit      → 进程退出时重置 UI 状态

Prompt管理:
  _load_bilingual_prompt  → 中英文合并写入编辑框
  _get_prompt_zh          → 提取中文部分
  _get_prompt_en_from_box → 提取英文部分
  _get_active_prompt      → 按传参语言选择返回实际内容
  _load_role              → 点角色按钮：双语加载
  _load_prompt_for_model  → 切模型时加载（含角色识别）
  _save_prompt            → 分别保存中/英文到角色或模型
  _reset_prompt_to_global → 重置到内置默认

监控:
  _init_hardware_info    → 后台扫描硬件，更新 UI
  _apply_hardware_labels → 把硬件信息填入标签
  _rescan_hardware       → 强制重扫（清除缓存）
  _start_resource_monitor → 启动 1 秒刷新循环
  _resource_loop          → 后台线程：psutil + nvidia-smi
  _query_nvidia_smi       → 调用 nvidia-smi 获取 GPU 数据
  _update_res_ui          → 主线程更新进度条和标签
  _update_load_progress   → 更新模型加载进度条
  _update_tok_speed       → 更新 token 速度 + 峰值

工具:
  _on_close           → 关闭保护（服务运行时弹确认）
  _copy_cmd           → 复制启动命令
  _copy_prompt_zh/en  → 复制中文/英文 Prompt
  _copy_srv_url       → 复制服务访问地址
  _copy_apikey        → 复制 API Key
  _open_log_file      → 用记事本打开最新日志
  _open_logs_dir      → 打开日志目录
  _open_config        → 用记事本打开 config.json
```

---

## 六、已知限制与后续计划

### 6.1 当前限制

| 限制 | 原因 | 绕过方案 |
|------|------|---------|
| 服务模式无法注入 system prompt | llama-server b8388 不支持 `--system-prompt` 参数 | 升级到 b8500+；或在 OpenWebUI 手动配置 |
| 对话模式 token 速度无法显示 | llama-cli 在独立 PowerShell 进程中运行，启动器无法读取输出 | 服务模式下可正常显示 |
| Windows 中文命令行编码 | Windows 默认 GBK 编码，中文 prompt 直接传参会乱码 | 通过临时 UTF-8 文件 + 语言切换解决 |
| 参数保存后需重选模型 | 旧版本问题，已通过 `trace_add` 修复同步 | — |

### 6.2 后续计划

- [ ] 升级 llama.cpp 版本后启用服务模式 system prompt 注入
- [ ] 模型下载管理（Hugging Face / ModelScope 集成）
- [ ] 多模型并行服务（多端口）
- [ ] 对话历史保存与回放
- [ ] 性能基准测试（自动跑 prompt 测速并记录）
- [ ] macOS / Linux 适配

---

## 七、运行依赖

### 7.1 必须

| 依赖 | 用途 |
|------|------|
| Python 3.8+ | 运行时环境 |
| tkinter | GUI 框架（Python 标准库，部分发行版需单独安装） |
| llama.cpp 可执行文件 | `llama-cli.exe` + `llama-server.exe` |

### 7.2 推荐安装

```bash
pip install psutil
```

| 依赖 | 用途 | 缺失时降级行为 |
|------|------|--------------|
| psutil | CPU / 内存实时监控 | 显示"需要 psutil" |
| nvidia-smi | GPU 监控 | GPU/VRAM 显示"—" |

### 7.3 首次运行

1. 把 `llama_launcher.py` 放到模型目录旁边
2. 双击运行，或 `python llama_launcher.py`
3. 首次启动自动生成 `config.json` 和 `models_config.json`
4. 在「编辑 config.json」里填入 llama-cli 和 llama-server 的路径
5. 点「重新扫描」发现模型，开始使用

---

*文档由 Claude 辅助整理，结合实际开发迭代内容生成。*
