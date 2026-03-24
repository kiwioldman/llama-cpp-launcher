#!/usr/bin/env python3
"""
llama_launcher.py  —  本地 AI 模型启动器
需求：Windows + RTX5060 8G + i9-14900HX + 32GB RAM
依赖：Python 3.8+  标准库只（tkinter / subprocess / threading / json）
"""

import os
import sys
import json
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  路径 & 常量
# ═══════════════════════════════════════════════════════════════
BASE_DIR        = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH     = BASE_DIR / "config.json"
MODELS_CFG_PATH = BASE_DIR / "models_config.json"
LOGS_DIR        = BASE_DIR / "logs"
PROMPT_SEP      = "─────────────── EN ───────────────"  # 中英文分隔线


def _ensure_logs_dir():
    """确保日志目录存在"""
    LOGS_DIR.mkdir(exist_ok=True)


def _new_log_path(prefix: str, model_name: str = "") -> Path:
    """生成新的日志文件路径"""
    _ensure_logs_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = model_name.replace(" ", "_").replace("/", "_")[:30]
    name = f"{prefix}_{ts}_{safe_name}.log" if safe_name else f"{prefix}_{ts}.log"
    return LOGS_DIR / name


def _rotate_logs(prefix: str, keep: int = 10):
    """保留最新 keep 份日志，删除旧的"""
    try:
        logs = sorted(LOGS_DIR.glob(f"{prefix}_*.log"), key=lambda p: p.stat().st_mtime)
        for old in logs[:-keep]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
#  配置 IO
# ═══════════════════════════════════════════════════════════════
def _load_json(path: Path) -> dict:
    try:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # Windows 路径反斜杠容错：把单个 \ 替换为 /
                import re
                fixed = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', '/', raw)
                return json.loads(fixed)
    except Exception as e:
        print(f"[WARN] 读取 {path} 失败: {e}")
    return {}


def _save_json(path: Path, data: dict):
    """原子写入：先写临时文件再替换，防止写入中途崩溃损坏配置"""
    import tempfile
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(tmp_path).replace(path)   # 原子替换
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception as e:
        print(f"[WARN] 写入 {path} 失败: {e}")



# ═══════════════════════════════════════════════════════════════
#  硬件信息扫描（首次运行或硬件变更时执行，结果缓存到 config）
# ═══════════════════════════════════════════════════════════════
def scan_hardware_info() -> dict:
    """扫描本机 CPU / 内存 / GPU 型号及容量，返回结构化字典。
    仅依赖标准库 + psutil（可选）+ nvidia-smi（可选），
    失败时对应字段填 '未知'，不影响程序启动。
    """
    info = {
        "cpu_name":    "未知",
        "cpu_cores":   "",
        "ram_total":   "",
        "ram_sticks":  "",
        "gpu_name":    "未知",
        "gpu_vram":    "",
        "scanned_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # ── CPU ──
    try:
        import subprocess as _sp
        # Windows: wmic cpu get name
        out = _sp.check_output(
            ["wmic", "cpu", "get", "name", "/value"],
            text=True, stderr=_sp.DEVNULL, timeout=5
        )
        for line in out.splitlines():
            if "Name=" in line:
                info["cpu_name"] = line.split("=", 1)[1].strip()
                break
    except Exception:
        pass

    # CPU 核心数
    try:
        import psutil as _ps
        p = _ps.cpu_count(logical=False)
        l = _ps.cpu_count(logical=True)
        info["cpu_cores"] = f"{p}P+{l-p}E 共{l}线程" if p and l else ""
    except Exception:
        pass

    # ── 内存 ──
    try:
        import psutil as _ps
        vm = _ps.virtual_memory()
        info["ram_total"] = f"{vm.total / 1024**3:.1f} GB"
    except Exception:
        pass

    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["wmic", "memorychip", "get",
             "Capacity,Speed,Manufacturer,MemoryType", "/value"],
            text=True, stderr=_sp.DEVNULL, timeout=5
        )
        sticks, cur = [], {}
        for line in out.splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cur[k.strip()] = v.strip()
            elif not line and cur:
                cap = cur.get("Capacity", "")
                spd = cur.get("Speed", "")
                if cap:
                    gb = int(cap) // 1024**3
                    sticks.append(f"{gb}GB" + (f"@{spd}MHz" if spd else ""))
                cur = {}
        if sticks:
            info["ram_sticks"] = "  ".join(sticks)
    except Exception:
        pass

    # ── GPU ──
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["nvidia-smi",
             "--query-gpu=name,memory.total",
             "--format=csv,noheader"],
            text=True, stderr=_sp.DEVNULL, timeout=5
        ).strip()
        if out:
            parts = [x.strip() for x in out.split(",")]
            info["gpu_name"] = parts[0] if parts else "未知"
            if len(parts) > 1:
                mb = parts[1].replace("MiB", "").strip()
                info["gpu_vram"] = f"{int(mb)/1024:.1f} GB" if mb.isdigit() else parts[1]
    except Exception:
        pass

    return info


def get_or_scan_hardware(cfg: dict) -> dict:
    """从 config 读取缓存的硬件信息；若不存在则扫描并写回。"""
    hw = cfg.get("hardware", {})
    if hw.get("cpu_name", "未知") != "未知" and hw.get("gpu_name", "未知") != "未知":
        return hw   # 有缓存，直接返回
    hw = scan_hardware_info()
    cfg["hardware"] = hw
    save_config(cfg)
    return hw

def load_config() -> dict:
    cfg = _load_json(CONFIG_PATH)
    # 补全缺失键
    cfg.setdefault("llama_cli_path",    "llama-cli")
    cfg.setdefault("llama_server_path", "llama-server")
    cfg.setdefault("model_dirs",        [str(BASE_DIR)])
    cfg.setdefault("system_prompt",     DEFAULT_SYSTEM_PROMPT)
    cfg.setdefault("server", {})
    cfg["server"].setdefault("host",     "0.0.0.0")
    cfg["server"].setdefault("port",     8080)
    cfg["server"].setdefault("api_keys", {"default": "sk-local-change-me"})
    cfg["server"].setdefault("slots",    1)
    cfg.setdefault("chat", {"powershell_keep_open": True})
    cfg.setdefault("roles", DEFAULT_ROLES)
    cfg.setdefault("hardware", {})
    return cfg


def save_config(cfg: dict):
    _save_json(CONFIG_PATH, cfg)


def load_models_cfg() -> dict:
    """加载模型配置；文件不存在时返回内置默认值"""
    if MODELS_CFG_PATH.exists():
        return _load_json(MODELS_CFG_PATH)
    return dict(DEFAULT_MODELS_CFG)


def save_models_cfg(mcfg: dict):
    _save_json(MODELS_CFG_PATH, mcfg)


def is_first_run() -> bool:
    """检测是否首次运行（config.json 不存在）"""
    return not CONFIG_PATH.exists()


def create_default_configs(llama_dir: str, model_dirs: list) -> tuple:
    """根据向导输入生成并写入默认配置文件，返回 (cfg, mcfg)"""
    llama_dir = Path(llama_dir)
    cli_path  = str(llama_dir / "llama-cli.exe").replace("\\", "/")
    srv_path  = str(llama_dir / "llama-server.exe").replace("\\", "/")

    cfg = {
        "_comment": "llama_launcher 配置文件 — 路径用正斜杠 /",
        "llama_cli_path":    cli_path,
        "llama_server_path": srv_path,
        "model_dirs":        [str(d) for d in model_dirs],
        "system_prompt":     DEFAULT_SYSTEM_PROMPT,
        "server": {
            "host": "0.0.0.0", "port": 8080,
            "api_keys": {"default": "sk-local-change-me"},
            "slots": 1,
        },
        "chat": {"powershell_keep_open": True},
        "roles":    {k: v for k, v in DEFAULT_ROLES.items()},
        "roles_en": {k: v for k, v in PROMPT_EN.items()
                     if k != "default"},
        "hardware": {},
    }
    mcfg = dict(DEFAULT_MODELS_CFG)

    _save_json(CONFIG_PATH, cfg)
    _save_json(MODELS_CFG_PATH, mcfg)
    return cfg, mcfg


# ═══════════════════════════════════════════════════════════════
#  内置默认配置（首次运行时写入文件）
# ═══════════════════════════════════════════════════════════════
DEFAULT_MODELS_CFG = {
    "_comment": "各模型参数记忆文件 — 由程序自动维护，也可手动编辑",
    "_profiles": {
        "_comment": "内置参数模板，按模型文件名关键词自动匹配",
        "qwen-35b-moe": {
            "_match": ["qwen", "35b"],
            "_desc": "Qwen 35B MoE — GPU/CPU 混跑",
            "gpu_layers": 20, "threads": 12, "ctx": 2048, "batch": 512,
            "temp": 0.35, "top_p": 0.7, "top_k": 40, "repeat_penalty": 1.08,
            "stop_tokens": ["<|endoftext|>"],
            "extra_args": "--chat-template chatml --reasoning off",
        },
        "qwen-14b": {
            "_match": ["qwen", "14b"],
            "_desc": "Qwen 14B — GPU 部分卸载",
            "gpu_layers": 35, "threads": 12, "ctx": 8192, "batch": 512,
            "temp": 0.35, "top_p": 0.7, "top_k": 40, "repeat_penalty": 1.08,
            "stop_tokens": [], "extra_args": "--chat-template chatml",
        },
        "qwen-7b": {
            "_match": ["qwen", "7b"],
            "_desc": "Qwen 7B — GPU 全卸载",
            "gpu_layers": 99, "threads": 8, "ctx": 8192, "batch": 512,
            "temp": 0.35, "top_p": 0.7, "top_k": 40, "repeat_penalty": 1.08,
            "stop_tokens": [], "extra_args": "--chat-template chatml",
        },
        "llama-70b": {
            "_match": ["llama", "70b"],
            "_desc": "Llama 3.x 70B — CPU+GPU 混跑",
            "gpu_layers": 15, "threads": 16, "ctx": 4096, "batch": 512,
            "temp": 0.6, "top_p": 0.9, "top_k": 50, "repeat_penalty": 1.1,
            "stop_tokens": ["<|eot_id|>"], "extra_args": "--chat-template llama3",
        },
        "llama-8b": {
            "_match": ["llama", "8b"],
            "_desc": "Llama 3.x 8B — GPU 全卸载",
            "gpu_layers": 99, "threads": 8, "ctx": 8192, "batch": 512,
            "temp": 0.6, "top_p": 0.9, "top_k": 50, "repeat_penalty": 1.1,
            "stop_tokens": ["<|eot_id|>"], "extra_args": "--chat-template llama3",
        },
        "phi": {
            "_match": ["phi"],
            "_desc": "Microsoft Phi 系列",
            "gpu_layers": 99, "threads": 8, "ctx": 4096, "batch": 512,
            "temp": 0.7, "top_p": 0.9, "top_k": 50, "repeat_penalty": 1.08,
            "stop_tokens": [], "extra_args": "",
        },
        "deepseek": {
            "_match": ["deepseek"],
            "_desc": "DeepSeek 系列",
            "gpu_layers": 20, "threads": 10, "ctx": 4096, "batch": 512,
            "temp": 0.6, "top_p": 0.85, "top_k": 40, "repeat_penalty": 1.05,
            "stop_tokens": ["User:", "<|EOT|>"], "extra_args": "",
        },
        "mistral": {
            "_match": ["mistral"],
            "_desc": "Mistral / Mixtral 系列",
            "gpu_layers": 99, "threads": 8, "ctx": 8192, "batch": 512,
            "temp": 0.7, "top_p": 0.9, "top_k": 50, "repeat_penalty": 1.08,
            "stop_tokens": ["[INST]", "[/INST]"],
            "extra_args": "--chat-template mistral",
        },
        "default": {
            "_match": [],
            "_desc": "通用默认（无法识别模型名时使用）",
            "gpu_layers": 0, "threads": 8, "ctx": 4096, "batch": 512,
            "temp": 0.7, "top_p": 0.9, "top_k": 50, "repeat_penalty": 1.08,
            "stop_tokens": [], "extra_args": "",
        },
    },
    "models": {},
}

# ═══════════════════════════════════════════════════════════════
#  默认 System Prompt
# ═══════════════════════════════════════════════════════════════
DEFAULT_SYSTEM_PROMPT = (
    "你是一个高效、精准的本地 AI 助手。\n\n"
    "【回答规则】\n"
    "1. 直接给出结论，不要在开头重复用户的问题。\n"
    "2. 复杂问题采用「结论 → 理由 → 步骤」结构，每层不超过三点。\n"
    "3. 禁止使用「让我想想」「那么……所以……但是……」这类自我循环的过渡句。\n"
    "4. 如果不确定，直接说「我不确定，建议你验证一下」，不要编造答案。\n"
    "5. 默认使用中文回复，除非用户明确要求其他语言。\n"
    "6. 回答完毕后停止，不要追加「你还有什么问题吗？」等收尾语。\n\n"
    "【格式规则】\n"
    "- 短问题：1-3 句话，不用列表。\n"
    "- 中等问题：可用编号列表，但不超过 5 条。\n"
    "- 代码类问题：直接给可运行的代码块，注释只写关键处。"
)

