"""人格包内容哈希（S5 / T30 / issue #39）。

为外部人格包提供**可重算、确定性**的内容校验和：任何人用同一函数对同一目录重跑必得同值。

设计要点：
- 基于**文件原始字节**（非解析后 dict）——YAML 注释 / 空行 / 序列化顺序的改动也能被捕获；
  仅 ``manifest.yaml`` 例外（见下）。
- 按文件名字典序拼接，文件名参与哈希绑定，文件间用 RS/US 分隔符防止 ``"ab"+"c"`` 歧义。
- **破循环**：``manifest.yaml`` 自身的 ``checksum`` 字段不能参与哈希（否则哈希依赖它自己）。
  处理方式：唯一一次解析该文件 -> 删除 ``checksum`` 字段 -> 规范重序列化（``sort_keys``）。
  这样 ``checksum: null`` 那一行的注释/取值改动不影响哈希，但 manifest 其他字段（如
  ``profile_version`` / ``origin``）的改动仍会改变哈希，满足「内容篡改必检出」。
- 只取包目录**顶层** ``*.yaml``（不递归子目录），排除 ``__pycache__`` 与隐藏文件——
  避免外部包塞进任意文件稀释哈希范围。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


class PackChecksumError(RuntimeError):
    """人格包校验和计算失败（目录不存在 / 无 YAML 文件 / manifest 损坏）。"""


# 记录分隔符（RS）与单元分隔符（US）：避免文件名与字节流拼接的歧义。
_RS = b"\x1e"
_US = b"\x1f"

_MANIFEST = "manifest.yaml"


def compute_pack_checksum(pack_dir: Path) -> str:
    """计算人格包内容哈希，返回 ``"sha256:<hex>"``。

    目录不存在、不是目录、或目录下没有任何顶层 YAML 文件时抛 ``PackChecksumError``。
    """
    if not pack_dir.is_dir():
        raise PackChecksumError(f"Pack directory does not exist: {pack_dir}")

    yaml_files = sorted(
        p.name
        for p in pack_dir.iterdir()
        if p.is_file() and p.suffix == ".yaml" and not p.name.startswith(".") and p.name != "__pycache__"
    )
    if not yaml_files:
        raise PackChecksumError(f"No top-level YAML files found in pack: {pack_dir}")

    digest = hashlib.sha256()
    for name in yaml_files:
        raw = (pack_dir / name).read_bytes()
        if name == _MANIFEST:
            raw = _manifest_bytes_without_checksum(raw)
        digest.update(name.encode("utf-8"))
        digest.update(_RS)
        digest.update(raw)
        digest.update(_US)

    return f"sha256:{digest.hexdigest()}"


def _manifest_bytes_without_checksum(raw: bytes) -> bytes:
    """解析 manifest、删除 ``checksum`` 字段、规范重序列化（破循环的唯一解析点）。"""
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as error:
        raise PackChecksumError(f"Unable to parse manifest.yaml: {error}") from error
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise PackChecksumError("manifest.yaml must be a YAML mapping.")

    data.pop("checksum", None)
    return yaml.safe_dump(
        data,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    ).encode("utf-8")
