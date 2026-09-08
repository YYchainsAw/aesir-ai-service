"""真人声 ASR 调优评测脚本。

用法：
    1. 准备样本：``data/asr_samples/`` 下放 WAV（16kHz/单声道/16bit），
       文件名即期望文本，如 ``艾琳撤退并优先保命.wav``（无需标点，评测前会去标点）。
    2. 配置环境（PowerShell，参考 .env.example / README）：
       $env:HF_ENDPOINT = "https://hf-mirror.com"   # 首次下载模型
       $env:AESIR_ASR_MODEL = "small"                # 要对比的模型
    3. 运行：
       .\.venv\Scripts\python scripts\asr_eval.py
       .\.venv\Scripts\python scripts\asr_eval.py --model medium --beam 5 --no-vad  # 参数扫描

输出每条样本的转写结果、字错误率（CER）与耗时，以及整体平均；用于对比
模型/beam/VAD 组合，选出 8GB 显存下的最优配置。
"""

import argparse
import time
from pathlib import Path

from app.config import get_settings
from app.services.transcribers.faster_whisper import _load_model

SAMPLES_DIR = Path("data/asr_samples")

# 评测时不计入 CER 的标点与空白
_STRIP = set("，。！？、,.!?;；:：'\"“”‘’ \t\n")


def _normalize(text: str) -> str:
    return "".join(ch for ch in text if ch not in _STRIP)


def _cer(reference: str, hypothesis: str) -> float:
    """字错误率：编辑距离 / 参考长度（参考为空时返回 0/1 视是否非空）。"""
    ref, hyp = _normalize(reference), _normalize(hypothesis)
    if not ref:
        return 1.0 if hyp else 0.0
    # 常规编辑距离 DP
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, hc in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(ref)


def main() -> None:
    parser = argparse.ArgumentParser(description="真人声 ASR 调优评测")
    parser.add_argument("--dir", default=str(SAMPLES_DIR), help="样本目录")
    parser.add_argument("--model", default=None, help="覆盖 AESIR_ASR_MODEL")
    parser.add_argument("--beam", type=int, default=1, help="beam_size（默认 1=贪心）")
    parser.add_argument("--no-vad", action="store_true", help="关闭 VAD 过滤")
    args = parser.parse_args()

    import os

    if args.model:
        os.environ["AESIR_ASR_MODEL"] = args.model

    samples = sorted(Path(args.dir).glob("*.wav"))
    if not samples:
        raise SystemExit(
            f"未找到样本：请在 {args.dir} 放置 WAV，文件名即期望文本，"
            "如「艾琳撤退并优先保命.wav」。"
        )

    model = _load_model()
    settings = get_settings()
    language = settings.asr_language
    print(
        f"模型={settings.asr_model} 设备={settings.asr_device} 量化={settings.asr_compute_type} "
        f"beam={args.beam} vad={not args.no_vad} 语言={language} 样本数={len(samples)}\n"
    )

    total_cer, total_sec = 0.0, 0.0
    for wav in samples:
        expected = wav.stem
        start = time.perf_counter()
        segments, _info = model.transcribe(
            str(wav),
            language=language,
            beam_size=args.beam,
            vad_filter=not args.no_vad,
        )
        text = "".join(seg.text for seg in segments).strip()
        elapsed = time.perf_counter() - start

        cer = _cer(expected, text)
        total_cer += cer
        total_sec += elapsed
        mark = "OK " if cer == 0 else "ERR"
        print(f"[{mark}] {wav.name}")
        print(f"      期望: {expected}")
        print(f"      转写: {text}")
        print(f"      CER={cer:.2%}  耗时={elapsed:.2f}s\n")

    print(
        f"平均 CER={total_cer / len(samples):.2%}  平均耗时={total_sec / len(samples):.2f}s"
    )


if __name__ == "__main__":
    main()