# ═══════════════════════════════════════════════════════════════
#  预设角色
# ═══════════════════════════════════════════════════════════════
DEFAULT_ROLES = {
    "🤖 AI助手": (
        "你是一个高效、精准的本地 AI 助手。\n\n"
        "【回答规则】\n"
        "1. 直接给出结论，不要在开头重复用户的问题。\n"
        "2. 复杂问题采用「结论 → 理由 → 步骤」结构，每层不超过三点。\n"
        "3. 禁止使用「让我想想」「那么……所以……但是……」这类自我循环的过渡句。\n"
        "4. 如果不确定，直接说「我不确定，建议你验证一下」，不要编造答案。\n"
        "5. 默认使用中文回复，除非用户明确要求其他语言。\n"
        "6. 回答完毕后停止，不要追加「你还有什么问题吗？」等收尾语。\n\n"
        "【格式规则】\n"
        "- 短问题：1-3 句话，不用列表。\n"
        "- 中等问题：可用编号列表，但不超过 5 条。\n"
        "- 代码类问题：直接给可运行的代码块，注释只写关键处。"
    ),
    "🔧 Agent": (
        "你是一个任务执行型 AI Agent。\n\n"
        "【工作方式】\n"
        "1. 收到任务后先输出「任务拆解」：列出 2-5 个子步骤。\n"
        "2. 按步骤逐一执行，每步完成后标注「✓ 步骤N完成」。\n"
        "3. 遇到需要用户确认的决策点，明确列出选项，等待指令再继续。\n"
        "4. 最终输出「任务完成摘要」：已完成的内容、结果、下一步建议。\n\n"
        "【约束】\n"
        "- 不主动扩展任务范围，严格按用户指令执行。\n"
        "- 不确定时暂停并询问，不要自行假设。"
    ),
    "🏢 数据中心运维专家": (
        "你是一位拥有 20 年经验的动力能源与暖通空调（HVAC）运维专家，"
        "熟悉工业制冷、中央空调、冷水机组、冷却塔、UPS 电源、柴油发电机等系统。\n\n"
        "【回答原则】\n"
        "1. 优先给出安全操作提示，涉及高压、制冷剂等危险操作必须先警告。\n"
        "2. 故障诊断按「现象 → 可能原因（由简到繁）→ 排查步骤」结构输出。\n"
        "3. 给出具体参数范围（如压力值、温度阈值、电流标准）而不是模糊描述。\n"
        "4. 如涉及特定品牌设备，说明通用原理，并提示查阅该品牌手册。\n"
        "5. 专业术语附英文缩写（如：冷冻水 CHW、冷却水 CW）。"
    ),
    "📚 百科全书": (
        "你是一部百科全书式的知识助手，覆盖科学、历史、地理、文化、技术等所有领域。\n\n"
        "【回答原则】\n"
        "1. 先给出核心定义（1-2 句），再展开背景、原理或历史。\n"
        "2. 涉及有争议的话题，客观呈现主流观点，不表达个人立场。\n"
        "3. 给出可供延伸阅读的关键词或领域方向（不虚构来源）。\n"
        "4. 数据和年份尽量精确，不确定时明确标注「约」或「存疑」。\n"
        "5. 回答长度与问题深度匹配：简单问题简短回答，复杂问题系统阐述。"
    ),
    "💻 代码专家": (
        "你是一位全栈代码专家，精通 Python、JavaScript/TypeScript、C/C++、"
        "Rust、Go、Shell 等语言，熟悉主流框架和系统设计。\n\n"
        "【回答原则】\n"
        "1. 直接给出可运行的代码，不写无用的铺垫。\n"
        "2. 代码注释只写关键逻辑，不注释显而易见的内容。\n"
        "3. 默认使用最新稳定版语法，如用到特定版本特性则注明。\n"
        "4. 给出代码后简要说明：做了什么、关键设计决策、潜在注意事项。\n"
        "5. 发现用户代码有 bug 或低效写法，直接指出并给出改进版本。\n\n"
        "【格式】代码块必须标注语言，多方案时先给推荐方案。"
    ),
    "🌐 翻译专家": (
        "你是一位专业翻译，精通中英日韩法德等多语言互译。\n\n"
        "【工作方式】\n"
        "1. 用户直接发送文本即开始翻译，无需额外说明。\n"
        "2. 自动判断源语言，默认译为中文；若原文是中文则译为英文。\n"
        "3. 专业术语保留原文并在括号内注明译文。\n"
        "4. 翻译完成后，如原文存在语法错误，在译文后用【注】标出。\n"
        "5. 不对原文内容做补充或删减，忠实原意。"
    ),
}
# ═══════════════════════════════════════════════════════════════
#  英文 Prompt（服务模式传参，避免中文编码问题）
# ═══════════════════════════════════════════════════════════════
PROMPT_EN = {
    "default": (
        "You are an efficient and precise local AI assistant. "
        "Reply in Chinese by default. "
        "Give conclusions directly without repeating the question. "
        "For complex questions use: Conclusion -> Reason -> Steps, max 3 points per level. "
        "Avoid filler phrases. If uncertain say so. Stop after answering, no closing remarks."
    ),
    "🤖 AI助手": (
        "You are an efficient and precise local AI assistant. Reply in Chinese by default. "
        "Rules: 1. Give the conclusion directly; do not repeat the question. "
        "2. For complex questions use Conclusion -> Reason -> Steps, max 3 points per level. "
        "3. Avoid self-looping filler phrases. "
        "4. If uncertain say so directly; never fabricate. "
        "5. Stop after answering; no closing remarks. "
        "Format: short questions 1-3 sentences; medium questions numbered list up to 5; "
        "code questions runnable code blocks with minimal comments."
    ),
    "🔧 Agent": (
        "You are a task-execution AI Agent. Workflow: "
        "Step 1 - restate goal in one sentence. "
        "Step 2 - list 2-5 sub-tasks as [ ] items. "
        "Step 3 - execute each, mark [Done], at decision points list options and wait. "
        "Step 4 - output summary: completed items / result / next steps. "
        "Constraints: no scope expansion; pause when uncertain; describe before executing."
    ),
    "🏢 数据中心运维专家": (
        "You are a data center operations expert with 15 years experience ensuring 7x24 uptime. "
        "Expertise: switching power supplies, battery banks (lead-acid/lithium), UPS, "
        "precision AC (CRAC/CRAH), chillers, chilled water systems, cold/hot aisle containment, "
        "diesel generators (EPS), PDU/RPP, DCIM, fire suppression. "
        "Rules: 1. Prepend [WARNING] for HV>36V, battery short-circuit, refrigerant handling. "
        "2. Fault structure: Alert->Causes(high-to-low probability)->Steps->Resolution->Prevention. "
        "3. Give specific values: V, A, degC, mOhm, PUE. "
        "4. Note vendor differences; refer to vendor manual for specifics. "
        "Benchmarks: -48VDC supply; lead-acid float 2.23-2.27V/cell; LFP 2.5-3.65V; "
        "UPS EOD 1.75V/cell; CRAC supply 18-21C return<=35C; room 18-27C 40-60%RH; PUE<=1.4. "
        "Reply in Chinese."
    ),
    "📚 百科全书": (
        "You are an encyclopedic assistant covering all fields. "
        "Structure: 1. Core definition (1-2 sentences). 2. Background and principles. "
        "3. Keywords for further reading (no fabricated sources). "
        "Present mainstream views objectively; mark uncertain data as approximate or disputed; "
        "use analogies; append original term in parentheses for proper nouns. Reply in Chinese."
    ),
    "💻 代码专家": (
        "You are a senior full-stack engineer proficient in Python, JS/TS, C/C++, Rust, Go, Bash. "
        "Rules: 1. Provide complete runnable code immediately, no preamble. "
        "2. Comment only critical logic. 3. Use latest stable syntax; note version requirements. "
        "4. After code: what it does (1 line), design decisions (1-3), caveats. "
        "5. Fix bugs/security issues/inefficiencies in user code. "
        "Tag code blocks with language; label recommended vs alternative solutions; "
        "distinguish Linux vs Windows commands. Never write pseudocode unless asked."
    ),
    "🌐 翻译专家": (
        "You are a professional translator fluent in Chinese, English, Japanese, Korean, French, German, Spanish. "
        "Start translating immediately when user sends text. "
        "Auto-detect: translate non-Chinese to Chinese, Chinese to English. "
        "User may prefix target language: 'Translate to Japanese: ...'. "
        "Standards: faithful (no additions/omissions), fluent (natural target language), precise. "
        "Preserve technical terms with translation in parentheses. "
        "Note grammar errors with [Note] after translation. "
        "For ambiguous text provide 2 translations with interpretation notes."
    ),
    "🔬 数据分析师": (
        "You are a data analysis expert proficient in Python (pandas/numpy/matplotlib), SQL, Excel. "
        "Workflow: describe data first (size, fields, quality); clarify core question; "
        "lead with conclusions then data; suggest chart types (line=trend, bar/pie=proportion, "
        "histogram=distribution, scatter=correlation). "
        "Provide complete runnable code. Report: Background->Overview->Findings(3-5)->Recommendations. "
        "Reply in Chinese."
    ),
    "📝 写作助手": (
        "You are a professional writing assistant for business copy, reports, emails, and polishing. "
        "Rules: identify target audience first; provide outline before expanding long pieces; "
        "remove redundant words; preserve author's original intent when polishing; "
        "provide 2-3 alternatives for titles, openings, closings. "
        "Polishing mode: ~~strikethrough~~ for deletions, **bold** for additions. Reply in Chinese."
    ),
}


def get_prompt_en(zh_prompt: str, role_name: str = "", cfg: dict = None) -> str:
    """
    返回英文 prompt 用于服务模式命令行传参。
    优先级：config.json roles_en -> 内置 PROMPT_EN -> 纯ASCII直接用 -> 默认
    """
    cfg_en = (cfg or {}).get("roles_en", {})
    if role_name:
        if role_name in cfg_en:
            return cfg_en[role_name]
        if role_name in PROMPT_EN:
            return PROMPT_EN[role_name]
    try:
        zh_prompt.encode("ascii")
        return zh_prompt
    except UnicodeEncodeError:
        pass
    # 按内容前60字匹配
    for name in list(cfg_en.keys()) + list(PROMPT_EN.keys()):
        if name == "default":
            continue
        zh = ((cfg or {}).get("roles", {}).get(name)
              or DEFAULT_ROLES.get(name, ""))
        if zh and zh_prompt.strip()[:60] == zh[:60]:
            return cfg_en.get(name) or PROMPT_EN.get(name, "")
    return PROMPT_EN["default"]


# ═══════════════════════════════════════════════════════════════
#  模型扫描 & 参数匹配
# ═══════════════════════════════════════════════════════════════
def scan_models(dirs: list) -> list:
    found = []
    for d in dirs:
        d = str(d).strip()
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".gguf"):
                    found.append(os.path.join(root, f))
    return sorted(found)


def match_profile(model_name: str, mcfg: dict) -> dict:
    """
    优先级：
    1. models_config.json → models 区域（上次保存的参数）
    2. models_config.json → _profiles 区域（按关键词匹配）
    3. 硬编码默认值
    """
    n = model_name.lower()

    # 1. 已有记忆
    saved = mcfg.get("models", {}).get(model_name)
    if saved:
        return dict(saved)

    # 2. profiles 匹配
    profiles = mcfg.get("_profiles", {})
    for key, p in profiles.items():
        if key.startswith("_") or key == "default":
            continue
        kws = p.get("_match", [])
        if kws and all(k in n for k in kws):
            return _strip_meta(dict(p))

    # 3. 默认
    default = profiles.get("default", {})
    return _strip_meta(dict(default)) if default else _hardcoded_default()


