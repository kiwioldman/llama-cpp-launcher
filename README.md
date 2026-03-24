# ⚡ llama launcher

**本地 AI 模型图形化管理器 · Windows**

> 无需命令行，通过图形界面管理 llama.cpp 本地模型的运行、参数调优、API 服务部署与实时监控。

> *(三栏布局：模型管理 · 参数配置 · 实时监控)*

---

## 功能特性

### 🚀 零门槛启动
- 首次运行自动弹出设置向导，引导配置 llama.cpp 路径和模型目录
- 自动扫描 .gguf 模型文件，按模型名称匹配推荐参数
- 参数记忆：调整后保存，下次自动恢复

### 💬 对话模式
- 一键启动 PowerShell 对话窗口
- System Prompt 注入（UTF-8 文件传参，支持中文）
- 支持隐藏 `<think>` 思考过程（PowerShell 脚本层过滤）
- 停止按钮直接终止对话进程

### 🌐 服务模式
- 启动 llama-server，暴露 OpenAI 兼容 API
- 实时日志流，自动检测服务就绪状态
- 一键复制访问地址（浏览器用）/ 带 Token 的 API 地址（OpenWebUI 等客户端用）
- 一键复制 API Key
- 支持停止 / 重启 / 热切换模型

### 🎭 角色与 Prompt 管理
内置 8 个预设角色，**中英文双语 Prompt 同步显示**：

| 角色 | 适用场景 |
|------|---------|
| 🤖 AI 助手 | 通用对话，干练直接 |
| 🔧 Agent | 任务拆解执行，四步工作流 |
| 🏢 数据中心运维专家 | IDC 故障诊断，含安全警告机制 |
| 📚 百科全书 | 知识查询，客观中立 |
| 💻 代码专家 | 编程开发，直接给可运行代码 |
| 🌐 翻译专家 | 多语言互译，信达雅三原则 |
| 🔬 数据分析师 | 数据分析，含 Python/SQL 代码 |
| 📝 写作助手 | 文案创作润色 |

- 角色 Prompt 可在界面编辑后保存回 `config.json`
- 支持模型专属 Prompt，优先级高于全局配置
- 底部提供「📋 复制中文」「📋 复制英文」按钮，方便粘贴到 OpenWebUI 等前端

### 📊 实时监控仪表盘
- **设备信息**：自动扫描 CPU 型号/核心数、内存规格、GPU 型号/显存，缓存到配置文件
- **实时监控**（每秒刷新）：CPU 利用率 + 频率 · 内存占用 · GPU 利用率 + 温度 · VRAM 占用
- **Token 速度**：从服务日志实时解析，显示当前速度 + 峰值 + 累计输出 Token 数
- **模型加载进度条**：实时显示加载百分比，就绪后自动锁定 100%

### 🛡️ 稳定性
- 配置文件原子写入（防写入中断损坏）
- 进程真实退出检测（防误报服务停止）
- `☠ 强制终止`：taskkill + psutil 双重保障
- 关闭窗口时检测服务状态，防止误关
- 运行日志自动归档到 `logs/` 目录，保留最近 10 份

---

## 安装与使用

### 环境要求

