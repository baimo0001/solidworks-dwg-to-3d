"""Build and reopen a SolidWorks part from a drawing-grounded reconstruction plan."""

import argparse
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from inspect_dwg import dependency_root, digest, existing_dwg


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"需要有限数值，收到 {value!r}。")
    return float(value)


def positive(value):
    value = number(value)
    if value <= 0:
        raise ValueError("尺寸、直径和深度必须大于零。")
    return value


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"二维点必须是 [x, y]，收到 {value!r}。")
    return tuple(map(number, value))


def validate_plan(plan, report, source):
    if plan["source_sha256"] != report["source_sha256"] or digest(source) != plan["source_sha256"]:
        raise ValueError("源 DWG、读取报告与建模参数的 SHA-256 不一致。")
    handles = {entity["handle"].upper() for layout in report["layouts"] for entity in layout["entities"]}
    for item in [plan["base"], *plan["holes"]]:
        if not item["basis"].strip() or not item["evidence_handles"]:
            raise ValueError("每项特征须说明图纸依据并引用实体句柄。")
        if not isinstance(item["evidence_handles"], list):
            raise ValueError("evidence_handles 必须是句柄列表。")
        missing = {ref.upper() for ref in item["evidence_handles"]} - handles
        if missing:
            raise ValueError(f"读取报告中找不到句柄：{', '.join(sorted(missing))}。")

    base = plan["base"]
    thickness = positive(base["thickness_mm"])
    width, height = point(base["size_mm"])
    positive(width)
    positive(height)
    profile = base["profile"]
    if "center_mm" in profile:
        if "edges" in profile or "start_mm" in profile:
            raise ValueError("圆形轮廓和分段轮廓只能指定一种。")
        point(profile["center_mm"])
        positive(profile["diameter_mm"])
    else:
        start = previous = point(profile["start_mm"])
        for edge in profile["edges"]:
            end = point(edge["end_mm"])
            if end == previous:
                raise ValueError("轮廓存在零长度边。")
            if "via_mm" in edge and point(edge["via_mm"]) in (previous, end):
                raise ValueError("圆弧中间点必须区别于两端。")
            previous = end
        if len(profile["edges"]) < 2 or previous != start:
            raise ValueError("外轮廓的最后一条边必须回到起点。")

    for hole in plan["holes"]:
        point(hole["center_mm"])
        positive(hole["diameter_mm"])
        if hole["kind"] == "blind_flat":
            if positive(hole["depth_mm"]) >= thickness:
                raise ValueError("盲孔深度须小于板厚。")
        elif hole["kind"] != "through" or "depth_mm" in hole:
            raise ValueError("孔类型须为 through 或 blind_flat，只有盲孔填写 depth_mm。")


def draw_profile(model, profile):
    from sw_connect import mm
    from sw_part import sketch_circle, sketch_line

    if "center_mm" in profile:
        x, y = map(mm, profile["center_mm"])
        if sketch_circle(model, x, y, mm(profile["diameter_mm"] / 2)) is None:
            raise RuntimeError("SolidWorks 未创建圆形轮廓。")
        return

    x1, y1 = map(mm, profile["start_mm"])
    for edge in profile["edges"]:
        x2, y2 = map(mm, edge["end_mm"])
        if "via_mm" in edge:
            mx, my = map(mm, edge["via_mm"])
            segment = model.SketchManager.Create3PointArc(x1, y1, 0, x2, y2, 0, mx, my, 0)
        else:
            segment = sketch_line(model, x1, y1, x2, y2)
        if segment is None:
            raise RuntimeError("SolidWorks 未创建轮廓边。")
        x1, y1 = x2, y2


def solid_body(model):
    from sw_connect import get_com_member

    bodies = get_com_member(model, "GetBodies2", 0, False) or ()
    if len(bodies) != 1:
        raise RuntimeError(f"预期单个实体，SolidWorks 返回 {len(bodies)} 个。")
    return bodies[0]


def measure_part(model):
    from sw_connect import get_com_member
    from sw_spring import exact_body_bounds_mm

    body = solid_body(model)
    props = get_com_member(model.Extension, "CreateMassProperty")
    volume = positive(get_com_member(props, "Volume") * 1e9)
    return volume, exact_body_bounds_mm(body)


def verify_hole_faces(model, holes, thickness):
    from sw_connect import get_com_member, mm

    if not holes:
        return
    cylinders = []
    for face in get_com_member(solid_body(model), "GetFaces"):
        surface = get_com_member(face, "GetSurface")
        if not get_com_member(surface, "IsCylinder"):
            continue
        x, y, _, _, _, axis_z, radius = get_com_member(surface, "CylinderParams")
        if not math.isclose(abs(axis_z), 1.0, abs_tol=1e-7):
            continue
        depth_mm = get_com_member(face, "GetArea") / (math.tau * radius) * 1000
        cylinders.append(((x, y, radius), depth_mm))
    for index, hole in enumerate(holes, start=1):
        x, y = map(mm, hole["center_mm"])
        nominal = (x, y, mm(hole["diameter_mm"] / 2))
        actual_depth = sum(
            depth for geometry, depth in cylinders
            if all(math.isclose(a, b, rel_tol=0, abs_tol=1e-6) for a, b in zip(geometry, nominal))
        )
        expected_depth = thickness if hole["kind"] == "through" else hole["depth_mm"]
        if actual_depth <= 0 or not math.isclose(actual_depth, expected_depth, rel_tol=0, abs_tol=0.001):
            raise RuntimeError(f"重开后第 {index} 个孔的中心、直径或圆柱段深度与建模参数不符。")