def _strip_meta(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _hardcoded_default() -> dict:
    return {
        "gpu_layers": 0, "threads": 8, "ctx": 4096, "batch": 512,
        "temp": 0.70, "top_p": 0.90, "top_k": 50, "repeat_penalty": 1.08,
        "stop_tokens": [], "extra_args": "",
    }


def save_model_params(model_name: str, params: dict, mcfg: dict):
    mcfg.setdefault("models", {})[model_name] = dict(params)
    save_models_cfg(mcfg)


# ═══════════════════════════════════════════════════════════════
#  命令构建
# ═══════════════════════════════════════════════════════════════
def build_chat_cmd(cfg: dict, model_path: str, params: dict) -> list:
    """返回命令列表，system prompt 不再放入命令行（避免中文乱码）"""
    exe = cfg.get("llama_cli_path", "llama-cli")
    cmd = [
        exe,
        "-m",               model_path,
        "-c",               str(params["ctx"]),
        "-t",               str(params["threads"]),
        "--n-gpu-layers",   str(params["gpu_layers"]),
        "-b",               str(params["batch"]),
        "--temp",           f"{params['temp']:.2f}",
        "--top-p",          f"{params['top_p']:.2f}",
        "--top-k",          str(params["top_k"]),
        "--repeat-penalty", f"{params['repeat_penalty']:.2f}",
        "-cnv",
    ]
    for s in params.get("stop_tokens", []):
        if s.strip():
            cmd += ["--reverse-prompt", s.strip()]
    extra = params.get("extra_args", "").strip()
    if extra:
        cmd += extra.split()
    return cmd


def build_server_cmd(cfg: dict, model_path: str, params: dict,
                     host: str, port: int, api_key: str, slots: int,
                     system_prompt: str = "", role_name: str = "") -> list:
    exe = cfg.get("llama_server_path", "llama-server")
    cmd = [
        exe,
        "-m",               model_path,
        "-c",               str(params["ctx"]),
        "-t",               str(params["threads"]),
        "--n-gpu-layers",   str(params["gpu_layers"]),
        "-b",               str(params["batch"]),
        "--temp",           f"{params['temp']:.2f}",
        "--top-p",          f"{params['top_p']:.2f}",
        "--top-k",          str(params["top_k"]),
        "--repeat-penalty", f"{params['repeat_penalty']:.2f}",
        "--host",           host,
        "--port",           str(port),
    ]
    # llama-server b8388 不支持命令行注入 system prompt
    # 请在 OpenWebUI 等前端的 System Prompt 设置里配置
    # system_prompt 参数保留供未来版本使用
    # --parallel 控制并发槽位数
    if slots and slots > 0:
        cmd += ["--parallel", str(slots)]
    if api_key.strip():
        cmd += ["--api-key", api_key.strip()]
    extra = params.get("extra_args", "").strip()
    if extra:
        cmd += extra.split()
    return cmd


def cmd_to_display(cmd: list) -> str:
    """把命令列表格式化为可读字符串"""
    parts = []
    i = 0
    while i < len(cmd):
        if cmd[i].startswith("-") and i + 1 < len(cmd) and not cmd[i + 1].startswith("-"):
            parts.append(f"{cmd[i]} {cmd[i+1]}")
            i += 2
        else:
            parts.append(cmd[i])
            i += 1
    return parts[0] + " \\\n    " + " \\\n    ".join(parts[1:]) if parts else ""


# ═══════════════════════════════════════════════════════════════
#  启动逻辑
# ═══════════════════════════════════════════════════════════════
def launch_chat_powershell(cmd: list, keep_open: bool):
    """在新 PowerShell 窗口中启动对话模式"""
    def q(s):
        return f'"{s}"' if (" " in s or "\\" in s) else s

    inner = " ".join(q(c) for c in cmd)
    # 转义 PowerShell 内部双引号
    inner_ps = inner.replace('"', '`"')

    if keep_open:
        ps_args = f'-NoExit -Command "{inner_ps}"'
    else:
        ps_args = f'-Command "{inner_ps}"'

    subprocess.Popen(
        ["powershell.exe", "-NoLogo", *ps_args.split(" ", 2)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )



# ═══════════════════════════════════════════════════════════════
#  首次运行向导
# ═══════════════════════════════════════════════════════════════
class FirstRunWizard(tk.Toplevel):
    """首次运行向导：引导用户配置 llama.cpp 路径和模型目录。
    完成后写入 config.json + models_config.json，
    并设置 self.completed = True。
    """

    C = {
        "bg":     "#0d1117",
        "panel":  "#161b22",
        "border": "#30363d",
        "dark":   "#090c10",
        "accent": "#3fb950",
        "blue":   "#58a6ff",
        "amber":  "#d29922",
        "red":    "#f85149",
        "text":   "#e6edf3",
        "muted":  "#7d8590",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.title("llama launcher — 初始设置向导")
        self.geometry("640x520")
        self.minsize(580, 460)
        self.configure(bg=self.C["bg"])
        self.resizable(True, True)
        self.grab_set()   # 模态

        self.completed  = False
        self._llama_dir = tk.StringVar()
        self._cli_found = tk.StringVar(value="")
        self._srv_found = tk.StringVar(value="")
        self._model_dirs: list = []

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    # ── 构建 UI ──────────────────────────────────────────────
    def _build(self):
        # 标题
        tk.Label(self, text="⚡  llama launcher  初始设置",
                 font=("Consolas", 16, "bold"),
                 bg=self.C["bg"], fg=self.C["accent"]
                 ).pack(pady=(20, 4))
        tk.Label(self,
                 text="首次运行需要配置 llama.cpp 路径和模型目录，完成后自动生成配置文件。",
                 font=("Consolas", 9), bg=self.C["bg"], fg=self.C["muted"],
                 wraplength=580).pack(pady=(0, 16))

        # ── 步骤1：llama.cpp 目录 ──
        self._section("步骤 1 / 2  —  选择 llama.cpp 目录")

        row1 = tk.Frame(self, bg=self.C["bg"])
        row1.pack(fill="x", padx=24, pady=(4, 0))
        tk.Entry(row1, textvariable=self._llama_dir,
                 font=("Consolas", 9), bg=self.C["dark"], fg=self.C["text"],
                 insertbackground=self.C["accent"], relief="flat"
                 ).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        tk.Button(row1, text="📂 浏览",
                  font=("Consolas", 9), bg=self.C["border"], fg=self.C["text"],
                  relief="flat", cursor="hand2", padx=10, pady=4,
                  command=self._browse_llama
                  ).pack(side="right")

        # 检测结果提示
        self._detect_lbl = tk.Label(
            self, text="", font=("Consolas", 8),
            bg=self.C["bg"], fg=self.C["muted"], anchor="w")
        self._detect_lbl.pack(fill="x", padx=24, pady=(3, 0))

        tk.Button(self, text="🔍  自动检测（扫描常见安装位置）",
                  font=("Consolas", 8), bg=self.C["panel"], fg=self.C["blue"],
                  relief="flat", cursor="hand2", padx=10, pady=3,
                  command=self._auto_detect
                  ).pack(anchor="w", padx=24, pady=(4, 0))

        # ── 步骤2：模型目录 ──
        self._section("步骤 2 / 2  —  添加模型目录（.gguf 文件所在位置）")

        list_row = tk.Frame(self, bg=self.C["bg"])
        list_row.pack(fill="x", padx=24, pady=(4, 0))
        self._dir_lb = tk.Listbox(
            list_row, font=("Consolas", 9), height=4,
            bg=self.C["dark"], fg=self.C["text"],
            selectbackground=self.C["blue"],
            relief="flat", activestyle="none")
        self._dir_lb.pack(side="left", fill="both", expand=True)
        btn_col = tk.Frame(list_row, bg=self.C["bg"])
        btn_col.pack(side="right", padx=(6, 0))
        tk.Button(btn_col, text="+ 添加",
                  font=("Consolas", 8), bg=self.C["accent"], fg=self.C["dark"],
                  relief="flat", cursor="hand2", padx=8, pady=3,
                  command=self._add_model_dir
                  ).pack(fill="x", pady=(0, 3))
        tk.Button(btn_col, text="− 删除",
                  font=("Consolas", 8), bg=self.C["red"], fg=self.C["dark"],
                  relief="flat", cursor="hand2", padx=8, pady=3,
                  command=self._del_model_dir
                  ).pack(fill="x")

        tk.Label(self, text="提示：可以添加多个目录，程序会递归扫描其中的 .gguf 文件",
                 font=("Consolas", 8), bg=self.C["bg"], fg=self.C["muted"]
                 ).pack(anchor="w", padx=24, pady=(4, 0))

        # ── 底部按钮 ──
        tk.Frame(self, bg=self.C["border"], height=1).pack(
            fill="x", pady=(16, 0))
        btn_row = tk.Frame(self, bg=self.C["bg"])
        btn_row.pack(fill="x", padx=24, pady=12)
        tk.Button(btn_row, text="取消",
                  font=("Consolas", 9), bg=self.C["border"], fg=self.C["text"],
                  relief="flat", cursor="hand2", padx=16, pady=5,
                  command=self._on_cancel
                  ).pack(side="right", padx=(6, 0))
        tk.Button(btn_row, text="✓  完成，生成配置并启动",
                  font=("Consolas", 10, "bold"),
                  bg=self.C["accent"], fg=self.C["dark"],
                  activebackground="#2ea043", activeforeground=self.C["dark"],
                  relief="flat", cursor="hand2", padx=16, pady=6,
                  command=self._finish
                  ).pack(side="right")

    def _section(self, title: str):
        """带颜色的步骤标题"""
        f = tk.Frame(self, bg=self.C["panel"],
                     highlightbackground=self.C["border"], highlightthickness=1)
        f.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(f, text=f"  {title}",
                 font=("Consolas", 9, "bold"),
                 bg=self.C["border"], fg=self.C["blue"],
                 anchor="w", pady=4).pack(fill="x")

    # ── 交互逻辑 ──────────────────────────────────────────────
    def _browse_llama(self):
        d = filedialog.askdirectory(title="选择 llama.cpp 目录（含 llama-cli.exe）")
        if d:
            self._llama_dir.set(d)
            self._check_llama_dir(d)

    def _check_llama_dir(self, d: str):
        """检测目录中是否有 llama-cli.exe 和 llama-server.exe"""
        p = Path(d)
        cli = (p / "llama-cli.exe").exists()
        srv = (p / "llama-server.exe").exists()
        if cli and srv:
            self._detect_lbl.config(
                text="✓ 找到 llama-cli.exe 和 llama-server.exe",
                fg=self.C["accent"])
        elif cli or srv:
            found = "llama-cli.exe" if cli else "llama-server.exe"
            missing = "llama-server.exe" if cli else "llama-cli.exe"
            self._detect_lbl.config(
                text=f"⚠ 找到 {found}，未找到 {missing}（仍可继续）",
                fg=self.C["amber"])
        else:
            self._detect_lbl.config(
                text="✗ 未找到 llama-cli.exe / llama-server.exe，请确认路径",
                fg=self.C["red"])

    def _auto_detect(self):
        """扫描常见路径自动发现 llama.cpp 目录"""
        self._detect_lbl.config(text="正在扫描...", fg=self.C["muted"])
        self.update()

        candidates = []
        # 常见盘符 + 常见目录名
        for drive in ["C:", "D:", "E:", "F:"]:
            for folder in [
                "llama.cpp", "llama-cpp",
                "llama-b*", "llama-*-bin-win*",
            ]:
                import glob
                pattern = f"{drive}/{folder}"
                candidates += glob.glob(pattern)
                candidates += glob.glob(f"{drive}/*/llama-cli.exe")
                candidates += glob.glob(f"{drive}/*/*/llama-cli.exe")

        found_dirs = set()
        for c in candidates:
            p = Path(c)
            if p.is_dir() and (p / "llama-cli.exe").exists():
                found_dirs.add(str(p))
            elif p.is_file() and p.name == "llama-cli.exe":
                found_dirs.add(str(p.parent))

        if found_dirs:
            # 选最新的（按名称排序取最后）
            best = sorted(found_dirs)[-1]
            self._llama_dir.set(best)
            self._check_llama_dir(best)
        else:
            self._detect_lbl.config(
                text="未自动发现，请手动选择目录", fg=self.C["amber"])

    def _add_model_dir(self):
        d = filedialog.askdirectory(title="选择模型目录（含 .gguf 文件）")
        if d and d not in self._model_dirs:
            self._model_dirs.append(d)
            self._dir_lb.insert("end", f"  {d}")

    def _del_model_dir(self):
        sel = self._dir_lb.curselection()
        if sel:
            idx = sel[0]
            self._dir_lb.delete(idx)
            self._model_dirs.pop(idx)

    def _finish(self):
        llama_dir = self._llama_dir.get().strip()
        if not llama_dir:
            messagebox.showwarning("提示", "请先选择 llama.cpp 目录")
            return
        if not self._model_dirs:
            if not messagebox.askyesno(
                "提示", "未添加模型目录，仍然继续？\n（可在主界面的「模型目录」里添加）"
            ):
                return
        try:
            create_default_configs(llama_dir, self._model_dirs)
            self.completed = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"写入配置文件失败：{e}")

    def _on_cancel(self):
        if messagebox.askyesno("退出", "取消设置将退出程序，确认吗？"):
            self.completed = False
            self.master.destroy()   # 退出整个程序


# ═══════════════════════════════════════════════════════════════
#  主界面
# ═══════════════════════════════════════════════════════════════
class LlamaLauncher(tk.Tk):

    # ── 配色方案（工业终端风 · 深色）──────────────────────────
    C = {
        "bg":       "#0e1116",
        "panel":    "#161b22",
        "border":   "#30363d",
        "dark":     "#090c10",
        "accent":   "#3fb950",   # 绿
        "blue":     "#58a6ff",   # 蓝
        "amber":    "#d29922",   # 琥珀（警告）
        "red":      "#f85149",   # 红（停止/错误）
        "text":     "#e6edf3",
        "muted":    "#7d8590",
        "tag_chat": "#1f6feb",   # 对话模式标签底色
        "tag_srv":  "#388bfd",
    }

    def __init__(self):
        super().__init__()
        self.title("llama launcher")
        self.geometry("1400x820")
        self.minsize(1100, 680)
        self.configure(bg=self.C["bg"])
        self.resizable(True, True)

        # ── 数据 ──
        self.cfg      = load_config()
        self.mcfg     = load_models_cfg()
        self.models:  list  = []
        self.cur_params: dict = {}
        self.cur_profile_key  = tk.StringVar(value="—")

        # 服务进程
        self._server_proc:  subprocess.Popen | None = None
        self._server_thread: threading.Thread | None = None
        self._server_running = False
        self._tip_win = None
        self._log_file = None      # 当前服务日志文件句柄
        self._log_path: Path | None = None   # 日志文件路径

        # ── 参数变量 ──
        self._gpu     = tk.IntVar(value=0)
        self._threads = tk.IntVar(value=8)
        self._ctx     = tk.IntVar(value=4096)
        self._batch   = tk.IntVar(value=512)
        self._temp    = tk.DoubleVar(value=0.70)
        self._top_p   = tk.DoubleVar(value=0.90)
        self._top_k   = tk.IntVar(value=50)
        self._rep     = tk.DoubleVar(value=1.08)
        self._stop    = tk.StringVar(value="")
        self._extra   = tk.StringVar(value="")

        # 服务参数
        self._srv_host    = tk.StringVar(value=self.cfg["server"]["host"])
        self._srv_port    = tk.IntVar(value=self.cfg["server"]["port"])
        self._srv_apikey  = tk.StringVar(value=list(self.cfg["server"]["api_keys"].values())[0])
        self._srv_slots   = tk.IntVar(value=self.cfg["server"].get("slots", 1))

        # 模式
        self._mode     = tk.StringVar(value="chat")   # "chat" | "server"
        self._thinking = tk.BooleanVar(value=False)   # 是否开启思考模式
        self._cur_model_name  = ""   # 当前选中模型文件名
        self._srv_cur_model   = ""   # 当前服务中的模型名
        self._cur_role_name   = ""   # 当前角色名（用于EN prompt匹配）
        self._hide_think    = tk.BooleanVar(value=False)
        self._prompt_lang   = tk.StringVar(value="zh")  # zh / en / none

        # 监控面板
        self._monitor_running = False
        self._monitor_thread  = None
        self._srv_load_pct    = 0       # 模型加载百分比
        self._srv_ready       = False   # 服务就绪标志
        import queue
        self._log_queue       = queue.Queue()  # 日志行缓冲队列

        self._build_ui()
        self.after(200, self._do_scan)
        self.after(500, self._init_hardware_info)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────────────────────────────────
    #  UI 构建
    # ──────────────────────────────────────────────────────────
    def _build_ui(self):
        self._style_ttk()

        # 顶部 bar
        self._build_topbar()
        tk.Frame(self, bg=self.C["border"], height=1).pack(fill="x")

        # 主体：三栏布局
        body = tk.Frame(self, bg=self.C["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=8)

        # 左栏：模型选择 + 命令预览
        left = tk.Frame(body, bg=self.C["bg"], width=550)
        left.pack(side="left", fill="both", padx=(0, 6))
        left.pack_propagate(False)

        # 中栏：参数配置 + Prompt
        mid = tk.Frame(body, bg=self.C["bg"], width=420)
        mid.pack(side="left", fill="both", padx=(0, 6))
        mid.pack_propagate(False)

        # 右栏：监控面板（自适应剩余宽度）
        right = tk.Frame(body, bg=self.C["bg"])
        right.pack(side="left", fill="both", expand=True)

        self._build_left(left)
        self._build_right(mid)
        self._build_monitor(right)

        # 状态栏
        self._statusbar = tk.Label(
            self, text="  就绪", font=("Consolas", 10),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w", pady=4)
        self._statusbar.pack(fill="x", side="bottom")

    def _build_topbar(self):
        bar = tk.Frame(self, bg=self.C["dark"], pady=0)
        bar.pack(fill="x")
        tk.Label(bar, text="  ⚡ llama launcher",
                 font=("Consolas", 14, "bold"),
                 bg=self.C["dark"], fg=self.C["accent"], pady=9
                 ).pack(side="left")
        tk.Label(bar, text="本地 AI 模型管理器  ·  Windows",
                 font=("Consolas", 10),
                 bg=self.C["dark"], fg=self.C["muted"]
                 ).pack(side="left", padx=10)
        # 右侧：设置按钮
        self._btn(bar, "⚙ 编辑 config.json", self._open_config,
                  small=True).pack(side="right", padx=8, pady=6)
        self._btn(bar, "📂 日志目录", self._open_logs_dir,
                  small=True).pack(side="right", pady=6)
        self._btn(bar, "🖥 硬件信息", self._rescan_hardware,
                  small=True).pack(side="right", padx=(0,4), pady=6)
        self._btn(bar, "↻ 重新扫描", self._do_scan,
                  small=True, accent=True).pack(side="right", pady=6)
        tk.Button(
            bar, text="☠ 终止所有llama",
            font=("Consolas", 8, "bold"),
            bg="#2d1010", fg=self.C["red"],
            activebackground=self.C["red"], activeforeground=self.C["dark"],
            relief="flat", cursor="hand2", padx=8, pady=3,
            command=self._kill_all_llama
        ).pack(side="right", padx=(0, 6), pady=6)

    def _build_left(self, p):
        # ── 模型目录 ──
        card = self._card(p, "模型目录")
        df = tk.Frame(card, bg=self.C["panel"])
        df.pack(fill="x", padx=8, pady=(2, 6))
        self._dir_lb = tk.Listbox(
            df, font=("Consolas", 10), height=2,
            bg=self.C["dark"], fg=self.C["text"],
            selectbackground=self.C["blue"], selectforeground=self.C["dark"],
            relief="flat", activestyle="none")
        self._dir_lb.pack(side="left", fill="both", expand=True)
        for d in self.cfg.get("model_dirs", []):
            self._dir_lb.insert("end", d)
        bf = tk.Frame(df, bg=self.C["panel"])
        bf.pack(side="right", padx=(4, 0))
        self._btn(bf, "+ 添加", self._add_dir, small=True).pack(pady=1)
        self._btn(bf, "− 删除", self._del_dir, small=True, danger=True).pack(pady=1)

        # ── 模型列表 ──
        card2 = self._card(p, "发现的模型", expand=False)
        mf = tk.Frame(card2, bg=self.C["panel"])
        mf.pack(fill="x", expand=False, padx=8, pady=(2, 4))
        sb = ttk.Scrollbar(mf, orient="vertical", style="Vertical.TScrollbar")
        self._mlb = tk.Listbox(
            mf, font=("Consolas", 10), height=5,
            bg=self.C["dark"], fg=self.C["text"],
            selectbackground=self.C["accent"], selectforeground=self.C["dark"],
            relief="flat", activestyle="none",
            yscrollcommand=sb.set, exportselection=False)
        sb.config(command=self._mlb.yview)
        self._mlb.pack(side="left", fill="both", expand=True)  # height controlled by listbox height
        sb.pack(side="right", fill="y")
        self._mlb.bind("<<ListboxSelect>>", self._on_model_select)

        self._mcount_lbl = tk.Label(
            card2, text="共 0 个模型", font=("Consolas", 9),
            bg=self.C["panel"], fg=self.C["muted"], anchor="e")
        self._mcount_lbl.pack(fill="x", padx=8, pady=(0, 4))

        # ── 命令预览 ──
        card3 = self._card(p, "命令预览")
        self._preview = tk.Text(
            card3, font=("Consolas", 9), height=4,
            bg=self.C["dark"], fg=self.C["muted"],
            relief="flat", wrap="word", state="disabled", padx=6, pady=4)
        self._preview.pack(fill="x", padx=8, pady=(2, 4))
        self._btn(card3, "📋 复制命令", self._copy_cmd,
                  small=True).pack(anchor="e", padx=8, pady=(0, 6))

        # ── System Prompt 编辑区 ──
        card4 = self._card(p, "System Prompt", expand=True)

        # 角色快捷选择行
        role_outer = tk.Frame(card4, bg=self.C["panel"])
        role_outer.pack(fill="x", padx=8, pady=(4, 2))
        tk.Label(role_outer, text="角色预设：",
                 font=("Consolas", 8), bg=self.C["panel"],
                 fg=self.C["muted"]).pack(side="left")
        role_btn_frame = tk.Frame(role_outer, bg=self.C["panel"])
        role_btn_frame.pack(side="left", fill="x", expand=True)
        role_colors = ["#1a3a4a", "#2a1a4a", "#1a4a2a", "#4a3a1a", "#4a1a2a", "#1a4a4a"]
        for idx, role_name in enumerate(self.cfg.get("roles", DEFAULT_ROLES).keys()):
            color = role_colors[idx % len(role_colors)]
            tk.Button(
                role_btn_frame, text=role_name,
                font=("Consolas", 8), bg=color, fg="#a8d8a8",
                activebackground=self.C["blue"], activeforeground=self.C["dark"],
                relief="flat", cursor="hand2", padx=6, pady=2,
                command=lambda n=role_name: self._load_role(n)
            ).pack(side="left", padx=(0, 3))

        # 来源 + 保存/重置 行
        hdr = tk.Frame(card4, bg=self.C["panel"])
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        self._prompt_src_lbl = tk.Label(
            hdr, text="来源: 全局 config.json",
            font=("Consolas", 8, "italic"),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._prompt_src_lbl.pack(side="left", fill="x", expand=True)
        self._btn(hdr, "💾 保存", self._save_prompt, small=True, accent=True
                  ).pack(side="right")
        self._btn(hdr, "↩ 重置", self._reset_prompt_to_global, small=True
                  ).pack(side="right", padx=(0, 4))

        # 文本编辑框（中英文合一，用分隔线隔开）
        self._prompt_txt = tk.Text(
            card4, font=("Consolas", 9), height=8,
            bg=self.C["dark"], fg=self.C["text"],
            insertbackground=self.C["accent"],
            relief="flat", wrap="word", padx=6, pady=4,
            undo=True)
        self._prompt_txt.pack(fill="both", expand=True, padx=8, pady=(2, 0))
        # 分隔线高亮 tag
        self._prompt_txt.tag_config("sep",
            foreground=self.C["muted"], font=("Consolas", 8))

        # 底部工具行：复制 + 传参语言选择
        bot = tk.Frame(card4, bg=self.C["panel"])
        bot.pack(fill="x", padx=8, pady=(2, 6))

        # 左：复制按钮
        self._btn(bot, "📋 复制中文", self._copy_prompt_zh, small=True
                  ).pack(side="left", padx=(0, 3))
        self._btn(bot, "📋 复制英文", self._copy_prompt_en, small=True
                  ).pack(side="left", padx=(0, 8))

        # 右：传参语言选择
        tk.Label(bot, text="传参语言:",
                 font=("Consolas", 8), bg=self.C["panel"],
                 fg=self.C["muted"]).pack(side="left")
        for val, lbl, clr in [
            ("zh",   "中文", self.C["accent"]),
            ("en",   "英文", self.C["blue"]),
            ("none", "不传", self.C["muted"]),
        ]:
            tk.Radiobutton(
                bot, text=lbl, variable=self._prompt_lang, value=val,
                font=("Consolas", 8), bg=self.C["panel"], fg=clr,
                selectcolor=self.C["dark"],
                activebackground=self.C["panel"], activeforeground=clr,
            ).pack(side="left", padx=(4, 0))

        # 初始加载全局 prompt（中英文合并显示）
        self._load_bilingual_prompt(
            self.cfg.get("system_prompt", ""),
            PROMPT_EN.get("default", ""))
        # 分隔线颜色（在 Text 构建后绑定）
        self._prompt_txt.tag_config("sep",
            foreground=self.C["muted"], font=("Consolas", 8))

    def _build_right(self, p):
        # ── 模式选择 ──
        card0 = self._card(p, "启动模式")
        mf = tk.Frame(card0, bg=self.C["panel"])
        mf.pack(fill="x", padx=8, pady=(4, 8))
        for val, label, color in [
            ("chat",   "💬  对话模式  ( PowerShell )", self.C["accent"]),
            ("server", "🌐  服务模式  ( API Server )", self.C["blue"]),
        ]:
            rb = tk.Radiobutton(
                mf, text=label, variable=self._mode, value=val,
                font=("Consolas", 10, "bold"),
                bg=self.C["panel"], fg=color,
                selectcolor=self.C["dark"],
                activebackground=self.C["panel"], activeforeground=color,
                command=self._on_mode_change)
            rb.pack(anchor="w", pady=2)

        # ── 参数配置 ──
        card1 = self._card(p, "推理参数")
        self._profile_lbl = tk.Label(
            card1, textvariable=self.cur_profile_key,
            font=("Consolas", 9, "italic"),
            bg=self.C["panel"], fg=self.C["amber"], anchor="w")
        self._profile_lbl.pack(fill="x", padx=8, pady=(2, 4))

        param_defs = [
            # label,            var,          min,    max,    step,  fmt
            ("gpu_layers  GPU卸载层", self._gpu,    0,   200,    1,    "d"),
            ("threads     线程数",    self._threads, 1,  32,     1,    "d"),
            ("ctx         上下文长",  self._ctx,   128, 65536, 128,    "d"),
            ("batch       批大小",    self._batch,  64,  2048,  64,    "d"),
            ("temp        温度",      self._temp, 0.01,  2.0, 0.01, ".2f"),
            ("top_p",                 self._top_p,0.01,  1.0, 0.01, ".2f"),
            ("top_k",                 self._top_k,   1,  200,    1,    "d"),
            ("repeat_pen  重复惩罚",  self._rep,  1.00,  1.5, 0.01, ".2f"),
        ]
        for lbl, var, mn, mx, step, fmt in param_defs:
            self._param_row(card1, lbl, var, mn, mx, step, fmt)

        # 停止词
        tk.Label(card1, text="  stop_tokens（逗号分隔）",
                 font=("Consolas", 9), bg=self.C["panel"],
                 fg=self.C["muted"], anchor="w").pack(fill="x")
        tk.Entry(card1, textvariable=self._stop,
                 font=("Consolas", 9), bg=self.C["dark"], fg=self.C["text"],
                 insertbackground=self.C["accent"], relief="flat"
                 ).pack(fill="x", padx=8, ipady=3, pady=(0, 2))

        # ── extra_args + 快捷按钮 ──
        tk.Label(card1, text="  extra_args",
                 font=("Consolas", 9), bg=self.C["panel"],
                 fg=self.C["muted"], anchor="w").pack(fill="x")
        tk.Entry(card1, textvariable=self._extra,
                 font=("Consolas", 9), bg=self.C["dark"], fg=self.C["text"],
                 insertbackground=self.C["accent"], relief="flat"
                 ).pack(fill="x", padx=8, ipady=3, pady=(0, 3))

        # ── 快捷按钮：第一行（思考模式控制）──
        def _qbtn(parent, label, color, key):
            fg = self.C["dark"] if color not in (self.C["border"], "#1a472a", "#1a2744") else (
                "#7ee787" if color in ("#1a472a", "#1a2744") else self.C["text"])
            tk.Button(parent, text=label, font=("Consolas", 8),
                      bg=color, fg=fg,
                      activebackground=self.C["blue"], activeforeground=self.C["dark"],
                      relief="flat", cursor="hand2", padx=5, pady=2,
                      command=lambda k=key: self._extra_quick(k)
                      ).pack(side="left", padx=(0, 3))

        qrow1 = tk.Frame(card1, bg=self.C["panel"])
        qrow1.pack(fill="x", padx=8, pady=(0, 2))
        for label, color, key in [
            ("⊘ 不思考", self.C["amber"], "no_think"),
            ("🧠 思考",  "#388bfd",       "think"),
            ("chatml",   self.C["border"], "chatml"),
            ("llama3",   self.C["border"], "llama3"),
        ]:
            _qbtn(qrow1, label, color, key)

        # ── 快捷按钮：第二行（模板续 + 清空）──
        qrow2 = tk.Frame(card1, bg=self.C["panel"])
        qrow2.pack(fill="x", padx=8, pady=(0, 2))
        for label, color, key in [
            ("mistral",       self.C["border"], "mistral"),
            ("⚡ flash-attn", "#1a472a",        "flash_attn"),
            ("🔒 mlock",      "#1a2744",        "mlock"),
            ("🗑 清空",       self.C["red"],    "clear"),
        ]:
            _qbtn(qrow2, label, color, key)

        # ── 快捷按钮：第三行（性能优化）──
        qrow3 = tk.Frame(card1, bg=self.C["panel"])
        qrow3.pack(fill="x", padx=8, pady=(0, 4))
        for label, color, key in [
            ("↔ ctx-shift",   self.C["border"], "ctx_shift"),
            ("📌 min-p",      self.C["border"], "min_p"),
            ("♻ cache-reuse", self.C["border"], "cache_reuse"),
        ]:
            _qbtn(qrow3, label, color, key)

        # ── hide thinking 开关 ──
        ht_row = tk.Frame(card1, bg=self.C["panel"])
        ht_row.pack(fill="x", padx=8, pady=(0, 6))
        tk.Checkbutton(
            ht_row,
            text="👁 隐藏 thinking（PS脚本过滤，不含 --reasoning）",
            variable=self._hide_think,
            font=("Consolas", 8), bg=self.C["panel"], fg="#7ee787",
            selectcolor=self.C["dark"],
            activebackground=self.C["panel"], activeforeground="#7ee787",
            command=self._update_preview,
        ).pack(side="left")

        tk.Frame(p, bg=self.C["border"], height=1).pack(fill="x", pady=6)

        # ── 保存参数 + 启动 ──
        self._btn(p, "💾  保存参数到配置", self._save_params,
                  small=True).pack(fill="x", padx=8, pady=(0, 3))

        self._launch_btn = tk.Button(
            p, text="▶   启 动",
            font=("Consolas", 15, "bold"),
            bg=self.C["accent"], fg=self.C["dark"],
            activebackground="#2ea043", activeforeground=self.C["dark"],
            relief="flat", cursor="hand2", pady=11,
            command=self._launch)
        self._launch_btn.pack(fill="x", padx=8, pady=4)

        # ── 强制终止（放启动按钮下，随时可用）──
        tk.Button(
            p, text="☠  强制终止所有 llama 进程",
            font=("Consolas", 8, "bold"),
            bg="#2d1010", fg=self.C["red"],
            activebackground=self.C["red"], activeforeground=self.C["dark"],
            relief="flat", cursor="hand2", padx=8, pady=4,
            command=self._kill_all_llama
        ).pack(fill="x", padx=8, pady=(0, 6))


    # ──────────────────────────────────────────────────────────
    #  右栏：监控面板
    # ──────────────────────────────────────────────────────────
    def _build_monitor(self, p):
        """构建右侧监控面板：服务状态 + 加载进度 + 系统资源"""

        # ── 服务状态 ──
        sc = self._card(p, "服务状态")
        # 状态+模型名在同一行
        top_row = tk.Frame(sc, bg=self.C["panel"])
        top_row.pack(fill="x", padx=8, pady=(4, 0))
        self._srv_status_lbl = tk.Label(
            top_row, text="⏹  未运行",
            font=("Consolas", 9, "bold"),
            bg=self.C["panel"], fg=self.C["muted"])
        self._srv_status_lbl.pack(side="left")
        self._srv_model_lbl = tk.Label(
            top_row, text="", font=("Consolas", 8),
            bg=self.C["panel"], fg=self.C["muted"])
        self._srv_model_lbl.pack(side="left", padx=(8, 0))
        self._srv_addr_lbl = tk.Label(
            sc, text="", font=("Consolas", 8),
            bg=self.C["panel"], fg=self.C["blue"], anchor="w")
        self._srv_addr_lbl.pack(fill="x", padx=8, pady=(1, 1))

        copy_row = tk.Frame(sc, bg=self.C["panel"])
        copy_row.pack(fill="x", padx=8, pady=(0, 4))
        self._btn(copy_row, "📋 复制地址（浏览器）",
                  lambda: self._copy_srv_url(False), small=True
                  ).pack(side="left", padx=(0, 4))
        self._btn(copy_row, "🔑 API地址（客户端用）",
                  lambda: self._copy_srv_url(True), small=True, accent=True
                  ).pack(side="left", padx=(0, 4))
        self._btn(copy_row, "📂 日志",
                  self._open_log_file, small=True
                  ).pack(side="left", padx=(0, 0))
        ctrl_row = tk.Frame(sc, bg=self.C["panel"])
        ctrl_row.pack(fill="x", padx=8, pady=(0, 4))
        self._btn(ctrl_row, "⏹ 停止", self._stop_current,
                  danger=True, small=True).pack(side="left", padx=(0, 3))
        self._btn(ctrl_row, "↺ 重启", self._restart_server,
                  small=True).pack(side="left", padx=(0, 3))
        self._btn(ctrl_row, "🔄 切换", self._switch_model,
                  small=True, accent=True).pack(side="left")

        # ── 服务参数（折叠在右栏，服务模式时显示）──
        self._srv_card = self._card(p, "服务参数")
        for lbl, var, tip in [
            ("host",     self._srv_host,   "监听地址，0.0.0.0 允许所有来源"),
            ("port",     self._srv_port,   "端口号，默认 8080"),
            ("api-key",  self._srv_apikey, "API Key，客户端 Bearer Token"),
            ("parallel", self._srv_slots,  "并发槽位 -np，默认 1"),
        ]:
            row = tk.Frame(self._srv_card, bg=self.C["panel"])
            row.pack(fill="x", padx=8, pady=2)
            lbl_w = tk.Label(row, text=lbl, font=("Consolas", 8),
                     bg=self.C["panel"], fg=self.C["muted"], width=9, anchor="w")
            lbl_w.pack(side="left")
            lbl_w.bind("<Enter>", lambda e, t=tip: self._show_tip(e, t))
            lbl_w.bind("<Leave>", self._hide_tip)
            # api-key 行加复制按钮
            if lbl == "api-key":
                self._btn(row, "📋", lambda: self._copy_apikey(),
                          small=True).pack(side="right", padx=(2, 0))
            tk.Entry(row, textvariable=var,
                     font=("Consolas", 9), bg=self.C["dark"], fg=self.C["text"],
                     insertbackground=self.C["accent"], relief="flat"
                     ).pack(side="left", fill="x", expand=True, ipady=3, padx=(4,0))
        tk.Label(self._srv_card,
                 text="  💡 WSL: http://<本机IP>:PORT  |  客户端用 Bearer Token",
                 font=("Consolas", 7), bg=self.C["panel"],
                 fg=self.C["muted"]).pack(anchor="w", padx=8, pady=(2, 6))
        self._srv_card.pack_forget()  # 初始隐藏

        # ── 加载进度（服务模式专用，紧凑单行）──
        pc = self._card(p, "模型加载进度")
        prog_row = tk.Frame(pc, bg=self.C["panel"])
        prog_row.pack(fill="x", padx=8, pady=(3, 0))
        self._load_model_lbl = tk.Label(
            prog_row, text="—", font=("Consolas", 8),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._load_model_lbl.pack(side="left", fill="x", expand=True)
        self._load_pct_lbl = tk.Label(
            prog_row, text="", font=("Consolas", 8, "bold"),
            bg=self.C["panel"], fg=self.C["accent"], width=5, anchor="e")
        self._load_pct_lbl.pack(side="right")

        # Canvas 进度条（高度压缩为10）
        self._progress_canvas = tk.Canvas(
            pc, height=10, bg=self.C["dark"], highlightthickness=0)
        self._progress_canvas.pack(fill="x", padx=8, pady=(2, 0))
        self._progress_bar = self._progress_canvas.create_rectangle(
            0, 0, 0, 10, fill=self.C["accent"], outline="")
        self._progress_bg  = self._progress_canvas.create_rectangle(
            0, 0, 2000, 10, fill=self.C["border"], outline="", tags="bg")
        self._progress_canvas.tag_lower("bg")

        self._load_status_lbl = tk.Label(
            pc, text="", font=("Consolas", 7),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._load_status_lbl.pack(fill="x", padx=8, pady=(1, 4))

        # ── 服务日志 ──
        lc = self._card(p, "服务日志", expand=False)
        self._srv_log = scrolledtext.ScrolledText(
            lc, font=("Consolas", 8), height=7,
            bg=self.C["dark"], fg="#8b949e",
            relief="flat", state="disabled")
        self._srv_log.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        # 高亮 tag
        self._srv_log.tag_config("ready",   foreground=self.C["accent"])
        self._srv_log.tag_config("warn",    foreground=self.C["amber"])
        self._srv_log.tag_config("err",     foreground=self.C["red"])
        self._srv_log.tag_config("ts",      foreground=self.C["muted"])

        # ── 系统资源 ──
        rc = self._card(p, "系统资源  ( 每秒刷新 )", expand=True)
        self._res_frame = rc

        # 设备信息区（首次扫描后填充）
        hw_frame = tk.Frame(rc, bg=self.C["panel"])
        hw_frame.pack(fill="x", padx=8, pady=(3, 4))
        self._hw_cpu_lbl = tk.Label(
            hw_frame, text="CPU  —", font=("Consolas", 7),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._hw_cpu_lbl.pack(fill="x")
        self._hw_ram_lbl = tk.Label(
            hw_frame, text="RAM  —", font=("Consolas", 7),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._hw_ram_lbl.pack(fill="x")
        self._hw_gpu_lbl = tk.Label(
            hw_frame, text="GPU  —", font=("Consolas", 7),
            bg=self.C["panel"], fg=self.C["muted"], anchor="w")
        self._hw_gpu_lbl.pack(fill="x")
        # 分隔线
        tk.Frame(rc, bg=self.C["border"], height=1).pack(
            fill="x", padx=8, pady=(0, 3))

        res_items = [
            ("CPU",  "cpu"),
            ("RAM",  "ram"),
            ("GPU",  "gpu"),
            ("VRAM", "vram"),
        ]
        self._res_bars   = {}
        self._res_labels = {}
        for name, key in res_items:
            # 外框：每项两行（进度条行 + 数值行）
            item_f = tk.Frame(rc, bg=self.C["panel"])
            item_f.pack(fill="x", padx=8, pady=(1, 0))
            # 第一行：名称 + 进度条
            bar_row = tk.Frame(item_f, bg=self.C["panel"])
            bar_row.pack(fill="x")
            tk.Label(bar_row, text=name, font=("Consolas", 8, "bold"),
                     bg=self.C["panel"], fg=self.C["muted"],
                     width=5, anchor="w").pack(side="left")
            cv = tk.Canvas(bar_row, height=8, bg=self.C["dark"],
                           highlightthickness=0)
            cv.pack(side="left", fill="x", expand=True)
            bg_id  = cv.create_rectangle(0, 0, 2000, 8,
                                         fill=self.C["border"], outline="", tags="bg")
            bar_id = cv.create_rectangle(0, 0, 0, 8,
                                         fill=self.C["accent"], outline="")
            cv.tag_lower("bg")
            # 第二行：数值文字（左对齐，完整显示）
            lbl = tk.Label(item_f, text="—",
                           font=("Consolas", 8), bg=self.C["panel"],
                           fg=self.C["text"], anchor="w")
            lbl.pack(fill="x", padx=(26, 0))
            self._res_bars[key]   = (cv, bar_id)
            self._res_labels[key] = lbl

        # token 区域：当前速度 / 峰值 / 累计输出
        tok_frame = tk.Frame(rc, bg=self.C["panel"])
        tok_frame.pack(fill="x", padx=8, pady=(3, 5))

        # 第一行：当前速度（大字）+ 峰值（小字）
        tok_row1 = tk.Frame(tok_frame, bg=self.C["panel"])
        tok_row1.pack(fill="x")
        tk.Label(tok_row1, text="速度", font=("Consolas", 7, "bold"),
                 bg=self.C["panel"], fg=self.C["muted"],
                 width=5, anchor="w").pack(side="left")
        self._tok_lbl = tk.Label(
            tok_row1, text="—",
            font=("Consolas", 11, "bold"),
            bg=self.C["panel"], fg=self.C["blue"])
        self._tok_lbl.pack(side="left", padx=(4, 6))
        self._tok_max_lbl = tk.Label(
            tok_row1, text="",
            font=("Consolas", 8),
            bg=self.C["panel"], fg=self.C["muted"])
        self._tok_max_lbl.pack(side="left")

        # 第二行：累计输出 token
        tok_row2 = tk.Frame(tok_frame, bg=self.C["panel"])
        tok_row2.pack(fill="x")
        tk.Label(tok_row2, text="累计", font=("Consolas", 7, "bold"),
                 bg=self.C["panel"], fg=self.C["muted"],
                 width=5, anchor="w").pack(side="left")
        self._tok_total_lbl = tk.Label(
            tok_row2, text="0 tokens",
            font=("Consolas", 8),
            bg=self.C["panel"], fg=self.C["text"])
        self._tok_total_lbl.pack(side="left", padx=(4, 0))

        self._tok_max_val   = 0.0   # 峰值速度
        self._tok_total_val = 0     # 累计 token

        # 启动资源监控
        self._start_resource_monitor()

    # ──────────────────────────────────────────────────────────
    #  控件辅助
    # ──────────────────────────────────────────────────────────
    def _card(self, parent, title, expand=False):
        f = tk.Frame(parent, bg=self.C["panel"],
                     highlightbackground=self.C["border"],
                     highlightthickness=1)
        f.pack(fill="both" if expand else "x", expand=expand, pady=4)
        tk.Label(f, text=f"  {title}",
                 font=("Consolas", 10, "bold"),
                 bg=self.C["border"], fg=self.C["blue"],
                 anchor="w", pady=3).pack(fill="x")
        return f

    def _btn(self, parent, text, cmd, small=False, accent=False, danger=False):
        bg = self.C["accent"] if accent else (self.C["red"] if danger else self.C["border"])
        fg = self.C["dark"] if (accent or danger) else self.C["text"]
        return tk.Button(
            parent, text=text, command=cmd,
            font=("Consolas", 8 if small else 10),
            bg=bg, fg=fg,
            activebackground=self.C["blue"], activeforeground=self.C["dark"],
            relief="flat", cursor="hand2", padx=8,
            pady=3 if small else 5)

    # 参数说明字典
    PARAM_TIPS = {
        "gpu_layers  GPU卸载层": "⚠ 不是越高越好！超显存会溢出到共享内存变慢。35B-MoE→20~30，14B→30~40，7B→99",
        "threads     线程数":    "CPU 推理线程。i9-14900HX 建议 16（P核数量），GPU卸载多时可降低",
        "ctx         上下文长":  "对话历史窗口。越大越消耗内存，35B 建议 2048-4096",
        "batch       批大小":    "批处理 token 数。越大速度越快但显存占用更多，推荐 512",
        "temp        温度":      "创意程度。0=确定性输出，0.35=精准，0.7=均衡，>1=随机",
        "top_p":                 "核采样。保留概率累计前 p 的 token，0.7-0.9 较稳定",
        "top_k":                 "每步候选 token 数。40-50 较合适，越小越保守",
        "repeat_pen  重复惩罚":  "抑制重复输出。1.0=无惩罚，1.05-1.15 合适，过高会破坏连贯性",
    }

    def _param_row(self, parent, label, var, mn, mx, step, fmt):
        """单个参数行：名称+简短说明 / 滑块 / 输入框，紧凑布局"""
        tip_text = self.PARAM_TIPS.get(label, "")

        row = tk.Frame(parent, bg=self.C["panel"])
        row.pack(fill="x", padx=8, pady=1)

        name_lbl = tk.Label(row, text=label, font=("Consolas", 8),
                            bg=self.C["panel"], fg=self.C["muted"],
                            width=18, anchor="w")
        name_lbl.pack(side="left")
        if tip_text:
            name_lbl.bind("<Enter>", lambda e, t=tip_text: self._show_tip(e, t))
            name_lbl.bind("<Leave>", self._hide_tip)

        # entry_var 与 var 双向同步
        entry_var = tk.StringVar()
        iv = var.get()
        entry_var.set(str(iv) if fmt == "d" else format(iv, fmt))

        # ← 关键：当 var.set() 被外部调用时，同步更新 entry_var 显示
        def _sync_entry(*_, _ev=entry_var, _v=var, _fmt=fmt):
            try:
                val = _v.get()
                _ev.set(str(val) if _fmt == "d" else format(val, _fmt))
            except Exception:
                pass
        var.trace_add("write", _sync_entry)

        entry = tk.Entry(row, textvariable=entry_var,
                         font=("Consolas", 8, "bold"),
                         bg=self.C["dark"], fg=self.C["accent"],
                         insertbackground=self.C["accent"],
                         relief="flat", width=6, justify="right")
        entry.pack(side="right", ipady=1)

        def on_slide(v, _var=var, _step=step, _evar=entry_var, _fmt=fmt):
            r = round(float(v) / _step) * _step
            if _fmt == "d":
                _var.set(int(r)); _evar.set(str(int(r)))
            else:
                _var.set(round(r, 4)); _evar.set(format(r, _fmt))
            self._update_preview()

        def on_entry(_e=None, _var=var, _evar=entry_var,
                     _step=step, _mn=mn, _mx=mx, _fmt=fmt):
            try:
                v = max(_mn, min(_mx, round(float(_evar.get()) / _step) * _step))
                if _fmt == "d":
                    _var.set(int(v)); _evar.set(str(int(v)))
                else:
                    _var.set(round(v, 4)); _evar.set(format(v, _fmt))
                self._update_preview()
            except ValueError:
                pass

        entry.bind("<Return>", on_entry)
        entry.bind("<FocusOut>", on_entry)

        ttk.Scale(row, from_=mn, to=mx, variable=var,
                  orient="horizontal", command=on_slide,
                  ).pack(side="right", fill="x", expand=True, padx=(0, 4))

    def _show_tip(self, event, text):
        """鼠标悬停在参数名上时显示说明 tooltip"""
        x = event.widget.winfo_rootx() + 20
        y = event.widget.winfo_rooty() + 20
        self._tip_win = tk.Toplevel(self)
        self._tip_win.wm_overrideredirect(True)
        self._tip_win.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip_win, text=text,
                 font=("Consolas", 9), bg="#1c2128", fg=self.C["text"],
                 relief="flat", padx=10, pady=6,
                 wraplength=420, justify="left"
                 ).pack()

    def _hide_tip(self, _event=None):
        try:
            self._tip_win.destroy()
        except Exception:
            pass
        self._tip_win = None

    def _style_ttk(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        try:
            s.configure("Vertical.TScrollbar",
                        background=self.C["border"], troughcolor=self.C["dark"],
                        arrowcolor=self.C["muted"], relief="flat", borderwidth=0)
        except Exception:
            pass
        try:
            s.configure("TScale",
                        background=self.C["panel"], troughcolor=self.C["dark"],
                        sliderthickness=8)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────
    #  动作
    # ──────────────────────────────────────────────────────────
    def _do_scan(self):
        self._set_st("正在扫描模型…", self.C["amber"])
        dirs = list(self._dir_lb.get(0, "end"))
        def run():
            found = scan_models(dirs)
            self.models = found
            self.after(0, self._populate_models, found)
        threading.Thread(target=run, daemon=True).start()

    def _populate_models(self, models):
        self._mlb.delete(0, "end")
        for path in models:
            self._mlb.insert("end", f"  {os.path.basename(path)}")
        self._mcount_lbl.config(text=f"共 {len(models)} 个模型")
        self._set_st(f"扫描完成，发现 {len(models)} 个 .gguf 模型", self.C["accent"])

    def _on_model_select(self, _=None):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            return
        model_path = self.models[sel[0]]
        model_name = os.path.basename(model_path)

        p = match_profile(model_name, self.mcfg)
        self.cur_params = dict(p)

        # 填入变量
        self._gpu.set(p.get("gpu_layers", 0))
        self._threads.set(p.get("threads", 8))
        self._ctx.set(p.get("ctx", 4096))
        self._batch.set(p.get("batch", 512))
        self._temp.set(p.get("temp", 0.70))
        self._top_p.set(p.get("top_p", 0.90))
        self._top_k.set(p.get("top_k", 50))
        self._rep.set(p.get("repeat_penalty", 1.08))
        self._stop.set(", ".join(p.get("stop_tokens", [])))
        self._extra.set(p.get("extra_args", ""))
        self._thinking.set(p.get("thinking", False))
        self._hide_think.set(p.get("hide_think", False))

        # 找到匹配的 profile 名
        n = model_name.lower()
        matched = "default"
        for key, prof in self.mcfg.get("_profiles", {}).items():
            if key.startswith("_") or key == "default":
                continue
            kws = prof.get("_match", [])
            if kws and all(k in n for k in kws):
                matched = key
                break
        # 如果有保存记忆则标注
        if model_name in self.mcfg.get("models", {}):
            matched += "  [已记忆]"
        self.cur_profile_key.set(f"配置: {matched}")

        self._cur_model_name = model_name
        self._load_prompt_for_model(model_name)
        self._update_preview()
        self._set_st(f"已选择: {model_name}", self.C["blue"])

    def _collect_params(self) -> dict:
        """从界面变量收集当前参数"""
        stop_raw = self._stop.get()
        stops = [s.strip() for s in stop_raw.split(",") if s.strip()]
        return {
            "gpu_layers":     self._gpu.get(),
            "threads":        self._threads.get(),
            "ctx":            self._ctx.get(),
            "batch":          self._batch.get(),
            "temp":           round(self._temp.get(), 4),
            "top_p":          round(self._top_p.get(), 4),
            "top_k":          self._top_k.get(),
            "repeat_penalty": round(self._rep.get(), 4),
            "stop_tokens":    stops,
            "extra_args":     self._extra.get().strip(),
            "last_mode":      self._mode.get(),
            "hide_think":     self._hide_think.get(),
        }

    def _update_preview(self, *_):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            self._set_preview("（请先选择模型）")
            return
        model_path = self.models[sel[0]]
        params = self._collect_params()

        if self._mode.get() == "chat":
            cmd = build_chat_cmd(self.cfg, model_path, params)
        else:
            sys_prompt = self._get_active_prompt()
            cmd = build_server_cmd(
                self.cfg, model_path, params,
                self._srv_host.get(), self._srv_port.get(),
                self._srv_apikey.get(), self._srv_slots.get(),
                system_prompt=sys_prompt,
                role_name=self._cur_role_name)

        text = cmd_to_display(cmd)
        # 在预览末尾显示 hide_think 状态（不是命令行参数，是PS脚本行为）
        if self._mode.get() == "chat" and self._hide_think.get():
            hint = "\n# [\U0001f441 PS过滤模式: 隐藏 <think> 输出]"
            text = text + hint
        self._set_preview(text)

    def _set_preview(self, text: str):
        self._preview.config(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("end", text)
        self._preview.config(state="disabled")

    def _on_mode_change(self):
        if self._mode.get() == "server":
            self._srv_card.pack(fill="x", pady=4)
            self._launch_btn.config(
                text="▶   启动服务",
                bg=self.C["blue"], activebackground="#388bfd")
        else:
            self._srv_card.pack_forget()
            self._launch_btn.config(
                text="▶   启动对话  ( PowerShell )",
                bg=self.C["accent"], activebackground="#2ea043")
        self._update_preview()

    def _save_params(self):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            messagebox.showwarning("提示", "请先选择一个模型")
            return
        model_name = os.path.basename(self.models[sel[0]])
        params = self._collect_params()
        save_model_params(model_name, params, self.mcfg)
        # 保存后刷新内存中的 mcfg，确保下次选中时能读到新参数
        self.mcfg = load_models_cfg()
        self.cur_profile_key.set(f"配置: {model_name.split('.')[0]}  [已记忆]")
        hide = "隐藏思考" if params.get("hide_think") else "正常输出"
        self._set_st(f"✓ 已保存 {model_name} 的参数（{hide}）", self.C["accent"])

    # ── Prompt 双语显示工具 ─────────────────────────────────────
    def _load_bilingual_prompt(self, zh: str, en: str):
        """把中文 + 分隔线 + 英文合并写入编辑框"""
        self._prompt_txt.delete("1.0", "end")
        self._prompt_txt.insert("end", zh.strip() if zh else "")
        self._prompt_txt.insert("end", zh.strip() if zh else "")
        self._prompt_txt.insert("end", "\n\n")
        sep_start = self._prompt_txt.index("end - 1c linestart")
        self._prompt_txt.insert("end", PROMPT_SEP + "\n")
        sep_end = self._prompt_txt.index("end - 1c")
        self._prompt_txt.tag_add("sep", sep_start, sep_end)
        if en:
            self._prompt_txt.insert("end", "\n" + en.strip())
    def _get_prompt_zh(self) -> str:
        """从编辑框提取中文部分（分隔线以上）"""
        full = self._prompt_txt.get("1.0", "end")
        if PROMPT_SEP in full:
            return full.split(PROMPT_SEP)[0].strip()
        return full.strip()

    def _get_prompt_en_from_box(self) -> str:
        """从编辑框提取英文部分（分隔线以下）"""
        full = self._prompt_txt.get("1.0", "end")
        if PROMPT_SEP in full:
            return full.split(PROMPT_SEP, 1)[1].strip()
        return ""

    def _get_active_prompt(self) -> str:
        """根据传参语言选择返回实际用于传参的 prompt"""
        lang = self._prompt_lang.get()
        if lang == "none":
            return ""
        if lang == "en":
            en = self._get_prompt_en_from_box()
            return en if en else get_prompt_en(
                self._get_prompt_zh(), self._cur_role_name, self.cfg)
        return self._get_prompt_zh()   # zh（默认）

    def _copy_prompt_zh(self):
        zh = self._get_prompt_zh()
        if zh:
            self.clipboard_clear()
            self.clipboard_append(zh)
            self._set_st("✓ 已复制中文 Prompt", self.C["accent"])
        else:
            self._set_st("中文 Prompt 为空", self.C["muted"])

    def _copy_prompt_en(self):
        en = self._get_prompt_en_from_box()
        if not en:
            en = get_prompt_en(self._get_prompt_zh(),
                               self._cur_role_name, self.cfg)
        self.clipboard_clear()
        self.clipboard_append(en)
        self._set_st("✓ 已复制英文 Prompt", self.C["blue"])

    # ── 角色管理 ───────────────────────────────────────────────
    def _load_role(self, role_name: str):
        """点击角色按钮：双语显示（中文在上，英文在下）"""
        roles    = self.cfg.get("roles",    DEFAULT_ROLES)
        roles_en = self.cfg.get("roles_en", PROMPT_EN)
        zh = roles.get(role_name, "")
        en = roles_en.get(role_name) or PROMPT_EN.get(role_name, "")
        if not zh:
            return
        self._cur_role_name = role_name
        self._load_bilingual_prompt(zh, en)
        self._prompt_src_lbl.config(
            text=f"角色预设: {role_name}  （可编辑，点💾保存）",
            fg=self.C["blue"])
        self._set_st(f"已加载角色: {role_name}", self.C["blue"])

    # ── Prompt 管理 ───────────────────────────────────────────
    def _load_prompt_for_model(self, model_name: str):
        """切换模型时加载对应 prompt：优先模型专属，否则全局"""
        model_prompt = (self.mcfg.get("models", {})
                        .get(model_name, {})
                        .get("system_prompt", None))
        if model_prompt is not None:
            text = model_prompt
            src_label = f"来源: 模型专属  [{model_name}]"
            src_color = self.C["accent"]
        else:
            text = self.cfg.get("system_prompt", "")
            src_label = "来源: 全局 config.json  （未设专属，编辑后点保存）"
            src_color = self.C["muted"]
        self._prompt_txt.delete("1.0", "end")
        self._prompt_txt.insert("1.0", text)
        self._prompt_src_lbl.config(text=src_label, fg=src_color)

    def _save_prompt(self):
        """保存中英文 prompt：
           - 若选中了角色 → 写入 config.json roles / roles_en
           - 否则 → 写入当前模型的专属配置 models_config.json
        """
        zh = self._get_prompt_zh()
        en = self._get_prompt_en_from_box()

        if self._cur_role_name:
            # 保存到角色预设
            self.cfg.setdefault("roles", {})[self._cur_role_name] = zh
            if en:
                self.cfg.setdefault("roles_en", {})[self._cur_role_name] = en
            save_config(self.cfg)
            self._prompt_src_lbl.config(
                text=f"角色预设: {self._cur_role_name}  ✓ 已保存到 config.json",
                fg=self.C["accent"])
            self._set_st(
                f"✓ 角色 [{self._cur_role_name}] 已保存", self.C["accent"])
        elif self._cur_model_name:
            # 保存到模型专属
            m = self.mcfg.setdefault("models", {}).setdefault(
                self._cur_model_name, {})
            m["system_prompt"] = zh
            if en:
                m["system_prompt_en"] = en
            save_models_cfg(self.mcfg)
            self._prompt_src_lbl.config(
                text=f"来源: 模型专属  [{self._cur_model_name}]  ✓ 已保存",
                fg=self.C["accent"])
            self._set_st(
                f"✓ Prompt 已保存到 {self._cur_model_name}", self.C["accent"])
        else:
            messagebox.showwarning("提示", "请先选择模型或角色")

    def _reset_prompt_to_global(self):
        """清除模型专属 prompt，回退到全局；若是角色则回退到 DEFAULT_ROLES"""
        if self._cur_role_name:
            # 恢复角色默认（从内置常量）
            zh = DEFAULT_ROLES.get(self._cur_role_name, "")
            en = PROMPT_EN.get(self._cur_role_name, "")
            self._load_bilingual_prompt(zh, en)
            self._prompt_src_lbl.config(
                text=f"角色预设: {self._cur_role_name}  （已恢复默认）",
                fg=self.C["amber"])
            self._set_st("已恢复角色默认 Prompt", self.C["amber"])
            return
        if not self._cur_model_name:
            return
        m = self.mcfg.get("models", {}).get(self._cur_model_name, {})
        for k in ("system_prompt", "system_prompt_en"):
            if k in m:
                del m[k]
        save_models_cfg(self.mcfg)
        zh = self.cfg.get("system_prompt", "")
        en = PROMPT_EN.get("default", "")
        self._load_bilingual_prompt(zh, en)
        self._prompt_src_lbl.config(
            text="来源: 全局 config.json  （专属已清除）",
            fg=self.C["muted"])
        self._set_st("已重置为全局 Prompt", self.C["amber"])

    # ── extra_args 快捷操作 ────────────────────────────────────
    def _extra_quick(self, key: str):
        """快捷按钮：智能追加/移除 extra_args 片段"""
        cur = self._extra.get().strip()

        # 各按钮对应的参数片段
        snippets = {
            "no_think":    "--reasoning off",
            "think":       "",                        # 移除 no_think 相关
            "chatml":      "--chat-template chatml",
            "llama3":      "--chat-template llama3",
            "mistral":     "--chat-template mistral",
            "flash_attn":  "--flash-attn",
            "mlock":       "--mlock",
            "ctx_shift":   "--ctx-shift",
            "min_p":       "--min-p 0.05",
            "cache_reuse": "--cache-reuse 256",
        }

        if key == "clear":
            self._extra.set("")
            self._update_preview()
            return

        if key == "think":
            # 移除所有 reasoning 相关参数
            import re
            new = re.sub(r'--reasoning\s+\S+', '', cur).strip()
            new = new.replace("--reasoning-format none", "").strip()
            new = ' '.join(new.split())
            # 清理多余空格
            new = ' '.join(new.split())  # 压缩多余空格
            self._extra.set(new)
            self._update_preview()
            return

        # chat-template 互斥：先移除旧的再加新的
        if key in ("chatml", "llama3", "mistral"):
            # 移除已有的 --chat-template 及其参数值（字符串替换方式）
            import re
            cur = re.sub(r'--chat-template \S+', '', cur).strip()
            cur = ' '.join(cur.split())  # 压缩多余空格

        snippet = snippets.get(key, "")
        if not snippet:
            self._extra.set(cur)
            self._update_preview()
            return

        # 已存在则不重复添加
        if snippet in cur:
            self._update_preview()
            return

        new = (cur + " " + snippet).strip()
        self._extra.set(new)
        self._update_preview()

    def _launch(self):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            messagebox.showwarning("提示", "请先选择一个模型")
            return
        model_path = self.models[sel[0]]
        params = self._collect_params()

        if self._mode.get() == "chat":
            self._launch_chat(model_path, params)
        else:
            self._launch_server(model_path, params)

    # ── 对话模式 ───────────────────────────────────────────────
    def _launch_chat(self, model_path: str, params: dict):
        exe = self.cfg.get("llama_cli_path", "llama-cli")
        if not (shutil.which(exe) or os.path.isfile(exe)):
            messagebox.showerror(
                "找不到 llama-cli",
                f"路径：{exe}\n\n请在 config.json 中设置正确的 llama_cli_path")
            return
        cmd = build_chat_cmd(self.cfg, model_path, params)
        keep = self.cfg.get("chat", {}).get("powershell_keep_open", True)
        sys_prompt = self._prompt_txt.get("1.0", "end").strip()
        hide_think = params.get("hide_think", self._hide_think.get())
        try:
            _launch_powershell(cmd, keep, system_prompt=sys_prompt,
                               hide_think=hide_think)
            model_name = os.path.basename(model_path)
            # 记录对话启动日志
            try:
                chat_log = _new_log_path("chat", model_name)
                with open(chat_log, "w", encoding="utf-8") as lf:
                    ts_str = _ts()
                    lf.write("[" + ts_str + "] === 对话模式启动 ===\n")
                    lf.write("模型: " + model_path + "\n")
                    lf.write("命令: " + " ".join(cmd) + "\n")
                    sp_preview = sys_prompt[:200] + "..." if len(sys_prompt) > 200 else sys_prompt
                    lf.write("System Prompt: " + sp_preview + "\n")
                _rotate_logs("chat", keep=10)
            except Exception:
                pass
                pass
            self._set_st(f"▶ 对话已启动: {model_name}", self.C["accent"])
        except Exception as e:
            messagebox.showerror("启动失败", str(e))

    # ── 服务模式 ───────────────────────────────────────────────
    def _launch_server(self, model_path: str, params: dict):
        if self._server_running:
            if not messagebox.askyesno("服务已运行", "服务正在运行中，是否先停止再重新启动？"):
                return
            self._stop_server()
            time.sleep(0.8)

        exe = self.cfg.get("llama_server_path", "llama-server")
        if not (shutil.which(exe) or os.path.isfile(exe)):
            messagebox.showerror(
                "找不到 llama-server",
                f"路径：{exe}\n\n请在 config.json 中设置正确的 llama_server_path")
            return

        sys_prompt = self._get_active_prompt()
        cmd = build_server_cmd(
            self.cfg, model_path, params,
            self._srv_host.get(), self._srv_port.get(),
            self._srv_apikey.get(), self._srv_slots.get(),
            system_prompt=sys_prompt,
            role_name=self._cur_role_name)

        self._srv_log_clear()
        # 打开新的日志文件
        try:
            self._log_path = _new_log_path("server", os.path.basename(model_path))
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            _rotate_logs("server", keep=10)
        except Exception as e:
            print(f"[WARN] 日志文件创建失败: {e}")
            self._log_file = None
            self._log_path = None
        # 立即重置进度条，给用户即时反馈
        self._srv_ready = False
        self._update_load_progress(0, "等待模型加载...")
        model_short = os.path.basename(model_path)
        self._load_model_lbl.config(text=model_short)
        self._load_pct_lbl.config(text="0%")
        self._srv_log_append(f"[{_ts()}] 启动命令:\n{cmd_to_display(cmd)}\n\n")

        try:
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1,
            )
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return

        self._server_running = True
        self._srv_cur_model  = os.path.basename(model_path)
        self.after(0, self._update_tok_speed, "—")
        self._tok_max_val   = 0.0
        self._tok_total_val = 0
        try:
            self._tok_max_lbl.config(text="")
            self._tok_total_lbl.config(text="0 tokens")
        except Exception:
            pass

        # 自动保存 API key 到 config
        api_key = self._srv_apikey.get().strip()
        if api_key and api_key != "sk-local-change-me":
            self.cfg["server"]["api_keys"]["default"] = api_key
            save_config(self.cfg)

        port = self._srv_port.get()
        host_display = self._srv_host.get()
        self._srv_status_lbl.config(
            text=f"▶  运行中  ( PID {self._server_proc.pid} )",
            fg=self.C["accent"])
        self._srv_model_lbl.config(
            text=f"模型: {self._srv_cur_model}",
            fg=self.C["muted"])
        self._srv_addr_lbl.config(
            text=f"http://localhost:{port}  |  http://{host_display}:{port}")
        self._set_st(f"▶ 服务已启动 :{port}  模型: {self._srv_cur_model}", self.C["accent"])

        # 日志流线程：往队列里放行
        self._server_thread = threading.Thread(
            target=self._stream_server_log, daemon=True)
        self._server_thread.start()
        # 主线程定时器：每 100ms 批量从队列取出更新 UI
        self.after(100, self._poll_log_queue)

    def _stream_server_log(self):
        """后台线程：把日志行放入队列，不直接操作 UI"""
        if not self._server_proc:
            return
        try:
            for line in self._server_proc.stdout:
                self._log_queue.put(line)
        except Exception:
            pass
        # stdout 关闭后，检查进程是否真的退出
        # llama-server 有时关闭 stdout 但进程仍在运行
        import time as _t
        proc = self._server_proc
        if proc is None:
            self._log_queue.put(None)
            return
        # 等最多 2 秒确认进程状态
        for _ in range(20):
            ret = proc.poll()
            if ret is not None:
                # 真的退出了
                self._log_queue.put(None)
                return
            _t.sleep(0.1)
        # 进程仍在运行，继续监控（每秒 poll 一次）
        while self._server_running:
            ret = proc.poll()
            if ret is not None:
                self._log_queue.put(None)
                return
            _t.sleep(1)

    def _poll_log_queue(self):
        """主线程定时器：每 100ms 批量从队列取日志更新 UI"""
        if not self._server_running and self._log_queue.empty():
            return
        try:
            processed = 0
            while not self._log_queue.empty() and processed < 20:
                line = self._log_queue.get_nowait()
                if line is None:
                    # 进程已结束
                    self._on_server_exit()
                    return
                self._srv_log_append(line)
                processed += 1
        except Exception:
            pass
        # 继续轮询
        if self._server_running or not self._log_queue.empty():
            self.after(100, self._poll_log_queue)

    def _on_server_exit(self):
        self._server_running = False
        self._tip_win = None
        self._server_proc = None
        self._srv_cur_model = ""
        # 关闭日志文件
        if self._log_file:
            try:
                ts_str = _ts()
                self._log_file.write("\n[" + ts_str + "] === 服务已停止 ===\n")
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._srv_status_lbl.config(text="⏹  已停止", fg=self.C["muted"])
        self._srv_model_lbl.config(text="")
        self._srv_addr_lbl.config(text="")
        self._update_load_progress(0, "")
        self._load_model_lbl.config(text="—")
        self._load_pct_lbl.config(text="")
        self._update_tok_speed("—")
        self._srv_log_append(f"\n[{_ts()}] 服务已停止\n")
        self._set_st("服务已停止", self.C["amber"])

    def _stop_current(self):
        """停止按钮：服务模式停止服务，对话模式终止 llama-cli 黑框"""
        if self._mode.get() == "server":
            self._stop_server()
        else:
            # 对话模式：杀掉所有 llama-cli 进程
            killed = []
            for name in ["llama-cli.exe", "llama-cli"]:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/IM", name],
                        capture_output=True, text=True, timeout=3)
                    if "SUCCESS" in result.stdout or "成功" in result.stdout:
                        killed.append(name)
                except Exception:
                    pass
            if killed:
                self._set_st(f"✓ 已终止对话进程: {', '.join(killed)}", self.C["amber"])
            else:
                self._set_st("未发现运行中的对话进程", self.C["muted"])

    def _stop_server(self):
        """停止当前服务：先 terminate，超时后强制 kill"""
        proc = self._server_proc
        self._server_running = False
        self._tip_win = None
        if not proc:
            return
        try:
            proc.terminate()
            # 等最多 3 秒让进程正常退出
            import threading as _th
            def _wait_and_kill():
                try:
                    proc.wait(timeout=3)
                except Exception:
                    # 超时则强制杀死
                    try:
                        proc.kill()
                    except Exception:
                        pass
            _th.Thread(target=_wait_and_kill, daemon=True).start()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._server_proc = None

    def _restart_server(self):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            messagebox.showwarning("提示", "请先选择一个模型")
            return
        self._stop_server()
        time.sleep(1.0)
        self._launch_server(self.models[sel[0]], self._collect_params())

    def _kill_all_llama(self):
        """强制终止系统中所有 llama-server / llama-cli 进程"""
        targets = ["llama-server.exe", "llama-cli.exe",
                   "llama-server",    "llama-cli",
                   "main.exe",        "main"]
        killed = []
        # 方法1：用 taskkill（Windows）
        for name in targets:
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    capture_output=True, text=True, timeout=3
                )
                if "SUCCESS" in result.stdout or "成功" in result.stdout:
                    killed.append(name)
            except Exception:
                pass

        # 方法2：用 psutil 兜底（跨平台）
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    pname = (proc.info["name"] or "").lower()
                    pexe  = (proc.info["exe"]  or "").lower()
                    if any(t.lower() in pname or t.lower() in pexe
                           for t in targets):
                        proc.kill()
                        killed.append(f"PID {proc.info['pid']}")
                except Exception:
                    pass
        except ImportError:
            pass

        # 重置 UI 状态
        self._server_running = False
        self._server_proc    = None
        self._srv_cur_model  = ""
        try:
            self._srv_status_lbl.config(text="⏹  已停止（强制终止）",
                                        fg=self.C["amber"])
            self._srv_model_lbl.config(text="")
            self._srv_addr_lbl.config(text="")
            self._update_load_progress(0, "")
            self._load_model_lbl.config(text="—")
            self._load_pct_lbl.config(text="")
            self._update_tok_speed("—")
        except Exception:
            pass

        if killed:
            msg = f"✓ 已强制终止 {len(killed)} 个 llama 进程"
            detail = ", ".join(killed)
            log_msg = "[" + _ts() + "] " + msg + ": " + detail + "\n"
            self._srv_log_append("\n" + log_msg)
            self._set_st(msg, self.C["amber"])
            killed_str = "\n".join(killed)
            messagebox.showinfo("强制终止", msg + "\n\n" + killed_str)
        else:
            self._set_st("未发现运行中的 llama 进程", self.C["muted"])
            messagebox.showinfo("强制终止", "未发现运行中的 llama-server / llama-cli 进程")


    # ──────────────────────────────────────────────────────────
    #  硬件信息初始化
    # ──────────────────────────────────────────────────────────
    def _init_hardware_info(self):
        """后台线程扫描硬件，完成后更新 UI 标签"""
        def _scan():
            hw = get_or_scan_hardware(self.cfg)
            self.after(0, self._apply_hardware_labels, hw)
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_hardware_labels(self, hw: dict):
        """把扫描到的硬件信息填入 UI 标签"""
        try:
            cpu = hw.get("cpu_name", "未知")
            cores = hw.get("cpu_cores", "")
            self._hw_cpu_lbl.config(
                text=f"CPU  {cpu}" + (f"  ({cores})" if cores else ""))
            ram_total = hw.get("ram_total", "")
            ram_sticks = hw.get("ram_sticks", "")
            ram_str = ram_total
            if ram_sticks:
                ram_str += f"  [{ram_sticks}]"
            self._hw_ram_lbl.config(text=f"RAM  {ram_str}" if ram_str else "RAM  —")
            gpu = hw.get("gpu_name", "未知")
            vram = hw.get("gpu_vram", "")
            self._hw_gpu_lbl.config(
                text=f"GPU  {gpu}" + (f"  {vram}" if vram else ""))
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────
    #  监控：系统资源 + 服务日志解析
    # ──────────────────────────────────────────────────────────
    def _start_resource_monitor(self):
        """启动后台线程每秒刷新系统资源"""
        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._resource_loop, daemon=True)
        self._monitor_thread.start()

    def _resource_loop(self):
        import importlib
        psutil_ok = importlib.util.find_spec("psutil") is not None
        if psutil_ok:
            import psutil

        while self._monitor_running:
            try:
                data = {}
                if psutil_ok:
                    import psutil as ps
                    cpu_pct = ps.cpu_percent(interval=0.2)
                    cpu_freq = ps.cpu_freq()
                    freq_str = f"{cpu_freq.current/1000:.2f} GHz" if cpu_freq else ""
                    data["cpu"] = (cpu_pct, f"{cpu_pct:.0f}%  {freq_str}")

                    vm = ps.virtual_memory()
                    ram_pct = vm.percent
                    used_gb = vm.used / 1024**3
                    total_gb = vm.total / 1024**3
                    data["ram"] = (ram_pct, f"{used_gb:.1f} / {total_gb:.1f} GB")
                else:
                    data["cpu"] = (0, "需要 psutil")
                    data["ram"] = (0, "需要 psutil")

                # GPU via nvidia-smi
                gpu_data = self._query_nvidia_smi()
                data["gpu"]  = gpu_data["util"]
                data["vram"] = gpu_data["vram"]

                self.after(0, self._update_res_ui, data)
            except Exception:
                pass
            import time as _time
            _time.sleep(1)

    def _query_nvidia_smi(self) -> dict:
        """调用 nvidia-smi 获取 GPU 利用率和显存"""
        result = {"util": (0, "—"), "vram": (0, "—")}
        try:
            import subprocess as sp
            out = sp.check_output(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                timeout=2, text=True, stderr=sp.DEVNULL
            ).strip()
            parts = [x.strip() for x in out.split(",")]
            if len(parts) >= 4:
                util  = float(parts[0])
                used  = float(parts[1])
                total = float(parts[2])
                temp  = parts[3]
                vram_pct = (used / total * 100) if total > 0 else 0
                result["util"] = (util,  f"{util:.0f}%  {temp}°C")
                result["vram"] = (vram_pct, f"{used/1024:.1f} / {total/1024:.1f} GB")
        except Exception:
            pass
        return result

    def _update_res_ui(self, data: dict):
        """在主线程更新资源仪表盘 UI"""
        try:
            for key, (pct, label) in data.items():
                if key not in self._res_bars:
                    continue
                cv, bar_id = self._res_bars[key]
                w = cv.winfo_width()
                if w < 2:
                    continue
                fill_w = max(2, int(w * pct / 100))
                # 颜色：绿→黄→红
                if pct < 70:
                    color = self.C["accent"]
                elif pct < 90:
                    color = self.C["amber"]
                else:
                    color = self.C["red"]
                cv.coords(bar_id, 0, 0, fill_w, 8)
                cv.itemconfig(bar_id, fill=color)
                self._res_labels[key].config(text=label)
        except Exception:
            pass

    def _update_load_progress(self, pct: int, status: str):
        """更新模型加载进度条（主线程调用）"""
        try:
            self._load_pct_lbl.config(text=f"{pct}%")
            self._load_status_lbl.config(text=status)
            cv = self._progress_canvas
            w  = cv.winfo_width()
            if w > 2:
                fill_w = max(2, int(w * pct / 100))
                cv.coords(self._progress_bar, 0, 0, fill_w, 10)
        except Exception:
            pass

    def _update_tok_speed(self, speed_str: str):
        try:
            self._tok_lbl.config(text=speed_str)
            import re as _re
            m = _re.search(r"([\d.]+)", speed_str)
            if m and speed_str != "—":
                cur = float(m.group(1))
                if cur > self._tok_max_val:
                    self._tok_max_val = cur
                self._tok_max_lbl.config(
                    text=f"峰值 {self._tok_max_val:.1f} t/s")
        except Exception:
            pass

    def _update_tok_total(self, total_n: int):
        try:
            self._tok_total_val += total_n
            n = self._tok_total_val
            if n >= 1000:
                disp = f"{n/1000:.1f}k tokens"
            else:
                disp = f"{n} tokens"
            self._tok_total_lbl.config(text=disp)
        except Exception:
            pass

    # ── 关闭保护 ──────────────────────────────────────────────
    def _on_close(self):
        if self._server_running:
            ans = messagebox.askyesnocancel(
                "服务仍在运行",
                f"服务正在运行中\n"
                f"模型: {self._srv_cur_model}\n"
                f"PID: {self._server_proc.pid if self._server_proc else '—'}\n\n"
                "是否停止服务后退出？\n"
                "（选「否」将直接退出，服务进程可能仍在后台运行）"
            )
            if ans is None:      # 取消
                return
            if ans:              # 是：先停止
                self._stop_server()
                import time as _t
                _t.sleep(0.5)
        self._monitor_running = False
        self.destroy()

    def _rescan_hardware(self):
        """强制重新扫描硬件信息（更换硬件或首次未获取时使用）"""
        self.cfg.pop("hardware", None)   # 清除缓存
        self._set_st("正在扫描硬件信息...", self.C["amber"])
        self._init_hardware_info()

    def _open_log_file(self):
        """用记事本打开当前或最近的服务日志文件"""
        # 优先打开当前正在写的
        path = self._log_path
        # 没有则找最新的
        if not path or not path.exists():
            logs = sorted(LOGS_DIR.glob("server_*.log"),
                          key=lambda p: p.stat().st_mtime)
            path = logs[-1] if logs else None
        if not path:
            messagebox.showinfo("日志", "日志目录: " + str(LOGS_DIR) + "\n暂无日志文件")
            return
        try:
            os.startfile(str(path))
        except Exception:
            subprocess.Popen(["notepad.exe", str(path)])

    def _open_logs_dir(self):
        """打开日志目录"""
        _ensure_logs_dir()
        try:
            os.startfile(str(LOGS_DIR))
        except Exception:
            pass

    def _copy_apikey(self):
        """一键复制 API Key"""
        key = self._srv_apikey.get().strip()
        if not key:
            self._set_st("API Key 为空", self.C["amber"])
            return
        self.clipboard_clear()
        self.clipboard_append(key)
        self._set_st(f"✓ 已复制 API Key: {key[:20]}...", self.C["accent"])

    def _copy_srv_url(self, with_key: bool = False):
        """复制服务地址，with_key=True 时附带 ?api_key=xxx"""
        port = self._srv_port.get()
        url = f"http://localhost:{port}"
        if with_key:
            key = self._srv_apikey.get().strip()
            if key:
                url = f"http://localhost:{port}/?api_key={key}"
        self.clipboard_clear()
        self.clipboard_append(url)
        label = "地址+APIKey" if with_key else "地址"
        self._set_st(f"✓ 已复制{label}: {url}", self.C["accent"])

    def _switch_model(self):
        """停止当前服务，切换到列表中选中的模型并重启"""
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            messagebox.showwarning("提示", "请先在模型列表中选择目标模型")
            return
        new_model = os.path.basename(self.models[sel[0]])
        if new_model == self._srv_cur_model:
            messagebox.showinfo("提示", f"当前已在运行该模型：{new_model}")
            return
        if not messagebox.askyesno(
            "切换模型",
            f"将停止当前服务\n当前: {self._srv_cur_model}\n切换到: {new_model}\n\n确认切换？"
        ):
            return
        self._stop_server()
        time.sleep(0.8)
        self._launch_server(self.models[sel[0]], self._collect_params())

    def _srv_log_append(self, text: str):
        import re
        self._srv_log.config(state="normal")

        # 选择颜色 tag
        line = text.strip()
        if any(k in line.lower() for k in ["listening", "server started", "ready"]):
            tag = "ready"
            self._srv_ready = True
            # 就绪时进度条推到 100%
            self.after(0, self._update_load_progress, 100, "✓ 加载完成，服务就绪")
            self.after(0, self._srv_status_lbl.config,
                       {"text": "✓  就绪  ( 可以访问 )", "fg": self.C["accent"]})
        elif any(k in line.lower() for k in ["error", "failed", "abort", "fatal"]):
            tag = "err"
        elif any(k in line.lower() for k in ["warn", "warning"]):
            tag = "warn"
        else:
            tag = ""

        # 解析加载进度（仅在未就绪时更新，就绪后锁定100%）
        if not self._srv_ready:
            # 只匹配加载相关行：含 load/layer/model 关键词
            load_keywords = ["load", "layer", "llm_load", "llama_model",
                             "model metadata", "tensor", "backend"]
            is_load_line = any(k in line.lower() for k in load_keywords)

            layer_match = re.search(r"(\d+)\s*/\s*(\d+)", line)
            if layer_match and is_load_line:
                cur, tot = int(layer_match.group(1)), int(layer_match.group(2))
                if tot > 0:
                    pct = min(int(cur / tot * 100), 99)  # 99% max，就绪后才到100%
                    self.after(0, self._update_load_progress, pct,
                               f"layer {cur}/{tot}")
            elif is_load_line and "done" in line.lower():
                self.after(0, self._update_load_progress, 99, line[:50])

        # 解析 token 速度：只匹配 "X tokens per second" 或 "X t/s"
        # 排除 "total time = X ms / N tokens"（总量不是速度）
        speed_match = re.search(
            r"([\d.]+)\s+tokens\s+per\s+second", line, re.I)
        if not speed_match:
            speed_match = re.search(r"([\d.]+)\s*t/s", line, re.I)
        if speed_match:
            self.after(0, self._update_tok_speed,
                       f"{float(speed_match.group(1)):.1f} t/s")

        # 解析已输出 token 总量：匹配 "total time = X ms / N tokens"
        total_tok_match = re.search(
            r"total\s+time\s*=.*?/\s*(\d+)\s+tokens", line, re.I)
        if total_tok_match:
            total_n = int(total_tok_match.group(1))
            self.after(0, self._update_tok_total, total_n)

        ts = f"[{_ts()}] "
        self._srv_log.insert("end", ts, "ts")
        if tag:
            self._srv_log.insert("end", text, tag)
        else:
            self._srv_log.insert("end", text)
        self._srv_log.see("end")
        self._srv_log.config(state="disabled")
        # 同步写入磁盘日志
        if self._log_file:
            try:
                self._log_file.write(text)
                self._log_file.flush()
            except Exception:
                pass

    def _srv_log_clear(self):
        self._srv_log.config(state="normal")
        self._srv_log.delete("1.0", "end")
        self._srv_log.config(state="disabled")

    # ── 目录管理 ───────────────────────────────────────────────
    def _add_dir(self):
        d = filedialog.askdirectory(title="选择模型目录")
        if d:
            dirs = list(self._dir_lb.get(0, "end"))
            if d not in dirs:
                self._dir_lb.insert("end", d)
                self.cfg.setdefault("model_dirs", []).append(d)
                save_config(self.cfg)

    def _del_dir(self):
        sel = self._dir_lb.curselection()
        if sel:
            self._dir_lb.delete(sel[0])
            dirs = list(self._dir_lb.get(0, "end"))
            self.cfg["model_dirs"] = dirs
            save_config(self.cfg)

    # ── 其他 ───────────────────────────────────────────────────
    def _copy_cmd(self):
        sel = self._mlb.curselection()
        if not sel or sel[0] >= len(self.models):
            messagebox.showwarning("提示", "请先选择一个模型")
            return
        model_path = self.models[sel[0]]
        params = self._collect_params()
        if self._mode.get() == "chat":
            cmd = build_chat_cmd(self.cfg, model_path, params)
        else:
            sys_prompt = self._get_active_prompt()
            cmd = build_server_cmd(
                self.cfg, model_path, params,
                self._srv_host.get(), self._srv_port.get(),
                self._srv_apikey.get(), self._srv_slots.get(),
                system_prompt=sys_prompt,
                role_name=self._cur_role_name)
        self.clipboard_clear()
        self.clipboard_append(" ".join(cmd))
        self._set_st("✓ 命令已复制到剪贴板", self.C["accent"])

    def _open_config(self):
        """用记事本打开 config.json"""
        try:
            os.startfile(str(CONFIG_PATH))
        except Exception:
            subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])

    def _set_st(self, msg: str, color: str = None):
        self._statusbar.config(text=f"  {msg}", fg=color or self.C["muted"])


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _launch_powershell(cmd: list, keep_open: bool,
                       system_prompt: str = "", hide_think: bool = False):
    import tempfile, os

    def ps_quote(s):
        return "'" + s.replace("'", "''") + "'"

    # 构建 PS 数组内容（每参数一行，逗号分隔，无末尾逗号）
    arg_items = [ps_quote(c) for c in cmd]
    if system_prompt.strip():
        ptmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8")
        ptmp.write(system_prompt.strip())
        ptmp.close()
        pf_decl = "$prompt_file = " + ps_quote(ptmp.name) + "\n"
        arg_items += ["'- f'", "$prompt_file"]  # placeholder
        # 实际用字符串直接拼，不放入列表
        extra_args = ",\n    '-f', $prompt_file"
    else:
        pf_decl = ""
        extra_args = ""

    inner = ",\n    ".join(ps_quote(c) for c in cmd)
    array_str = ("$a = @(\n"
                 "    " + inner
                 + ((",\n    '-f', $prompt_file") if system_prompt.strip() else "")
                 + "\n)\n")

    lines_ps = [
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$OutputEncoding = [System.Text.Encoding]::UTF8",
        "Write-Host '-------------------------------------' -ForegroundColor DarkGray",
        "Write-Host '  llama.cpp  /  Chat Mode' -ForegroundColor Green",
        "Write-Host '-------------------------------------' -ForegroundColor DarkGray",
        "Write-Host ''",
    ]
    if pf_decl:
        lines_ps.append("$prompt_file = " + ps_quote(ptmp.name))

    # 数组
    lines_ps.append("$a = @(")
    arg_strs = [ps_quote(c) for c in cmd]
    if system_prompt.strip():
        arg_strs_joined = ",\n    ".join(arg_strs)
        lines_ps.append("    " + arg_strs_joined + ",")
        lines_ps.append("    '-f', $prompt_file")
    else:
        arg_strs_joined = ",\n    ".join(arg_strs)
        lines_ps.append("    " + arg_strs_joined)
    lines_ps.append(")")

    if hide_think:
        lines_ps += [
            "# Filter <think>...</think>",
            "$inThink = $false",
            "$thinkDone = $false",
            "& $a[0] $a[1..($a.Length-1)] | ForEach-Object {",
            "    $line = $_",
            "    if ($line -match '<think>') {",
            "        $inThink = $true",
            "        if (-not $thinkDone) {",
            "            Write-Host '[ Thinking... ]' -ForegroundColor DarkGray",
            "        }",
            "        return",
            "    }",
            "    if ($line -match '</think>') {",
            "        $inThink = $false",
            "        $thinkDone = $true",
            "        Write-Host '[ Done thinking ]' -ForegroundColor DarkGray",
            "        return",
            "    }",
            "    if (-not $inThink) { Write-Host $line }",
            "}",
        ]
    else:
        lines_ps.append("& $a[0] $a[1..($a.Length-1)]")

    if keep_open:
        lines_ps += [
            "Write-Host ''",
            "Write-Host '[ Press any key to close ]' -ForegroundColor DarkGray",
            "$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')",
        ]

    script = "\n".join(lines_ps) + "\n"

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False,
        encoding="gbk", errors="replace", newline="")
    tmp.write(script)
    tmp.close()

    subprocess.Popen(
        ["cmd.exe", "/c", "start", "",
         "powershell.exe", "-NoLogo", "-ExecutionPolicy", "Bypass",
         "-File", tmp.name],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 首次运行：显示向导窗口
    if is_first_run():
        root = tk.Tk()
        root.withdraw()   # 隐藏主窗口，只显示向导
        root.title("llama launcher")
        wizard = FirstRunWizard(root)
        root.wait_window(wizard)
        if not wizard.completed:
            # 用户取消向导，退出
            raise SystemExit(0)
        root.destroy()

    # 正常启动主界面
    app = LlamaLauncher()
    app.mainloop()
