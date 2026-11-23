# DWG 工程图判读及建模参数

## 符号怎样影响模型

| 看到的证据 | 建模时怎么用 |
|---|---|
| ⌀、Ø、AutoCAD 的 %%c | 读取直径。结合引线端点、剖视及说明，确认它属于外圆、内孔还是别的圆形特征。圆及中心线单独存在时，孔的终止条件仍可能有歧义。 |
| THRU、通孔、贯穿 | 明确关联到目标孔后选择贯穿。核对视图方向、进入面、孔轴、数量和相对基准的位置。 |
| BLIND、盲孔、深度符号 ↧ | 核对进入面、直孔段深度和底部形状。钻尖的总深与圆柱段深度可能不同；仅在图纸或用户明确平底时使用脚本的 blind_flat。 |
| ⌵、CSK、沉头 | 检查锥形沉头的大端直径、夹角与所在侧，同时确认基孔。 |
| ⌴、C'BORE、平底沉孔、锪平 | 检查扩径、深度和加工侧，同时确认基孔。按引线和剖面区分沉孔、锪平面与锥形沉头。 |
| M、螺纹规格和深度 | 核对内外螺纹、螺距、制式、有效螺纹深度和底孔。按交付要求选螺纹标注或实体特征，说明建模表达方式。 |
| R、倒角尺寸、角度 | R 标注指向轮廓中的圆弧或圆角。倒角按指向和书写约定核对长度、角度、边和方向，区分数量前缀。 |
| 虚线、中心线、剖切线和剖面线 | 虚线按图例解释为隐藏轮廓等；中心线用于轴线和对称。用剖切标记、箭头和剖视代号确定剖面位置与观察方向。仅把零件边界作为草图轮廓。 |
| 公差、基准、形位公差框、表面粗糙度 | 按名义尺寸建立实体。将这些信息记录为图纸要求；用户要求 PMI 或图纸标注时才转换成相应的标注，并核对关联对象。 |

先从标题栏确认单位、零件、图纸版本和投影法，再匹配主视、俯视、侧视及剖视或局部视图。使用布局中的视口比例和基准对齐，避免把排版相邻的两个视图当成一个轮廓。INSUNITS 是插入单位提示。核对线性比例因子、存在的尺寸覆盖及实际图面显示，尤其是英寸、无单位、断裂视图和放大详图。几何比例与标注冲突时先定位冲突。脚本给出的 symbol_hints 是关键词线索，原文、引线关系、面向和上下文决定其含义。

块属性可随读取报告取得。动态块、外部参照、仅图形构成的符号、形位框及复杂引线需要在图面检查。读取脚本中的实体列表也保留未抽取详细属性的对象。多个视图的深度或内部几何无法唯一确定时，可以完成已确定部分的分析并标出需要的剖视或尺寸。

## 脚本调用

在下列 PowerShell 示例中，$skill 是本技能目录，$dwg 为 DWG 的完整路径。两个 JSON 可放到任务工作目录。

~~~powershell
python "$skill/scripts/inspect_dwg.py" "$dwg" --output "inspection.json"
python "$skill/scripts/build_part.py" "$dwg" --inspection "inspection.json" --plan "plan.json" --output "part.SLDPRT" --solidworks-year 2024
~~~

用与实际安装对应的 SolidWorks 年份。模板找不到时可提供 --part-template。已有 SolidWorks 实例的 COM 连接未就绪时，先检查窗口中的对话框。在已确认目标版本且只有一个对应实例的情况下，可按固有连接工具的说明为当前命令启用 SW_ATTACH_EXISTING_DISPATCH=1，使用带进程标识与版本复核的回退。已有用户文档由各会话保留。

## 单基体参数示例

下例是一块普通安装板。替换 SHA-256 和句柄为实际读取报告中的值，在 basis 中记录图纸证据与缩放或坐标变换。XY 为选定基体视图在草图中的坐标，全部尺寸先换成 mm。各孔的进入面都对应基体草图平面。size_mm 是图纸中基体轮廓的 X、Y 方向外形尺寸。

~~~json
{
  "source_sha256": "填入读取报告的 source_sha256",
  "base": {
    "profile": {
      "start_mm": [0, 0],
      "edges": [
        {"end_mm": [60, 0]},
        {"end_mm": [60, 40]},
        {"end_mm": [0, 40]},
        {"end_mm": [0, 0]}
      ]
    },
    "size_mm": [60, 40],
    "thickness_mm": 12,
    "evidence_handles": ["82", "88", "C5"],
    "basis": "主视闭合外轮廓与宽度尺寸一致，厚度按图注 12 mm。"
  },
  "holes": [
    {
      "kind": "through",
      "center_mm": [15, 20],
      "diameter_mm": 6,
      "evidence_handles": ["83", "86"],
      "basis": "圆心取自主视图的孔轮廓，图注明确写明 ⌀6 THRU。"
    }
  ]
}
~~~

- 直线边用 end_mm。圆弧边另外提供弧上的中间点 via_mm，最后一段回到 start_mm。整圆外轮廓用 {"center_mm": [x, y], "diameter_mm": d}。
- 按圆孔逐个填入 holes；没有孔时用 []。平底盲孔用 kind 为 blind_flat，再填写 depth_mm。通孔用 through。
- 段的支撑曲线、相交、闭合性和实体生成由 SolidWorks 检查。验收应包括与标注核对孔的直径、位置及进入面。脚本的体积核对能发现未切到、未贯穿或重叠等问题。

SolidWorks 原厂操作参考可参阅 [DXF/DWG 导入选项](https://help.solidworks.com/2024/English/SolidWorks/slddxf/HIDD_IMPORT_PARTPAGE1.htm) 和 [二维转三维流程](https://help.solidworks.com/2024/English/SolidWorks/sldworks/c_2D_to_3D_Conversion_Overview.htm)。DWG 的只读打开方式见 [AutoCAD ActiveX 文档](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-ActiveX-Reference/files/GUID-9ED7A548-7978-4BFD-8462-E2FA747E8880.htm)。
