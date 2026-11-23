# SolidWorks DWG to 3D

在 Windows 上用 Codex 辅助读机械 DWG 图纸，并在 SolidWorks 中重建原生零件（`.SLDPRT`）。技能用 AutoCAD 读取模型空间和布局，结合实际图面确认尺寸、视图和引线归属，再按名义尺寸建模并重开复测。源 DWG 以只读方式读取。

## 适用范围

| 图纸类型 | 建模方式 |
| --- | --- |
| 单一等厚基体，带圆形通孔或从同一面进入的平底盲孔 | `build_part.py` 根据经核对的 JSON 生成草图、拉伸凸台和切除。外轮廓可用圆，或由直线和圆弧组成的闭合轮廓。 |
| 阶梯轴、环槽、复杂剖视、螺纹或多方向加工特征 | Codex 根据图纸证据调用对应的 SolidWorks 建模功能，按特征核验结果。 |
| 已包含三维实体的 DWG | 先确认实体和单位，再使用 SolidWorks 三维导入流程。 |

当单位、视图关系、孔深或加工面存在冲突时，应从剖视、细节图或补充尺寸确定几何。公差、粗糙度、形位公差和表面处理按图纸要求记录。需要将这些要求加入三维标注时，请在建模请求中说明。

## 环境要求

- Windows 10 或 11，Python 3.10+。随仓库发布的脚本已用 AutoCAD 2026 和 SolidWorks 2024 SP3.1 完成合成安装板的读取、建模与重开测试。
- 本机安装并激活 AutoCAD 和 SolidWorks，且对应的 COM 接口可用。读取 DWG 时需启动 AutoCAD。建模时需有可用的 SolidWorks 零件模板。
- 安装 [SolidWorks Automation Skill](https://github.com/wzyn20051216/solidworks-automation-skill)。它提供 AutoCAD 会话、SolidWorks 建模和测量方法。该依赖单独安装，随其自身版本更新。
- 两个脚本使用同一个 Python 环境。安装 Windows COM 依赖，并运行自检。

```powershell
$cadAutomation = 'C:/CAD/solidworks-automation-skill'  # 替换为本机依赖目录
python -m pip install "pywin32>=305" "comtypes>=1.2.0"
python "$cadAutomation/scripts/sw_preflight.py"
python "$cadAutomation/subskills/autocad-automation/scripts/acad_preflight.py"
```

`$cadAutomation` 指向依赖的根目录，目录内应能找到 `scripts/sw_session.py`。

## 在 Codex 中使用

将本仓库克隆到用户技能目录。示例使用当前 Codex 文档中的 `.agents/skills`。

```powershell
$skillRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.agents/skills'
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
git clone https://github.com/baimo0001/solidworks-dwg-to-3d.git (Join-Path $skillRoot 'solidworks-dwg-to-3d')
```

在 [Codex 技能选择器](https://learn.chatgpt.com/docs/build-skills#how-chatgpt-and-codex-use-skills)中调用 `$solidworks-dwg-to-3d` 并附上 DWG。例如：

> 用 $solidworks-dwg-to-3d 把附上的 DWG 做成可编辑的 SolidWorks 零件，另存为 SLDPRT。请核对剖视、主要外形尺寸和孔的终止条件。

若依赖安装在其他目录，可以在请求中附上依赖根目录，或在脚本调用中传入 `--solidworks-skill`。

## 从 PowerShell 运行

从本仓库根目录执行。下面将依赖目录和 DWG 路径写成示例，请按本机实际位置替换。命令中的 `2024` 为示例使用的 SolidWorks 年份。

```powershell
$cadAutomation = 'C:/CAD/solidworks-automation-skill'
$drawing = 'C:/CAD/input/plate.dwg'
$inspection = 'C:/CAD/output/inspection.json'
$plan = 'C:/CAD/output/plan.json'
$model = 'C:/CAD/output/plate.SLDPRT'
New-Item -ItemType Directory -Path 'C:/CAD/output' -Force | Out-Null

python scripts/inspect_dwg.py $drawing --output $inspection --solidworks-skill $cadAutomation
```

`inspection.json` 记录源文件的 SHA-256、插入单位、图层、布局、实体句柄和可读取的标注属性。结合 AutoCAD 显示核对视图、尺寸比例和引线，再按 [建模 JSON 示例](references/drawing-to-part.md#单基体参数示例)填写 `plan.json`。每项特征都需要对应的实体句柄和建模依据。

```powershell
python scripts/build_part.py $drawing --inspection $inspection --plan $plan --output $model --solidworks-year 2024 --solidworks-skill $cadAutomation
```

读取报告和模型应使用新文件名。生成脚本会比较源 DWG 的 SHA-256 与报告和方案记录的源文件哈希，保存后重开模型，并核对单实体、外形尺寸、体积和孔的中心、直径及圆柱段深度。复杂零件按相应建模流程逐项核验。

## 常见问题

| 遇到的问题 | 检查方法 |
| --- | --- |
| 找不到 AutoCAD 或 SolidWorks | 先手动启动对应 CAD，处理首次启动或许可证对话框，再运行自检。 |
| 找不到 `solidworks-automation` | 用 `--solidworks-skill` 指定包含 `scripts/sw_session.py` 的根目录。 |
| 刚打开 DWG 时出现 `<unknown>.FullName` | 等 AutoCAD 完成图纸加载后重试。也可以先在 AutoCAD 中只读打开目标 DWG，再运行读取脚本。 |
| 找不到零件模板 | 将本机可用的 `.prtdot` 路径传给 `--part-template`。 |
| 报告里缺尺寸值或符号 | 回到 AutoCAD 查看原视图和标注，检查尺寸覆盖、线性比例、块和外部参照。 |
| SHA-256 不一致 | 对当前 DWG 重新生成读取报告，并让建模方案引用这份报告。 |

## 仓库结构

- [`SKILL.md`](SKILL.md) 供 Codex 识别和执行的识图建模流程。
- [`scripts/inspect_dwg.py`](scripts/inspect_dwg.py) 通过 AutoCAD 只读提取 DWG 证据。
- [`scripts/build_part.py`](scripts/build_part.py) 根据经核对的参数构建等厚零件并重开验证。
- [`references/drawing-to-part.md`](references/drawing-to-part.md) 记录工程图符号、投影、比例和建模计划格式。

## 许可证

仓库代码和文档采用 [MIT 许可证](LICENSE)。运行所调用的独立 CAD 软件和上游依赖适用各自的许可条款。
