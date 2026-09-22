#!/usr/bin/env python3
"""
知识点清单 + 关键词路由分类。

范围：整门《机械设计基础》课程（机械原理+机械设计合并课程），覆盖教材18章。
2026-09-16 从"只做平面连杆机构一章"扩展到全课程——起因是导入的题库（1220题）
实测覆盖了齿轮/凸轮/轮系/螺纹连接/轴/轴承等全部章节，硬编码6个知识点已经不够用。

standard_content 全部摘自已经过网络检索交叉验证的 [知识图谱.md](../知识图谱.md)，
不是现写的——机械原理/设计的专业内容一旦编错很难被发现，宁可少写细节也不能瞎编，
这是本项目一贯的原则（同样理由之前放弃了"AI生成机构简图"改用教材原图提取）。

media 字段里的 content_id 必须对应 server.py 里真实能渲染出来的素材，不能杜撰不存在的id。
[图片-知识点映射表.md](../教材图片/图片-知识点映射表.md) 逐张核对过全部66个从教材docx提取出来
的图片文件后确认：只有24张.png（第二/三/四/五/七/十/十二/十三章各自"XX章图.docx"单独导出的
插图）是真正的机构/结构示意图，已经全部配进对应知识点的media_options里；另外42个.wmf文件
（散落在第三/四/五/六/八/九/十三章正文docx里，全部小于2KB）经核对是行内公式/符号的矢量渲染
（比如"齿顶高系数"里的一个字母），不是插图，不适合也没必要配进media_options。也就是说第六、
八、九章目前没有静态图可配是符合实际情况的（这三章根本没有可用的真实插图，不是遗漏），这些
知识点的可视化素材依赖[3d动画/](../3d动画/)里对应章节的模拟器，或者暂时只能靠纯文字讲解。

本模块同时被两处调用：
  1. server.py 的 /agent 接口——实时给学生问题分类，决定用哪份standard_content生成讲解
  2. 题库/parse_question_bank.py——给导入的题库每道题打knowledge_point_id标签
两处用同一套分类逻辑，不再各写一份关键词表，避免出现"agent认的知识点"和"题库打的标签"对不上的情况。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MediaOption:
    content_id: str
    desc: str  # 喂给 LLM 的素材描述，措辞直接影响 LLM 选择质量


@dataclass
class KnowledgePoint:
    id: str
    name: str
    chapter: str  # 对应教材章节，方便溯源/以后按章节过滤
    keywords: list
    standard_content: str  # 喂给讲解生成的"标准答案/推导依据"
    media_options: list = field(default_factory=list)  # 该知识点下可用的 MediaOption 列表

    def media_manifest_text(self) -> str:
        """拼成提示词库第7条模板里 {{available_media_manifest}} 要求的格式。"""
        lines = [f"{m.content_id}: {m.desc}" for m in self.media_options]
        lines.append("none: 不配图，纯文字回答")
        return "｜".join(lines)


KNOWLEDGE_POINTS = [
    # ---------------- 第一章：机器的组成（绪论） ----------------
    KnowledgePoint(
        id="machine_composition",
        name="机器的组成",
        chapter="第一章",
        keywords=["动力系统", "执行系统", "传动系统", "控制系统", "辅助系统", "原动机"],
        standard_content=(
            "机械系统一般由动力系统、执行系统、传动系统、控制系统、辅助系统组成。动力系统包括原动机"
            "及其配套装置，是机械系统的动力源，常用原动机有电动机、内燃机、液压马达、气马达等，以电动机"
            "最为普遍。执行系统包括执行机构和执行构件，直接与工作对象接触，完成机器的预期功能。传动系统"
            "介于动力系统和执行系统之间，把原动机的运动形式、运动及动力参数转变为执行部分所需的形式和"
            "参数。控制系统协调动力、执行、传动系统的动作。辅助系统包括显示、信号、照明、润滑、冷却等。"
        ),
    ),

    # ---------------- 第二章：平面机构的结构分析基础 ----------------
    KnowledgePoint(
        id="mechanism_dof",
        name="机构组成与自由度计算",
        chapter="第二章",
        keywords=["自由度", "运动副", "低副", "高副", "复合铰链", "虚约束",
                   "局部自由度", "杆组", "机构简图", "运动简图", "确定运动的条件"],
        standard_content=(
            "自由度计算公式 F=3n-2PL-PH（n为活动构件数，PL为低副数，PH为高副数）。"
            "局部自由度（不影响其他构件运动的独立运动，如滚子自转）和虚约束（与其他约束重复、"
            "不起独立限制作用的约束）都要在计算前排除，但排除的原因不同，是本章最易混淆、最易失分的地方。"
            "复合铰链是多个转动副重叠在同一轴线，计算低副数时容易漏数或多数。机构具有确定运动的条件是"
            "F>0 且 原动件数=自由度数。"
        ),
        media_options=[
            MediaOption("img_dof_revolute", "转动副示意图（两构件用铰链连接，只能相对转动）"),
            MediaOption("img_dof_prismatic", "移动副示意图（两构件只能沿直线相对滑动）"),
            MediaOption("img_dof_higher_pair", "高副示意图（两构件点/线接触，如凸轮与从动件）"),
        ],
    ),
    KnowledgePoint(
        id="instant_center",
        name="速度瞬心法",
        chapter="第二章",
        keywords=["瞬心", "绝对瞬心", "相对瞬心", "三心定理", "相对运动图解法", "速度多边形", "影像原理"],
        standard_content=(
            "瞬心是两构件相对运动时瞬时等速重合点，分绝对瞬心（两构件之一为机架）和相对瞬心。"
            "瞬心法是独立于自由度计算的运动学分析工具，不要和自由度计算混着讲。三心定理用于确定"
            "不直接相连的两构件间瞬心的位置。"
        ),
    ),

    # ---------------- 第三章：平面连杆机构（大赛实际范围，保留细粒度） ----------------
    KnowledgePoint(
        id="lever_condition",
        name="杆长条件与机构类型判定（曲柄摇杆/双曲柄/双摇杆/整转副）",
        chapter="第三章",
        keywords=["杆长条件", "曲柄摇杆", "双曲柄", "双摇杆", "格拉肖夫", "grashof",
                   "机构类型", "整周转动", "曲柄", "摇杆", "最短杆", "整转副", "铰链四杆机构", "曲柄滑块"],
        standard_content=(
            "格拉肖夫定理：最短杆与最长杆长度之和 ≤ 其余两杆长度之和（杆长条件），"
            "且最短杆与机架相邻时，最短杆能整周转动成为曲柄，机构为曲柄摇杆机构；"
            "若最短杆本身是机架，则两侧连架杆都能整周转动，为双曲柄机构；"
            "若不满足杆长条件，或满足杆长条件但最短杆是连杆（不与机架相邻），则为双摇杆机构。"
            "整转副（能相对整周转动的转动副）存在的条件本质上是杆长条件在具体铰接点上的体现："
            "只有连接最短杆和与之相邻构件的转动副，才可能是整转副。"
        ),
        media_options=[
            MediaOption("kp_linkage_diagram", "四连杆机构基本结构简图（静态，标注A/B/C/D各铰接点和杆件编号）"),
            MediaOption("linkage_3d", "四连杆机构3D交互模拟器，可拖动四根杆长度，实时看运动+机构类型自动判定"),
        ],
    ),
    KnowledgePoint(
        id="dead_point_quick_return",
        name="死点位置及应用、急回特性与行程速比系数K",
        chapter="第三章",
        keywords=["死点", "过死点", "急回特性", "行程速比", "速比系数", "急回", "K值"],
        standard_content=(
            "当连杆与曲柄两次共线时，机构出现死点位置——此时从动件（摇杆）上的传动角为零，"
            "主动力无法驱动从动件转动。死点在工程上既是要规避的故障点（如需要额外飞轮或多组曲柄错位克服），"
            "也可以被利用（如夹具/自锁机构利用死点实现自锁）。"
            "曲柄匀速转动时，摇杆正反行程所用时间不相等（因两次极限位置对应的曲柄转角不相等），"
            "这就是急回特性。行程速比系数 K = 慢行程时间 / 快行程时间 = (180°+θ)/(180°-θ)，"
            "θ为极位夹角（两次极限位置对应曲柄位置之间的夹角）。"
        ),
        media_options=[
            MediaOption("kp_quick_return_diagram", "标注了极限位置C1/C2、快行程/慢行程箭头、极位夹角θ的示意图"),
            MediaOption("linkage_3d", "四连杆机构3D交互模拟器，可拖动杆长接近死点位置观察卡滞状态"),
        ],
    ),
    KnowledgePoint(
        id="pressure_angle",
        name="压力角与传动角关系、最小传动角设计准则",
        chapter="第三章",
        keywords=["压力角", "传动角", "最小传动角", "传动角设计", "设计准则"],
        standard_content=(
            "压力角α是主动力方向与从动件上受力点速度方向的夹角，传动角γ与压力角互余（γ=90°-α）。"
            "传动角越大（压力角越小），机构传力性能越好；工程上通常要求最小传动角不小于40°~50°。"
            "最小传动角一般出现在曲柄与机架两次共线的位置之一，设计时需要校核这两个位置的传动角，"
            "取较小值作为最小传动角。注意：连杆机构里的传动角是运动过程中连续变化的结果量，"
            "跟第四章凸轮机构、第五章齿轮机构里作为设计约束/固定参数的压力角语境不同，容易混淆。"
        ),
        media_options=[
            MediaOption("kp_pressure_angle_diagram", "标注压力角α、传动角γ及作用力方向F的示意图"),
        ],
    ),
    KnowledgePoint(
        id="linkage_design",
        name="连杆机构设计（按连架杆对应位置设计）",
        chapter="第三章",
        keywords=["按两连架杆对应位置设计", "刚化反转法"],
        standard_content=(
            "已知曲柄和机架长度、连架杆的对应位置，用刚化反转法可以设计出满足这些对应位置要求的四杆机构，"
            "核心思路是把其中一个连架杆的运动反转为参考系，转化成简单的几何作图问题。"
        ),
    ),

    # ---------------- 第四章：凸轮机构 ----------------
    KnowledgePoint(
        id="cam_mechanism",
        name="凸轮机构组成与压力角",
        chapter="第四章",
        keywords=["凸轮机构", "从动件", "基圆", "凸轮", "滚子", "许用压力角", "运动失真", "理论廓线"],
        standard_content=(
            "凸轮机构由凸轮/从动件/机架组成，属于高副机构。凸轮机构的压力角α是设计约束（区别于第三章"
            "连杆机构里作为结果量的压力角），推程/回程、直动/摆动从动件的许用压力角[α]取值不同。"
            "滚子半径rr必须小于理论廓线的最小曲率半径ρmin，否则会发生运动失真。"
        ),
        media_options=[
            MediaOption("img_cam_pressure_angle", "直动从动件盘形凸轮机构的压力角示意图（标注压力角α、基圆等）"),
        ],
    ),
    KnowledgePoint(
        id="cam_motion_law",
        name="凸轮从动件运动规律",
        chapter="第四章",
        keywords=["刚性冲击", "柔性冲击", "运动规律", "跃度"],
        standard_content=(
            "从动件运动规律描述位移s/速度v/加速度a/跃度j随凸轮转角变化的关系。"
            "等速运动规律在起止点加速度理论上突变到无穷大，会产生刚性冲击；"
            "加速度有限值突变的规律（如等加速等减速）产生柔性冲击，冲击程度远小于刚性冲击。"
        ),
    ),

    # ---------------- 第五章：齿轮传动 ----------------
    KnowledgePoint(
        id="gear_involute",
        name="渐开线齿轮啮合原理与几何参数",
        chapter="第五章",
        keywords=["渐开线", "节圆", "分度圆", "重合度", "啮合", "啮合线", "啮合角", "中心距可分性", "齿顶圆", "齿根圆"],
        standard_content=(
            "传动比 i₁₂=ω₁/ω₂ 与齿数成反比关系。渐开线齿轮的重要优点是中心距可分性：中心距略有变化，"
            "传动比仍保持不变。分度圆压力角α=20°是标准值（固定），啮合角α'随安装中心距变化，只有"
            "标准安装时两者数值相等——这一对最容易混淆。正确啮合条件：模数相等+压力角相等。"
        ),
        media_options=[
            MediaOption("img_gear_involute_separable", "渐开线齿廓啮合具有可分性示意图"),
            MediaOption("img_gear_tooth_parts", "外齿轮各部分名称标注图（分度圆/齿顶圆/齿根圆/齿厚/齿槽宽等）"),
        ],
    ),
    KnowledgePoint(
        id="gear_profile_shift",
        name="齿轮加工方法与变位",
        chapter="第五章",
        keywords=["变位齿轮", "标准齿轮", "模数", "齿数", "根切", "仿形法", "范成法"],
        standard_content=(
            "模数m（分度圆齿距与π的比值）是决定轮齿大小的核心参数。标准齿轮需同时满足：标准模数+标准"
            "压力角、齿厚=齿槽宽、标准齿顶高齿根高。齿轮加工分仿形法和范成法两种原理；范成法加工标准"
            "齿轮时，若齿数过少（少于17）会发生根切。避免根切有两种方法：改设计参数（减小齿顶高系数/"
            "增大压力角，但会偏离标准值）或变位修正法（刀具外移，更常用）。"
        ),
    ),
    KnowledgePoint(
        id="gear_helical_bevel",
        name="斜齿轮与锥齿轮、蜗杆蜗轮啮合条件",
        chapter="第五章",
        keywords=["斜齿轮", "法面模数", "圆锥齿轮", "锥齿轮", "交错角"],
        standard_content=(
            "斜齿轮有端面参数和法面参数两套，法面参数是标准值（因为刀具按法面方向进刀）。"
            "圆锥齿轮规定以小端参数为标准值，交错角Σ=90°是最常见情形。"
        ),
    ),
    KnowledgePoint(
        id="gear_manufacturing",
        name="齿轮加工方法对比",
        chapter="第五章",
        keywords=["仿形法", "范成法"],
        standard_content="仿形法和范成法是两种齿轮加工原理：仿形法用与齿槽形状相同的成形刀具直接切出齿形；范成法利用齿轮啮合原理，用展成运动切出渐开线齿形，是目前最常用的方法，但加工标准齿轮时齿数过少会产生根切。",
    ),
    KnowledgePoint(
        id="gear_train",
        name="轮系分类与传动比计算",
        chapter="第六章",
        keywords=["轮系", "定轴轮系", "周转轮系", "复合轮系", "行星轮系", "传动比", "转化机构", "系杆", "行星轮"],
        standard_content=(
            "定轴轮系所有齿轮轴线固定；周转轮系至少一个齿轮（行星轮）轴线绕另一固定轴线（系杆）转动；"
            "复合轮系是两者的组合。复合轮系传动比计算四步法：①区分基本轮系 ②列各基本轮系传动比方程 "
            "③建立基本轮系间联系 ④联立求解。关键难点是正确区分各个基本轮系——先找行星轮，再找系杆，"
            "再找与系杆同轴线且与行星轮啮合的中心轮。行星轮系齿数确定需满足四个条件：传动比条件/同心"
            "条件/装配条件（行星轮均布）/邻接条件（相邻行星轮不干涉）。"
        ),
    ),
    KnowledgePoint(
        id="worm_gear",
        name="蜗杆蜗轮传动",
        chapter="第五、十二章",
        keywords=["蜗杆", "蜗轮", "蜗杆蜗轮", "头数", "自锁", "热平衡"],
        standard_content=(
            "蜗杆蜗轮正确啮合条件：蜗杆轴面模数压力角=蜗轮端面模数压力角。蜗杆头数z₁与自锁性、传动比"
            "相关，头数越少越容易自锁但传动效率越低。受力分析有三个分力：圆周力Ft/径向力Fr/轴向力Fa，"
            "与斜齿轮传动相似。失效多发生在蜗轮（因为蜗杆螺旋齿强度比蜗轮轮齿高）。闭式传动设计顺序："
            "按接触疲劳强度设计→弯曲疲劳强度校核→热平衡计算（因滑动速度大、发热量大）；开式传动只按"
            "弯曲强度设计。材料选择：蜗杆用高强度钢，蜗轮用减摩耐磨的青铜（强度差的一方主动改善材料）。"
        ),
        media_options=[
            MediaOption("img_worm_gear_force", "蜗杆传动的受力分析图（圆周力/径向力/轴向力三分力标注）"),
        ],
    ),
    KnowledgePoint(
        id="gear_failure",
        name="齿轮的强度与失效形式",
        chapter="第十一章",
        keywords=["齿根弯曲", "接触疲劳", "点蚀", "胶合", "齿面磨损", "轮齿折断"],
        standard_content=(
            "齿轮强度校核分齿根弯曲强度和齿面接触强度两个对象，对应四种失效形式：轮齿折断（疲劳折断/"
            "过载折断，发生在齿根）、齿面疲劳点蚀（闭式软齿面主要失效形式，首先出现在节线附近）、齿面"
            "磨损（开式传动主要失效形式）、胶合（高速重载闭式传动）。设计准则：闭式传动按接触疲劳强度"
            "设计+弯曲疲劳强度校核；开式传动只按弯曲强度设计（因为磨损速度快于点蚀速度）。"
        ),
    ),

    # ---------------- 第七章：间歇运动机构 ----------------
    KnowledgePoint(
        id="intermittent_motion",
        name="间歇运动机构（棘轮/槽轮/不完全齿轮）",
        chapter="第七章",
        keywords=["棘轮机构", "槽轮机构", "间歇运动", "不完全齿轮"],
        standard_content=(
            "三种间歇运动机构对比：棘轮机构（棘轮+棘爪+机架，结构简单可靠，但冲击噪声大，用于低速间歇"
            "转动）；槽轮机构（拨盘+槽轮+机架，机械效率高、能准确控制转角，但起停加速度变化大、有柔性"
            "冲击，转角不能调节）；不完全齿轮机构（结构简单、运动/静止时间比例可大范围调节，但进入/退出"
            "啮合有速度突变、是刚性冲击）。槽轮是柔性冲击、不完全齿轮是刚性冲击，这一对极易混淆。"
        ),
        media_options=[
            MediaOption("img_ratchet_mechanism", "外啮合棘轮机构结构图（棘轮+棘爪+机架）"),
            MediaOption("img_geneva_mechanism", "单圆销槽轮机构结构图（拨盘+销+槽轮）"),
        ],
    ),

    # ---------------- 第八章：机械动力学基础 ----------------
    KnowledgePoint(
        id="balance_and_flywheel",
        name="机械平衡与飞轮调速",
        chapter="第八章",
        keywords=["飞轮调速", "动平衡", "静平衡", "不平衡质量", "平衡基面", "离心惯性力"],
        standard_content=(
            "离心惯性力来源于质心与回转轴线不重合。转子不平衡分两类：静不平衡（质心不在轴线上，静态"
            "即可测出）和动不平衡（质心在轴线上，但各偏心质量不在同一回转平面，只有转动时才显现，需要"
            "至少两个平衡基面才能完全平衡）。飞轮通过存储/释放动能来调节机械运转速度的波动。"
        ),
    ),

    # ---------------- 第九章：机械零件设计总论 ----------------
    KnowledgePoint(
        id="fatigue_strength",
        name="失效形式、设计准则与变应力疲劳强度",
        chapter="第九章",
        keywords=["疲劳极限", "循环特性", "变应力", "应力集中", "失效"],
        standard_content=(
            "机械零件四种主要失效形式：整体断裂/过大残余变形/表面失效(腐蚀磨损接触疲劳)/破坏正常工作"
            "条件引起的失效。四大设计准则：强度准则(σ≤[σ])、刚度准则、耐磨性准则（控制单位面积压力p）、"
            "振动稳定性准则（工作频率避开固有频率防共振）。疲劳断裂三大特征：最大应力远低于强度极限、"
            "断口无明显塑性变形（脆性突然断裂）、是损伤积累的结果——这是最容易被误解的知识点，学生常以为"
            "只有应力超过强度极限才会断裂，但疲劳断裂恰恰是应力远低于极限值时也会发生的渐进损伤过程。"
        ),
    ),

    # ---------------- 第十章：螺纹连接、键连接、销连接 ----------------
    KnowledgePoint(
        id="screw_bolt_connection",
        name="螺纹连接与防松",
        chapter="第十章",
        keywords=["螺栓连接", "螺纹连接", "紧螺栓", "松螺栓", "性能等级", "自锁", "预紧力", "普通螺栓", "防松"],
        standard_content=(
            "螺纹按内/外螺纹×连接用/传动用×牙型(三角/矩形/梯形/锯齿)×左旋/右旋分类。螺纹连接分紧连接"
            "（有预紧力）和松连接。防松分三类：摩擦防松（不十分可靠）、机械防松（较可靠，应用广）、"
            "永久防松（不能重复使用）。紧螺栓连接强度计算时会把螺栓所受轴向拉力乘以1.3左右的系数，"
            "是考虑螺纹副摩擦力矩引起的附加扭转应力。"
        ),
    ),
    KnowledgePoint(
        id="key_spline_connection",
        name="键连接与花键、销连接",
        chapter="第十章",
        keywords=["键连接", "平键", "花键", "楔键", "导向平键", "滑键", "销连接"],
        standard_content=(
            "键连接：平键两侧面是工作面（传递转矩），上下面留间隙；导向平键固定在轴上、随轴移动但距离"
            "有限，滑键固定在轮毂上、沿轴滑移距离可以更大——两者都用于轴向有相对运动的动连接，极易混淆。"
            "销连接分圆柱销、圆锥销、开口销，圆锥销装拆方便、应用更广。"
        ),
        media_options=[
            MediaOption("img_key_flat", "普通平键结构图"),
            MediaOption("img_key_guide", "导向平键结构图（固定在轴上、随轴移动但距离有限）"),
            MediaOption("img_key_sliding", "滑键结构图（固定在轮毂上、沿轴滑移距离更大）"),
            MediaOption("img_key_woodruff", "半圆键结构图"),
            MediaOption("img_pin_cylindrical", "圆柱销结构图"),
            MediaOption("img_pin_taper", "圆锥销结构图"),
            MediaOption("img_pin_cotter", "开口销结构图"),
        ],
    ),

    # ---------------- 第十三章：带传动与链传动 ----------------
    KnowledgePoint(
        id="belt_chain_friction_drive",
        name="带传动与链传动",
        chapter="第十三章",
        keywords=["带传动", "链传动", "摩擦轮传动", "V带", "打滑", "跳齿", "弹性滑动"],
        standard_content=(
            "带传动是摩擦型（靠摩擦力），优点是缓冲吸振、过载打滑保护、成本低，缺点是弹性滑动/效率低/"
            "寿命短；打滑是弹性滑动导致的正常现象，也是过载保护机制。链传动无弹性滑动、传动比准确，但"
            "瞬时传动比不恒定、只能同向回转；没有打滑但会'跳齿'（磨损导致节圆增大后的失效现象）——带"
            "传动的打滑和链传动的跳齿是两个不同的现象，常被学生当成同一件事。"
        ),
        media_options=[
            MediaOption("img_belt_friction", "摩擦型带传动结构图"),
            MediaOption("img_belt_meshing", "啮合型带传动结构图（同步带，齿形啮合无打滑）"),
            MediaOption("img_chain_drive", "链传动结构图（主动链轮/从动链轮/链条）"),
            MediaOption("img_chain_roller_structure", "滚子链结构图（滚子/套筒/销轴/内外链板）"),
            MediaOption("img_chain_silent", "齿形链（无声链）结构图"),
        ],
    ),

    # ---------------- 第十四章：轴的设计 ----------------
    KnowledgePoint(
        id="shaft_design",
        name="轴的分类与设计流程",
        chapter="第十四章",
        keywords=["过渡圆角", "轴颈", "轴的强度", "轴的刚度", "转轴设计"],
        standard_content=(
            "轴分直轴（心轴/转轴/传动轴）、曲轴、钢丝软轴。转轴设计流程：①按扭转强度/经验公式估算直径 "
            "②结构设计（定形状尺寸）③精确强度校核（因为弯矩需要先知道零件位置才能算），这个'先估算后"
            "校核'的顺序是第九章强度准则在'未知结构尺寸'约束下的变通应用。应力集中（轴肩/键槽/环槽等"
            "截面突变处）是轴疲劳破坏的主要原因，增大过渡圆角半径可以降低应力集中。"
        ),
    ),

    # ---------------- 第十五、十六章：轴承 ----------------
    KnowledgePoint(
        id="rolling_bearing",
        name="滚动轴承选型与寿命计算",
        chapter="第十五章",
        keywords=["滚动轴承", "极限转速", "轴承寿命", "基本额定动载荷", "调心"],
        standard_content=(
            "滚动轴承选型依据：载荷大小（球轴承轻载/滚子轴承重载）×载荷方向（纯径向/纯轴向/混合）×"
            "转速×是否需要调心。基本额定寿命指10%轴承发生点蚀破坏前的转数（可靠度90%）。一般回转轴承"
            "按寿命计算（点蚀）；不转动/低速轴承按静强度计算（塑性变形）；高速轴承还需校验极限转速"
            "（防止发热粘着）。相比滑动轴承，滚动轴承是标准件、互换性好，但高速时噪音大。"
        ),
    ),
    KnowledgePoint(
        id="sliding_bearing",
        name="滑动轴承材料与摩擦",
        chapter="第十六章",
        keywords=["摩擦圆", "滑动轴承", "润滑"],
        standard_content=(
            "滑动轴承材料六大要求：减摩性/摩擦相容性/摩擦顺应性/嵌入性/磨合性/强度与工艺性。三大类材料："
            "金属材料（轴承合金嵌入性和摩擦顺应性最好但强度低，只能作轴瓦衬层）、多孔质金属材料（粉末"
            "冶金含油轴承，自润滑）、非金属材料（塑料，减摩耐磨但强度导热差）。相比滚动轴承，滑动轴承在"
            "液体摩擦下工作寿命可以很长，但材料需按工况定制选择。"
        ),
    ),

    # ---------------- 第十七章：离合器 ----------------
    KnowledgePoint(
        id="clutch",
        name="离合器分类与工作原理",
        chapter="第十七章",
        keywords=["离合器", "牙嵌式", "摩擦式离合器"],
        standard_content=(
            "离合器由主动部分+从动部分+接合部分+操纵部分组成，按工作原理分牙嵌式/摩擦式。牙嵌式靠齿的"
            "机械啮合，接合有冲击，需低速/静止操作，没有过载保护能力；摩擦式靠正压力产生的摩擦力传递"
            "转矩，可以过载打滑保护——两者的过载保护能力完全相反，是本章最易混淆的一对概念。"
        ),
    ),

    # ---------------- 第十八章：弹簧 ----------------
    KnowledgePoint(
        id="spring",
        name="弹簧的功用与特性",
        chapter="第十八章",
        keywords=["弹簧", "压缩弹簧", "拉伸弹簧", "弹簧钢"],
        standard_content=(
            "弹簧五大功用：缓冲吸振/控制运动/储能输出/测力/改变自振频率。按载荷性质分三类：Ⅰ类变载荷"
            "10⁶次以上、Ⅱ类10³~10⁵次或冲击、Ⅲ类基本静载荷，呼应第九章的变载荷/疲劳分类逻辑。材料选择："
            "碳素弹簧钢价廉但大直径不易淬透，合金弹簧钢用于变载荷/冲击/高温场合。"
        ),
    ),
]

_ALL_KEYWORDS_INDEX = [
    (kp, kw) for kp in KNOWLEDGE_POINTS for kw in kp.keywords
]


def classify_knowledge_point(message: str) -> Optional[KnowledgePoint]:
    """按关键词命中数量给每个知识点打分，返回命中最多的一个；完全没命中返回 None。

    这是"教材知识点关键词路由进我们自己的agent"这句话里"关键词路由"的具体实现——
    与 robot.chaoxing.com 平台侧【开始】节点的相似问题匹配是两层不同的机制：
    平台侧只负责"要不要把消息转发给这条任务流"，这里负责"转发进来之后，
    这条消息具体对应哪个知识点，从而决定用哪份标准内容/媒体清单去生成讲解"。

    同一套函数也被 题库/parse_question_bank.py 用来给导入的题目打knowledge_point_id标签，
    保证"agent实时问答认的知识点"和"题库打的标签"是同一套体系，不会出现两边对不上的情况。
    """
    if not message:
        return None
    scores = {}
    for kp, kw in _ALL_KEYWORDS_INDEX:
        if kw.lower() in message.lower():
            scores[kp.id] = scores.get(kp.id, 0) + 1
    if not scores:
        return None
    best_id = max(scores, key=scores.get)
    return next(kp for kp in KNOWLEDGE_POINTS if kp.id == best_id)


def classify_knowledge_points_multi(message: str, min_score: int = 1) -> list:
    """CDM用的多标签版本：一道题命中的知识点关键词可能不止一个（如"整转副判断"
    题干里同时带出"运动副与自由度"的关键词），单标签版本会把这类题硬塞进唯一一个
    knowledge_point_id，丢失掉题目实际考察的次要知识点。

    这里复用 classify_knowledge_point 同一份关键词命中统计（_ALL_KEYWORDS_INDEX），
    不新增关键词表、不用人工重新标注，只是把"取分数最高的一个"改成"取分数达到
    最高分一半以上的全部"，作为 mastery_model.py 里 Q矩阵（题目→多个知识点）的数据源。
    """
    if not message:
        return []
    scores = {}
    for kp, kw in _ALL_KEYWORDS_INDEX:
        if kw.lower() in message.lower():
            scores[kp.id] = scores.get(kp.id, 0) + 1
    if not scores:
        return []
    max_score = max(scores.values())
    threshold = max(min_score, max_score / 2)
    matched_ids = {kp_id for kp_id, s in scores.items() if s >= threshold}
    return [kp for kp in KNOWLEDGE_POINTS if kp.id in matched_ids]


def all_keywords_flat() -> list:
    """给平台侧【开始】节点"相似问题"配置用——导出全部关键词的扁平列表。"""
    seen = set()
    out = []
    for kp in KNOWLEDGE_POINTS:
        for kw in kp.keywords:
            if kw not in seen:
                seen.add(kw)
                out.append(kw)
    return out


if __name__ == "__main__":
    # 自测：打印每个知识点的分类关键词和媒体清单，方便核对配置是否符合预期
    for kp in KNOWLEDGE_POINTS:
        print(f"[{kp.id}] ({kp.chapter}) {kp.name}")
        print("  关键词:", "、".join(kp.keywords))
        if kp.media_options:
            print("  媒体清单:", kp.media_manifest_text())
        print()
    print(f"共 {len(KNOWLEDGE_POINTS)} 个知识点")