| 依赖 | 说明 |
|------|------|
| Windows 10/11 | 仅支持 Windows |
| Python 3.8+ | [下载](https://www.python.org/downloads/) |
| llama.cpp | 需要 `llama-cli.exe` 和 `llama-server.exe` |
| .gguf 模型文件 | 从 HuggingFace / ModelScope 下载 |

### 推荐安装（可选，用于系统监控）

```bash
pip install psutil
```

### 下载与启动

```bash
# 1. 克隆仓库
<<<<<<< HEAD
git clone https://github.com/kiwioldman/llama-cpp-launcher.git
cd llama-cpp-launcher

# 2. 运行（无需安装）
python llama-cpp-launcher.py
=======
git clone https://github.com/你的用户名/llama-launcher.git
cd llama-launcher

# 2. 运行（无需安装）
python llama_launcher.py
>>>>>>> 02c62c5 (feat: 初始发布 llama-ccp-launcher v1.0，图形化微调模型，支持硬件监控)
```

### 首次运行

首次启动会自动弹出设置向导：

```
第 1 步：选择 llama.cpp 目录
         ↓ 点击「🔍 自动检测」或手动浏览
         ↓ 找到 llama-cli.exe ✓

第 2 步：添加模型目录
         ↓ 选择存放 .gguf 文件的目录

第 3 步：点击「✓ 完成，生成配置并启动」
         ↓ 自动生成 config.json + models_config.json
         ↓ 进入主界面
```

---

## llama.cpp 获取

从 [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases) 下载对应版本：

- **NVIDIA GPU**：选 `llama-bXXXX-bin-win-cuda-XX.X-x64.zip`
- **仅 CPU**：选 `llama-bXXXX-bin-win-noavx-x64.zip`

解压后在向导中选择该目录即可。

---

## 模型推荐

| 模型 | 参数量 | 推荐配置 | 适合场景 |
|------|--------|---------|---------|
| Qwen3 8B / 9B | 8-9B | gpu_layers=99, ctx=8192 | 日常对话，全 GPU |
| Qwen3 14B | 14B | gpu_layers=35, ctx=4096 | 均衡性能 |
| Qwen3.5 35B MoE | 35B (3B激活) | gpu_layers=20, ctx=2048 | 高质量，混跑 |
| Phi-4 Mini | 3.8B | gpu_layers=99, ctx=4096 | 快速响应 |
| Llama 3.x 8B | 8B | gpu_layers=99, ctx=8192 | 英文任务 |

> 💡 gpu_layers 不是越高越好。超出显存会溢出到系统内存，反而变慢。

---

## 配置文件说明

程序目录下自动生成两个配置文件：

### `config.json` — 全局配置

```json
{
  "llama_cli_path":    "E:/llama-xxx/llama-cli.exe",
  "llama_server_path": "E:/llama-xxx/llama-server.exe",
  "model_dirs":        ["E:/models"],
  "server": {
    "host": "0.0.0.0",
    "port": 8080,
    "api_keys": { "default": "sk-local-change-me" }
  },
  "roles":    { "🤖 AI助手": "你是..." },
  "roles_en": { "🤖 AI助手": "You are..." },
  "hardware": { "cpu_name": "...", "gpu_name": "..." }
}
```

### `models_config.json` — 模型参数记忆

```json
{
  "_profiles": {
    "qwen-35b-moe": { "_match": ["qwen","35b"], "gpu_layers": 20 }
  },
  "models": {
    "Qwen3.5-9B-Q5_K_M.gguf": {
      "gpu_layers": 97, "ctx": 16128,
      "extra_args": "--reasoning off"
    }
  }
}
```

---

## 与 OpenWebUI 集成

1. 在 llama launcher 中切换到**服务模式**，选择模型，点击**启动服务**
2. 等待加载进度条到 100%，状态显示「✓ 就绪（可以访问）」
3. 点击「🔑 API地址（客户端用）」复制地址
4. 在 OpenWebUI 的「Settings → Connections」中：
   - OpenAI API URL：`http://localhost:8080/v1`
   - API Key：从 llama launcher 服务参数中复制

> 💡 System Prompt 推荐在 OpenWebUI 的模型设置中配置（llama-server b8388 不支持命令行注入）。

---

## 参数说明

| 参数 | 说明 | 推荐值 |
|------|------|-------|
| gpu_layers | GPU 卸载层数 | 视显存决定，不够就降低 |
| threads | CPU 线程数 | P核数 × 2（如 i9：16） |
| ctx | 上下文窗口 | 4096-16384，越大越耗内存 |
| temp | 温度 | 0.35（精准）/ 0.7（均衡）/ 1.0（创意） |
| --reasoning off | 关闭思考模式（Qwen3） | 加入 extra_args |
| --flash-attn | 加速注意力计算 | 加入 extra_args |

---

## 常见问题

**Q: 启动后提示找不到 llama-cli / llama-server？**  
A: 在「⚙ 编辑 config.json」中检查 `llama_cli_path` 和 `llama_server_path` 路径，使用正斜杠 `/`。

**Q: 服务启动后马上停止？**  
A: 查看右栏「服务日志」中的红色错误行。常见原因：端口被占用（改 port）、参数不被支持（检查 extra_args）。

**Q: 35B 模型推理速度很慢（< 2 t/s）？**  
A: 降低 `gpu_layers`（20-25），避免 VRAM 溢出到系统内存。任务管理器中 GPU 专用内存接近上限时需要降低。

**Q: 中文 Prompt 在服务模式传不进去？**  
A: llama-server b8388 不支持 `--system-prompt` 参数。使用界面中的「📋 复制中文」按钮，在 OpenWebUI 中手动粘贴。升级 llama.cpp 到 b8500+ 后可自动传入。

**Q: 系统资源显示「—」？**  
A: 安装 psutil：`pip install psutil`；GPU 显示需要 NVIDIA 驱动。

---

## 开发与贡献

欢迎 PR 和 Issue。主要改进方向：

- [ ] macOS / Linux 适配
- [ ] 模型下载管理（HuggingFace 集成）
- [ ] 升级 llama.cpp 后启用服务模式 System Prompt
- [ ] 多模型并行服务
- [ ] 对话历史保存与回放

### 项目结构

```
llama_launcher.py    # 单文件主程序（约 2900 行）
README.md
LICENSE
CHANGELOG.md
config.json          # 自动生成，不提交到 git
models_config.json   # 自动生成，不提交到 git
logs/                # 自动生成，不提交到 git
```

建议 `.gitignore`：

```gitignore
config.json
models_config.json
logs/
__pycache__/
*.pyc
```

---

## 许可证

[MIT License](LICENSE) — 自由使用、修改、分发。

---

## 致谢

- [llama.cpp](https://github.com/ggerganov/llama.cpp) — 本地模型推理引擎
- [Qwen](https://github.com/QwenLM/Qwen) — 阿里巴巴通义千问模型系列
- 本项目通过 [Claude](https://claude.ai) vibecoding 开发，代码由 AI 生成，需求由人驱动
