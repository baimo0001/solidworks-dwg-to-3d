"""Read native DWG evidence through AutoCAD ActiveX without saving the drawing."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys


def existing_dwg(raw_path):
    path = Path(raw_path).resolve(strict=True)
    if path.suffix.lower() != ".dwg" or not path.is_file():
        raise ValueError("需要本地 .dwg 文件。")
    return path


def digest(path):
    fingerprint = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            fingerprint.update(block)
    return fingerprint.hexdigest()


def dependency_root(requested):
    if requested:
        candidates = [Path(requested)]
    else:
        local_skills = Path(__file__).resolve().parents[2]
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        candidates = [
            root / name
            for root in (local_skills, codex_home / "skills")
            for name in ("solidworks-automation-skill", "solidworks-automation")
        ]
    for candidate in candidates:
        if (candidate / "scripts/sw_session.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError("未找到 solidworks-automation，使用 --solidworks-skill 指定其目录。")


_AUTOCAD_ESCAPES = {
    "%%c": "⌀", "%%d": "°", "%%p": "±",
}
_SYMBOLS = {
    "diameter": r"[⌀ØΦ∅]\s*\d",
    "radius": r"(?<![A-Z])R\s*\d",
    "through": r"\b(?:THRU|THROUGH)\b|(?<!不)通孔|贯穿",
    "blind": r"\bBLIND\b|盲孔|不通孔",
    "depth": r"\bDEPTH\b|深度|孔深|↧",
    "countersink": r"\bCSK\b|沉头|⌵",
    "counterbore": r"\bC(?:'|\s*)BORE\b|平底沉孔|⌴",
    "thread": r"(?<![A-Z0-9])M\s*\d+(?:[.,]\d+)?(?:\s*[×x]\s*\d+(?:[.,]\d+)?)?|螺纹",
    "chamfer": r"\bCHAMFER\b|倒角|\d+(?:[.,]\d+)?\s*[×x]\s*\d+(?:[.,]\d+)?\s*°",
    "tolerance": r"±",
}


def note_text(text):
    text = re.sub(r"\\U\+([0-9a-f]{4})", lambda m: chr(int(m[1], 16)), text, flags=re.I)
    text = re.sub(r"%%[cdp]", lambda m: _AUTOCAD_ESCAPES[m[0].lower()], text, flags=re.I)
    return text.replace(r"\P", "\n")


def symbol_hints(text):
    return [name for name, pattern in _SYMBOLS.items() if re.search(pattern, text, re.I)]


def optional(entity, property_name):
    from pywintypes import com_error

    try:
        return getattr(entity, property_name)
    except (AttributeError, com_error):
        return None


def describe(entity):
    kind = str(entity.ObjectName)
    evidence = {
        "handle": str(entity.Handle), "type": kind, "layer": str(entity.Layer),
        "linetype": str(entity.Linetype), "visible": bool(entity.Visible),
    }
    fields = {
        "AcDbLine": ("StartPoint", "EndPoint"),
        "AcDbCircle": ("Center", "Radius", "Normal"),
        "AcDbArc": ("Center", "StartPoint", "EndPoint", "Radius", "Normal", "StartAngle", "EndAngle"),
        "AcDbPolyline": ("Coordinates", "Closed", "Elevation", "Normal", "ConstantWidth"),
        "AcDb2dPolyline": ("Coordinates", "Closed", "Elevation", "Normal"),
        "AcDbText": ("InsertionPoint", "TextString", "Rotation"),
        "AcDbMText": ("InsertionPoint", "TextString", "Rotation"),
        "AcDbLeader": ("Coordinates",),
        "AcDbMLeader": ("TextString", "ContentType"),
        "AcDbFcf": ("InsertionPoint", "Text"),
        "AcDbBlockReference": (
            "Name", "EffectiveName", "InsertionPoint", "Rotation", "HasAttributes",
            "XScaleFactor", "YScaleFactor", "ZScaleFactor",
        ),
        "AcDbViewport": ("Center", "Width", "Height", "CustomScale"),
    }.get(kind, ())
    if kind.endswith("Dimension"):
        fields = (
            "Measurement", "TextOverride", "TextPosition", "StyleName", "LinearScaleFactor",
            "ExtLine1Point", "ExtLine2Point", "Center", "ChordPoint", "FarChordPoint",
            "ToleranceDisplay", "ToleranceUpperLimit", "ToleranceLowerLimit",
        )
    for field in fields:
        value = optional(entity, field)
        if isinstance(value, (bool, int, float, str, tuple, list)):
            evidence[field] = value
    if kind == "AcDbPolyline" and "Coordinates" in evidence:
        count = len(evidence["Coordinates"]) // 2
        edge_count = count if evidence.get("Closed") else max(0, count - 1)
        evidence["bulges"] = [float(entity.GetBulge(index)) for index in range(edge_count)]
    if kind == "AcDbBlockReference" and evidence.get("HasAttributes"):
        evidence["attributes"] = [
            {"handle": str(attr.Handle), "tag": str(attr.TagString), "text": str(attr.TextString)}
            for attr in entity.GetAttributes()
        ]
    texts = [evidence[key] for key in ("TextString", "TextOverride", "Text") if evidence.get(key)]
    texts.extend(attr["text"] for attr in evidence.get("attributes", []))
    if texts:
        evidence["decoded_text"] = [note_text(value) for value in texts]
        evidence["symbol_hints"] = symbol_hints("\n".join(evidence["decoded_text"]))
    if kind == "AcDbFcf":
        evidence.setdefault("symbol_hints", []).append("feature_control_frame")
    return evidence


def survey(path, root):
    sys.path.insert(0, str(root / "subskills/autocad-automation/scripts"))
    from acad_session import AutoCADSession, _retry_com_busy

    fingerprint = digest(path)
    session = AutoCADSession(visible=True).connect()

    def matching_drawing():
        return next(
            (doc for doc in session.app.Documents if doc.FullName and Path(doc.FullName).resolve() == path),
            None,
        )

    already_open = _retry_com_busy(matching_drawing, "查找目标 DWG") is not None
    try:
        if not already_open:
            session.open_document(path, read_only=True)
        doc = _retry_com_busy(matching_drawing, "连接已打开的目标 DWG")
        if doc is None or (not already_open and not _retry_com_busy(lambda: doc.ReadOnly, "检查只读状态")):
            raise RuntimeError("AutoCAD 未以只读方式打开目标 DWG。")
        if already_open and not doc.Saved:
            raise ValueError("DWG 有未保存的编辑。请提供已保存的版本，避免标注与源文件不一致。")
        layouts = []
        for layout in doc.Layouts:
            layouts.append({
                "name": str(layout.Name),
                "model_space": bool(layout.ModelType),
                "entities": [describe(entity) for entity in layout.Block],
            })
        result = {
            "source": str(path), "source_sha256": fingerprint, "insunits": int(doc.GetVariable("INSUNITS")),
            "layers": [
                {"name": str(layer.Name), "linetype": str(layer.Linetype),
                 "on": bool(layer.LayerOn), "frozen": bool(layer.Freeze)}
                for layer in doc.Layers
            ],
            "layouts": layouts,
        }
        if digest(path) != fingerprint or (already_open and not doc.Saved):
            raise RuntimeError("读取期间 DWG 版本发生变化，请重新读取。")
        return result
    finally:
        if not already_open:
            def close_read_only_drawing():
                opened = matching_drawing()
                if opened is not None and opened.ReadOnly:
                    opened.Close(False)

            _retry_com_busy(close_read_only_drawing, "关闭本次只读打开的 DWG")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dwg")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--solidworks-skill")
    args = parser.parse_args()
    try:
        root = dependency_root(args.solidworks_skill)
        if args.output.exists() or args.output.suffix.lower() != ".json":
            raise ValueError("输出须为尚不存在的 .json 文件。")
        report = survey(existing_dwg(args.dwg), root)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(serialized + "\n")
        print(f"已读取 {len(report['layouts'])} 个布局，证据文件：{args.output.resolve()}")
    except (OSError, ValueError, RuntimeError, AttributeError, ImportError) as error:
        parser.exit(1, f"DWG 读取失败：{error}\n")


if __name__ == "__main__":
    main()
