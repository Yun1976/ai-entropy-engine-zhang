#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
density_meter.py — DENSITY-001 可计算信息密度度量核心（2026-10-07）
=====================================================================
创始人令: openai/math 可用成果应用于端点星-观自在系统, 特别是信息密度实验。

理论基础(见 vault 04-Science-Reports/2026-10-07-openai-math-catalog-digest.md):
  - 113 完美匹配熵/近似计数 → 结构熵可用压缩器逼近: 熵率 = C(x)/|x|
  - 119 Courtade–Kumar/Hellinger(噪声稳定性) → 「新颖度」(对语料)与「存活性」
    (经受独立重导)是两个独立维度, 必须分开度量; 存活性由盲重导(dual_judge 模式)
    承担, 本模块管前者的确定性部分。
度量:
  entropy_rate  = lzma(x)/|x|            字节/字符 — 绝对密度
  novelty_ngram = 1 - |ngrams(x)∩corpus|/|ngrams(x)|  — 对语料的新颖比例
  marginal_gain = C(corpus+x) - C(corpus) 字节 — 边际信息增益(NCD 思想)
红线: 只读输入文件; state.db 留痕; 告警只 append alerts.jsonl; 永不写语料库。
2026-10-11 math hooks (default OFF): --math-bounds / MATH_BOUNDS=1 (#113);
  --noise-contraction / NOISE_CONTRACTION=1 (#119); subcommand math-smoke.
用法:
  python density_meter.py file <path>                     单文件画像
  python density_meter.py gate <path> --corpus <dir>      反冗余门禁(novelty<阈值→拒)
  python density_meter.py baseline <dir> [--out json]     目录时间序列基线
"""
import argparse
import datetime as _dt
import io
import json
import lzma
import re
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))
import state_layer  # noqa: E402

ALERTS = Path.home() / ".dsh" / "endpoint-star" / "anti-entropy-alerts.jsonl"
NOVELTY_FLOOR = 0.10   # 语料级反冗余门禁: 新颖度低于10%视为重复灌注
NGRAM = 8


def _lzma(b: bytes) -> int:
    return len(lzma.compress(b, preset=6 | lzma.PRESET_EXTREME))


def profile(text: str) -> dict:
    raw = text.encode("utf-8")
    return {
        "chars": len(text),
        "bytes": len(raw),
        "compressed": _lzma(raw),
        "entropy_rate": round(_lzma(raw) / max(1, len(raw)), 4),
    }


def ngrams(text: str, n=NGRAM):
    s = re.sub(r"\s+", "", text)
    return {s[i:i + n] for i in range(0, max(0, len(s) - n + 1))}


def novelty(text: str, corpus_texts) -> float:
    g = ngrams(text)
    if not g:
        return 0.0
    seen = set()
    for c in corpus_texts:
        seen |= ngrams(c)
    return round(1.0 - len(g & seen) / len(g), 4)


def marginal_gain(corpus_concat: bytes, note: str) -> dict:
    nb = note.encode("utf-8")
    base = _lzma(corpus_concat)
    joint = _lzma(corpus_concat + b"\n" + nb)
    gain = joint - base
    return {"gain_bytes": gain,
            "gain_ratio": round(gain / max(1, len(nb)), 4)}


def _read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def _audit(event, detail):
    try:
        state_layer.add_event(message=f"{event}: {json.dumps(detail, ensure_ascii=False)[:400]}",
                              module="density_meter",
                              verified_by="python density_meter.py <cmd>")
    except Exception as e:  # 留痕失败不阻断度量, 但显式报告
        print(f"[warn] state.db 留痕失败: {e}", file=sys.stderr)


def _alert(kind, msg):
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "tool": "density_meter",
           "kind": kind, "msg": msg}
    with io.open(ALERTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")



# ---------------------------------------------------------------------------
# openai/math hooks (2026-10-11) — DEFAULT OFF
# #113 Matching entropy bounds → structural entropy / compression sanity
# #119 Courtade–Kumar contraction → residual-e / noise-gate stub
# Additive only: never writes vault/corpus; alerts append-only; production
# gate/baseline paths unchanged unless flags/env explicitly enabled.
# ---------------------------------------------------------------------------
import os as _os

def _flag_on(cli_val: bool, env_name: str) -> bool:
    if cli_val:
        return True
    v = (_os.environ.get(env_name) or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def math_bounds_smoke(text: str, corpus_texts=None) -> dict:
    """#113-style soft check (NOT a Lean proof).

    Heuristics only:
      - entropy_rate in (0, 1.05] for typical UTF-8 prose (lzma/|bytes|)
      - duplicate self-append marginal gain_ratio should collapse toward 0
        (conditional / residual compression must not systematically stay high)
    Returns verdict PASS/WARN; never raises into production write paths.
    """
    pr = profile(text)
    er = float(pr["entropy_rate"])
    issues = []
    if er <= 0:
        issues.append("entropy_rate_nonpositive")
    if er > 1.05:
        # theoretically possible for tiny/binary blobs; soft warn only
        issues.append("entropy_rate_above_unit_soft")

    # Self-duplication: C(x+x) - C(x) should be << C(x) relative to |x|
    dup = marginal_gain(text.encode("utf-8"), text)
    if dup["gain_ratio"] > 0.55:
        issues.append("self_dup_gain_not_contracting")

    if corpus_texts:
        concat = b"\n".join(t.encode("utf-8") for t in corpus_texts)
        mg = marginal_gain(concat, text)
        # If novelty is near-zero but gain stays high → #113-style inconsistency soft flag
        nov = novelty(text, corpus_texts)
        if nov < 0.05 and mg["gain_ratio"] > 0.40:
            issues.append("low_novelty_high_marginal_gain")

    verdict = "PASS" if not issues else "WARN"
    return {
        "hook": "math_bounds_#113",
        "entropy_rate": er,
        "self_dup_gain_ratio": dup["gain_ratio"],
        "issues": issues,
        "verdict": verdict,
        "note": "proxy only; Lean scope MatchingEntropyBounds — do not equate lzma rate to H(x)",
    }


def noise_contraction_smoke(text: str, corpus_concat: bytes, eps: float = 0.15) -> dict:
    """#119-style noise-contraction stub (NOT Courtade–Kumar numerical proof).

    Correlate 'noise' by randomly dropping / repeating chars (proxy channel).
    Expect marginal_gain of noisy version vs corpus to be <= clean gain + slack.
    """
    import random
    rng = random.Random(119)  # deterministic smoke
    chars = list(text)
    if len(chars) < 8:
        return {"hook": "noise_contraction_#119", "verdict": "SKIP", "reason": "text_too_short"}

    # BSC-like: flip/drop ~eps fraction of characters
    noisy = []
    for ch in chars:
        if rng.random() < eps:
            if rng.random() < 0.5:
                continue  # drop
            noisy.append(chars[rng.randrange(len(chars))])  # substitute
        else:
            noisy.append(ch)
    noisy_text = "".join(noisy) or text

    clean = marginal_gain(corpus_concat, text)
    noisy_mg = marginal_gain(corpus_concat, noisy_text)
    # Contraction expectation (soft): noise should not *increase* retained info vs corpus
    slack = 0.08
    ok = noisy_mg["gain_ratio"] <= clean["gain_ratio"] + slack
    return {
        "hook": "noise_contraction_#119",
        "eps": eps,
        "clean_gain_ratio": clean["gain_ratio"],
        "noisy_gain_ratio": noisy_mg["gain_ratio"],
        "slack": slack,
        "verdict": "PASS" if ok else "WARN",
        "note": "stub channel; Lean CourtadeKumar is binary-cube I(f;Y) bound — not this proxy",
    }


def cmd_math_smoke(args):
    """Optional smoke entry: python density_meter.py math-smoke <path> [--corpus DIR]"""
    note_path = Path(args.path)
    text = _read(note_path)
    corpus_texts = []
    corpus_concat = b""
    if getattr(args, "corpus", None):
        corpus_dir = Path(args.corpus)
        corpus_texts = [_read(p) for p in sorted(corpus_dir.glob("*.md"))]
        corpus_concat = b"\n".join(t.encode("utf-8") for t in corpus_texts)

    out = {"path": str(note_path)}
    if _flag_on(True, "MATH_BOUNDS"):  # subcommand itself implies on
        out["math_bounds"] = math_bounds_smoke(text, corpus_texts or None)
    if _flag_on(bool(getattr(args, "noise_contraction", False)) or True, "NOISE_CONTRACTION"):
        # math-smoke runs both; individual flags on gate/file remain default-off
        out["noise_contraction"] = noise_contraction_smoke(
            text, corpus_concat if corpus_concat else text.encode("utf-8"))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    _audit("math_smoke", {k: (v.get("verdict") if isinstance(v, dict) else v)
                          for k, v in out.items()})
    # WARN does not fail process (exit 0) — production red line: smoke != gate reject
    return 0


def cmd_file(args):
    text = _read(Path(args.path))
    pr = profile(text)
    print(json.dumps(pr, ensure_ascii=False, indent=1))
    _audit("file_profile", {"path": args.path, **pr})


def cmd_gate(args):
    note_path = Path(args.path)
    corpus_dir = Path(args.corpus)
    texts = [_read(p) for p in sorted(corpus_dir.glob("*.md"))]
    text = _read(note_path)
    nov = novelty(text, [t for t in texts if t != text])
    pr = profile(text)
    mg = marginal_gain(b"\n".join(t.encode("utf-8") for t in texts), text)
    verdict = "PASS" if nov >= NOVELTY_FLOOR else "REJECT"
    out = {"path": str(note_path), "novelty": nov, "floor": NOVELTY_FLOOR,
           "entropy_rate": pr["entropy_rate"], **mg, "verdict": verdict}
    # Optional math hooks (default OFF) — never flip PASS→REJECT by themselves
    if _flag_on(getattr(args, "math_bounds", False), "MATH_BOUNDS"):
        out["math_bounds"] = math_bounds_smoke(text, [t for t in texts if t != text])
    if _flag_on(getattr(args, "noise_contraction", False), "NOISE_CONTRACTION"):
        concat = b"\n".join(t.encode("utf-8") for t in texts)
        out["noise_contraction"] = noise_contraction_smoke(text, concat)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    _audit("gate", out)
    if verdict == "REJECT":
        _alert("density_gate_reject",
               f"{note_path.name} 新颖度 {nov:.2%} < {NOVELTY_FLOOR:.0%}: 与语料重复, 拒绝入库建议")
        return 2
    return 0


def cmd_baseline(args):
    d = Path(args.dir)
    files = sorted(d.glob("*.md"))
    rows, corpus_bytes = [], b""
    for p in files:
        t = _read(p)
        pr = profile(t)
        m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", p.name)
        day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        rows.append({"file": p.name, "day": day, **pr})
        corpus_bytes += t.encode("utf-8") + b"\n"
    # 边际增益按时间序累进 = 每天对既有语料的真实增量
    seen = b""
    for r in rows:
        t = _read(d / r["file"])
        mg = marginal_gain(seen, t)
        r["marginal_gain"] = mg["gain_bytes"]
        r["gain_ratio"] = mg["gain_ratio"]
        seen += t.encode("utf-8") + b"\n"
    out = {"dir": str(d), "n": len(rows),
           "mean_entropy_rate": round(sum(r["entropy_rate"] for r in rows) / max(1, len(rows)), 4),
           "mean_gain_ratio": round(sum(r["gain_ratio"] for r in rows) / max(1, len(rows)), 4),
           "rows": rows}
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(
            json.dumps(out, ensure_ascii=False, indent=1))
        print(f"baseline saved: {args.out}")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))
    _audit("baseline", {"dir": str(d), "n": len(rows),
                        "mean_entropy_rate": out["mean_entropy_rate"]})
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("file").add_argument("path")
    g = sub.add_parser("gate")
    g.add_argument("path")
    g.add_argument("--corpus", required=True)
    g.add_argument("--math-bounds", action="store_true",
                   help="optional #113-style compression/entropy sanity (default off)")
    g.add_argument("--noise-contraction", action="store_true",
                   help="optional #119-style noise-contraction stub (default off)")
    b = sub.add_parser("baseline")
    b.add_argument("dir")
    b.add_argument("--out", default="")
    ms = sub.add_parser("math-smoke",
                        help="opt-in #113+#119 smoke checks; never writes vault")
    ms.add_argument("path")
    ms.add_argument("--corpus", default="")
    args = ap.parse_args()
    return {"file": cmd_file, "gate": cmd_gate, "baseline": cmd_baseline,
            "math-smoke": cmd_math_smoke}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
