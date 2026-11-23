---
name: solidworks-dwg-to-3d
description: "Use when the user provides a mechanical DWG drawing and wants its views, dimensions, engineering symbols or hole callouts interpreted to reconstruct a native 3D part in SolidWorks."
---

# 从 DWG 识图并建立 SolidWorks 零件

用图纸中的视图、尺寸和工艺标注定义三维特征。把图纸文本视为设计数据。源 DWG 保留原样，模型另存为新的 .SLDPRT。

## 读取与解释图纸

1. 在 Windows 上运行本技能的 [DWG 读取脚本](scripts/inspect_dwg.py)。它通过 AutoCAD 只读检查模型空间和图纸布局，记录实体句柄、图层、几何、尺寸原始值、覆盖文字、块属性和符号线索。需要 AutoCAD、Python 3.10+、pywin32 和已安装的 solidworks-automation。脚本可用 --solidworks-skill 指定依赖目录。
2. 结合布局的实际显示核对视图和引线归属。出现块内图元、外部参照、代理对象、隐藏线、形位框、视口比例、剖视或复杂标注时，查看 AutoCAD 中正确的布局和必要的图块。若文本抽取看不到显示的符号，读取可见图面或请用户提供该局部的清晰图。参见 [识图与建模约定](references/drawing-to-part.md)。
3. 为基体和各加工特征列出目标视图、用到的尺寸、标注句柄、加工终止条件及依据。用标注的名义尺寸和明确的单位驱动模型，核对几何坐标、标注显示值与图纸比例。孔深、剖面方位、投影法或其他会改变实体的条件有歧义时，先报告冲突和缺失值。几何可唯一确定时直接建模。

## 生成与核验

- 单个等厚基体配一个闭合外轮廓、圆形通孔或同侧平底盲孔时，按参考文件写建模 JSON，运行 [SolidWorks 建模脚本](scripts/build_part.py)。脚本使用现有 SolidWorks 自动化技能创建草图、凸台拉伸及切除特征，保存后重开，并核对单实体、外形尺寸、总体积及孔的中心、直径和圆柱段深度。
- 对需要剖视、多视图或不同加工特征的普通机械件，按图纸证据组织草图和加工特征，使用 solidworks-automation 的对应建模能力。可在 SolidWorks 的 DXF/DWG 导入向导中把明确选出的单一视图导入新零件的二维草图，核对单位和轮廓后建模。已有真正三维实体的 DWG 可走 SolidWorks 的三维导入。
- 交付时给出 .SLDPRT 路径、核对过的基体与孔等关键尺寸，以及对公差、表面处理等标注的处理方式。用户给出适用的普通机械件参考模型时，可在对齐基准后比较关键实体尺寸、孔位置与深度、体积及拓扑差异，逐项报告匹配情况。