def check_size(actual, expected):
    if not all(math.isclose(value, target, abs_tol=0.001) for value, target in zip(actual, expected)):
        raise RuntimeError(f"实体尺寸与图纸参数不符，实测 {actual} mm，目标 {expected} mm。")


def build(plan, output, root, version, template):
    sys.path.insert(0, str(root / "scripts"))
    from sw_connect import mm
    from sw_part import extrude_boss, extrude_cut, sketch, sketch_circle
    from sw_session import SolidWorksSession

    base = plan["base"]
    thickness = base["thickness_mm"]
    expected_size = [*base["size_mm"], thickness]
    with TemporaryDirectory(prefix="dwg-to-3d-", dir=output.parent) as staging:
        staged_part = Path(staging) / (Path(staging).name + ".SLDPRT")
        with SolidWorksSession(version=version, wait_seconds=8) as session:
            model = session.new_part(template_path=template)
            with sketch(model) as outline:
                draw_profile(model, base["profile"])
            if extrude_boss(model, outline, mm(thickness), direction=False) is None:
                raise RuntimeError("SolidWorks 未生成基体拉伸。")
            volume, size = measure_part(model)
            check_size(size, expected_size)
            checked_holes = []
            for index, hole in enumerate(plan["holes"], start=1):
                through = hole["kind"] == "through"
                depth = thickness if through else hole["depth_mm"]
                radius = hole["diameter_mm"] / 2
                x, y = map(mm, hole["center_mm"])
                with sketch(model) as hole_sketch:
                    if sketch_circle(model, x, y, mm(radius)) is None:
                        raise RuntimeError(f"SolidWorks 未创建第 {index} 个孔的轮廓。")
                if extrude_cut(model, hole_sketch, 0 if through else mm(depth), direction=True) is None:
                    raise RuntimeError(f"SolidWorks 未生成第 {index} 个孔。")
                new_volume, _ = measure_part(model)
                removed = volume - new_volume
                if not math.isclose(removed, math.pi * radius**2 * depth, rel_tol=1e-5, abs_tol=1e-5):
                    raise RuntimeError(
                        f"第 {index} 个孔的去除体积异常 ({removed:.6g} mm³)，请复核孔位、深度和相交。"
                    )
                checked_holes.append({"kind": hole["kind"], "removed_mm3": round(removed, 6)})
                volume = new_volume
            model.ShowNamedView2("*Isometric", 7)
            model.ViewZoomtofit2()
            if not session.save(model, staged_part) or not staged_part.is_file():
                raise RuntimeError("SolidWorks 未保存零件。")
            session.close(model=model)
            reopened = session.open(staged_part, read_only=True, silent=True)
            reopened_volume, reopened_size = measure_part(reopened)
            check_size(reopened_size, expected_size)
            verify_hole_faces(reopened, plan["holes"], thickness)
            if not math.isclose(reopened_volume, volume, rel_tol=1e-8, abs_tol=1e-5):
                raise RuntimeError("保存重开后零件体积发生变化。")
            revision = session.connection_info["actual_revision"]
        # Windows rename fails if another process created the destination during this run.
        staged_part.rename(output)
    return {
        "part_file": str(output),
        "solidworks_revision": revision,
        "solid_bodies": 1,
        "size_mm": [round(value, 6) for value in reopened_size],
        "volume_mm3": round(reopened_volume, 6),
        "checked_holes": checked_holes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dwg")
    parser.add_argument("--inspection", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--solidworks-year", type=int)
    parser.add_argument("--part-template", type=Path)
    parser.add_argument("--solidworks-skill")
    args = parser.parse_args()
    try:
        if sys.platform != "win32":
            raise RuntimeError("生成原生 SolidWorks 零件需要 Windows。")
        source = existing_dwg(args.dwg)
        output = args.output.resolve()
        if output.suffix.lower() != ".sldprt" or output.exists():
            raise ValueError("输出须为尚不存在的 .SLDPRT 文件。")
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        report = json.loads(args.inspection.read_text(encoding="utf-8-sig"))
        validate_plan(plan, report, source)
        root = dependency_root(args.solidworks_skill)
        output.parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(build(plan, output, root, args.solidworks_year, args.part_template),
                         ensure_ascii=False, allow_nan=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, ImportError) as error:
        parser.exit(1, f"SolidWorks 建模失败：{error}\n")


if __name__ == "__main__":
    main()
