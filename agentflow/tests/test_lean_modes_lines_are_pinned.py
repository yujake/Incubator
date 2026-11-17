# -*- coding: utf-8 -*-
"""`docs/LEAN-MODES.md` 的逐行钉住判据（AU2b 乙组·④）。

## 为什么这样钉

旧版开头自述「`tests/test_lean_modes_matrix.py` 逐行断言这里的每一条」，实测不成立：
那份判据只覆盖可执行差异（第一行 / V 的强度 / `check_formal` 直拒 / `detect_verifier` /
M 与 L 的义务句 / 画像 / 索引 / H 的措辞）。把整份矩阵的每一行都做成语义判据，等于再实现一遍
矩阵（而多数行是环境读数：检查器可用性、超时、版本），也只能靠人复核。

所以这里选的是「逐行钉住」：每一行一个 sha256 前缀，一行改了判据就红 ——
改的人必须回答「这一条还成立吗、对应哪条判据」，不许让文档静默过期。
可执行的那部分仍由 `test_lean_modes_matrix.py` 语义断言。
"""
from __future__ import annotations

import hashlib
import pathlib

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "LEAN-MODES.md"

#: 1-based 行号 -> 该行 sha256 的前 12 位。
_LINES = {
    1: "904039ff736d",
    2: "e3b0c44298fc",
    3: "890e4d76c9b4",
    4: "0817477edf13",
    5: "2b54500be088",
    6: "237ce44fcbc7",
    7: "e3121f8d52e0",
    8: "297a33f9da46",
    9: "569e8eff169e",
    10: "dfec8e6862b9",
    11: "e3b0c44298fc",
    12: "7b9bce69771b",
    13: "e3b0c44298fc",
    14: "1c7c2d0aade0",
    15: "4da1ec6f4778",
    16: "bf91db63f101",
    17: "85baa5bb6036",
    18: "e3b0c44298fc",
    19: "166113b403e4",
    20: "e3b0c44298fc",
    21: "add88ad44514",
    22: "e2501a351cea",
    23: "0d54865e6706",
    24: "03820d2c322a",
    25: "e3b0c44298fc",
    26: "ff9a37bf098f",
    27: "e3b0c44298fc",
    28: "02b14a711b86",
    29: "23cca02b74f3",
    30: "80cd87595c51",
    31: "af783ed5a5fd",
    32: "70b2c86a7f27",
    33: "1ac1e180b2d8",
    34: "e3b0c44298fc",
    35: "16161af1ca16",
    36: "e3b0c44298fc",
    37: "12f587eeb4e8",
    38: "23cca02b74f3",
    39: "2a00f810b2e0",
    40: "5df0557721c3",
    41: "ff404df105d3",
    42: "0b21ad29b671",
    43: "2779cf7960e3",
    44: "0eb2acf79dd2",
    45: "a0421a9d4399",
    46: "e3b0c44298fc",
    47: "83cc601d5c6b",
    48: "e3b0c44298fc",
    49: "12f587eeb4e8",
    50: "23cca02b74f3",
    51: "12781a3072ff",
    52: "b3247540110c",
    53: "b62524b2589d",
    54: "c6df516dc8e9",
    55: "e3b0c44298fc",
    56: "90cf3c0177ee",
    57: "e3b0c44298fc",
    58: "162b317bb470",
    59: "23cca02b74f3",
    60: "c927717bdd77",
    61: "2d6e238cf69f",
    62: "c85da62810a6",
    63: "3a22bb0ee0f4",
    64: "5b6f05b22a43",
    65: "08fd87b17e85",
    66: "e3b0c44298fc",
    67: "3449b8d69785",
    68: "e3b0c44298fc",
    69: "5f89c33048d4",
    70: "e3b0c44298fc",
    71: "09c348fd3f69",
    72: "23cca02b74f3",
    73: "9e6ea6eba2e2",
    74: "82aef5e6ad84",
    75: "58e8d9b18301",
    76: "e3b0c44298fc",
    77: "1d3faf762783",
    78: "e3b0c44298fc",
    79: "0f417cd68b9d",
    80: "e3b0c44298fc",
    81: "2d070156875c",
    82: "23cca02b74f3",
    83: "b4803b513cd5",
    84: "d3f8c9a2ee0a",
    85: "6189c34e10ff",
    86: "6ae19c2e4921",
    87: "e3b0c44298fc",
    88: "c046f67ecd87",
    89: "e3b0c44298fc",
    90: "de1ea74d1608",
    91: "e3b0c44298fc",
    92: "a950b8c52758",
    93: "23cca02b74f3",
    94: "f29383ef26dc",
    95: "21ea43afd47b",
    96: "317909c092af",
    97: "61550d50f09a",
    98: "4bdb481ff899",
    99: "2bdda8b3b6b2",
    100: "1ce73a6bab2d",
    101: "e3b0c44298fc",
    102: "5c6241fda452",
    103: "e3b0c44298fc",
    104: "e9e9af9fdba9",
    105: "e3b0c44298fc",
    106: "27bde934f405",
    107: "e4b6c1ab9239",
    108: "e3b0c44298fc",
    109: "3d14c820a99e",
    110: "e3b0c44298fc",
    111: "dd2e00211479",
    112: "e3b0c44298fc",
    113: "baf2aaa0d8c3",
    114: "2bb3248cc2b7",
    115: "84a1bf61f58d",
    116: "e3b0c44298fc",
    117: "6f0cac9f6e11",
    118: "e3b0c44298fc",
    119: "348dbe82fdb8",
    120: "02e99bbdf288",
}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def test_every_line_of_lean_modes_is_pinned() -> None:
    """逐行钉住：行数、行号集合与每一行的 sha256 都必须与快照一致。"""
    text = DOC.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) >= 100, f"只读到 {len(lines)} 行 ⇒ 读错文件或文档被截断"
    live = {i: _digest(line) for i, line in enumerate(lines, 1)}
    assert set(live) == set(_LINES), (set(live) - set(_LINES), set(_LINES) - set(live))
    stale = [i for i in sorted(live) if live[i] != _LINES[i]]
    assert not stale, (
        "这些行变了（改完请回答：这一条还成立吗、对应哪条判据，然后重记这一行）："
        + "、".join(str(i) for i in stale))


def test_the_self_description_is_true() -> None:
    """开头那句不许再声称「逐行断言」；它必须说清哪部分可执行、哪部分靠逐行钉住。"""
    head = "\n".join(DOC.read_text(encoding="utf-8").splitlines()[:14])
    assert "逐行断言这里的每一条" not in head
    assert "可执行的那部分" in head
    assert "每一行" in head and "sha256" in head
