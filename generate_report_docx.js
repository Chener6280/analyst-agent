// 生成宏观策略分析师周报 Word 文档
// 基于 docx skill R1 配方 + IG-1 (Ink Gold) 调色板
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, PageNumber, NumberFormat, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType, PageOrientation, SectionType,
  TableLayoutType, PageBreak, LevelFormat,
} = require("docx");
const fs = require("fs");

// ─────────── 调色板 IG-1 (Ink Gold) ───────────
const P = {
  bg: "1A1A1A", primary: "FFFFFF", accent: "C9A84C",
  titleColor: "FFFFFF", subtitleColor: "B0B8C0", metaColor: "90989F", footerColor: "687078",
  headerBg: "C9A84C", headerText: "1A1A1A", accentLine: "C9A84C",
  innerLine: "DDD5C0", surface: "F5F2E8",
};
const c = (hex) => hex.replace("#", "");
const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };

// ─────────── 工具函数 ───────────
function safeText(value, placeholder) {
  if (value === undefined || value === null || value === "" || String(value) === "NaN" || String(value) === "undefined") {
    return placeholder || "—";
  }
  return String(value);
}

// ─────────── 封面：R1 Pure Paragraph ───────────
function buildCover() {
  const padL = 1200, padR = 800;
  const titleLines = ["分析师观点周报"];
  const titleSize = 80; // 40pt
  const accentLeft = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];

  // 顶部留白
  children.push(new Paragraph({ spacing: { before: 3600 } }));

  // 英文标签 + 底部细线
  children.push(new Paragraph({
    indent: { left: padL, right: padR }, spacing: { after: 500 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
    children: [new TextRun({ text: "W E E K L Y   A N A L Y S T   V I E W S",
      size: 18, color: P.accent, font: { ascii: "Calibri", eastAsia: "SimHei" }, characterSpacing: 40 })],
  }));

  // 主标题
  for (let i = 0; i < titleLines.length; i++) {
    children.push(new Paragraph({
      indent: { left: padL },
      spacing: { after: 300, line: Math.ceil(40 * 23), lineRule: "atLeast" },
      children: [new TextRun({ text: titleLines[i], size: titleSize, bold: true,
        color: P.titleColor, font: { eastAsia: "SimHei", ascii: "Arial" } })],
    }));
  }

  // 副标题
  children.push(new Paragraph({
    indent: { left: padL }, spacing: { after: 800 },
    children: [new TextRun({ text: "2026 年第 24 周 · 全量扫描汇总",
      size: 26, color: P.subtitleColor, font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
  }));

  // 元信息（左侧 accent 边线）
  const metaLines = [
    "扫描批次：2026-W24-full-v2",
    "覆盖团队：38 家 · 覆盖率 89%",
    "数据来源：38 家券商官方公众号",
    "生成日期：2026 年 6 月 15 日",
  ];
  for (const line of metaLines) {
    children.push(new Paragraph({
      indent: { left: padL + 200 }, spacing: { after: 80 },
      border: { left: accentLeft },
      children: [new TextRun({ text: line, size: 24, color: P.metaColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" } })],
    }));
  }

  // 底部留白
  children.push(new Paragraph({ spacing: { before: 2400 } }));

  // 页脚
  children.push(new Paragraph({
    indent: { left: padL, right: padR },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: "macro-strategy-analyst", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
      new TextRun({ text: "                                        " }),
      new TextRun({ text: "Production Ready", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
    ],
  }));

  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg }, borders: noBorders,
        children,
      })],
    })],
  })];
}

// ─────────── 段落构建器 ───────────
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160, line: 312 },
    children: [new TextRun({ text, bold: true, size: 32, color: "0F2027",
      font: { ascii: "Calibri", eastAsia: "SimHei" } })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 120, line: 312 },
    children: [new TextRun({ text, bold: true, size: 28, color: "0F2027",
      font: { ascii: "Calibri", eastAsia: "SimHei" } })],
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 100, line: 312 },
    children: [new TextRun({ text, bold: true, size: 24, color: "203A43",
      font: { ascii: "Calibri", eastAsia: "SimHei" } })],
  });
}
function body(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: opts.indent === false ? 0 : 480 },
    spacing: { line: 312, after: 80 },
    children: [new TextRun({ text, size: 24, color: "000000",
      font: { ascii: "Times New Roman", eastAsia: "SimSun" } })],
  });
}
function bodyRuns(runs, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: { firstLine: opts.indent === false ? 0 : 480 },
    spacing: { line: 312, after: 80 },
    children: runs,
  });
}
function bullet(text) {
  return new Paragraph({
    bullet: { level: 0 },
    spacing: { line: 312, after: 60 },
    children: [new TextRun({ text, size: 24, color: "000000",
      font: { ascii: "Times New Roman", eastAsia: "SimSun" } })],
  });
}
function tableCaption(text) {
  return new Paragraph({
    keepNext: true,
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 60 },
    children: [new TextRun({ text, bold: true, size: 21, color: "0F2027",
      font: { ascii: "Calibri", eastAsia: "SimHei" } })],
  });
}

// ─────────── 表格构建器（Horizontal-Only） ───────────
function buildTable(headers, rows, colWidths) {
  const widths = colWidths || headers.map(() => Math.floor(100 / headers.length));

  const headerRow = new TableRow({
    tableHeader: true, cantSplit: true,
    children: headers.map((text, i) => new TableCell({
      children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text, bold: true, size: 21, color: P.headerText,
          font: { ascii: "Calibri", eastAsia: "SimHei" } })],
      })],
      shading: { type: ShadingType.CLEAR, fill: P.headerBg },
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
      width: { size: widths[i], type: WidthType.PERCENTAGE },
    })),
  });

  const dataRows = rows.map((row, idx) => new TableRow({
    cantSplit: true,
    children: row.map((cell, i) => new TableCell({
      children: [new Paragraph({
        alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.LEFT,
        children: [new TextRun({ text: safeText(cell), size: 20, color: "000000",
          font: { ascii: "Times New Roman", eastAsia: "SimSun" } })],
      })],
      shading: idx % 2 === 0
        ? { type: ShadingType.CLEAR, fill: P.surface }
        : { type: ShadingType.CLEAR, fill: "FFFFFF" },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      width: { size: widths[i], type: WidthType.PERCENTAGE },
    })),
  }));

  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 6, color: P.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accentLine },
      left: NB, right: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: P.innerLine },
      insideVertical: NB,
    },
    rows: [headerRow, ...dataRows],
  });
}

// ─────────── 正文章节 ───────────
function buildBody() {
  const children = [];

  // ===== 摘要 =====
  children.push(h1("一、本周结论摘要"));
  children.push(body("本周（2026 年第 24 周）对 38 家券商宏观与策略团队进行了全量观点扫描，共采集官方公众号文章 38 篇，其中 33 篇获取全文，全文率 87%，覆盖率达 89%。整体数据质量满足 production profile（生产级）来源质量阈值，可用于投资决策参考。"));
  children.push(body("从宏观与策略两个维度的共识与分歧看，本周市场呈现以下特征：货币政策方面，16 家团队形成共识，一致认为将边际宽松；财政政策方面，9 家表态团队一致指向边际扩张；海外环境方面，5 家团队一致认为将边际恶化。而增长、通胀、流动性三个维度则分歧较高，团队观点出现明显分化。"));

  children.push(h2("1.1 五大维度速览"));
  children.push(tableCaption("表 1：本周宏观与策略核心维度一览"));
  children.push(buildTable(
    ["维度", "样本数", "众数", "中位数", "分歧度", "摘要"],
    [
      ["增长（宏观）", "16/16", "边际改善", "0.5", "2", "分歧较高，众数为边际改善"],
      ["通胀（宏观）", "12/16", "边际上行", "1.0", "2", "分歧较高，众数为边际上行"],
      ["货币政策", "16/16", "边际宽松", "1.0", "0", "共识偏向边际宽松"],
      ["财政政策", "9/16", "边际扩张", "1", "0", "共识偏向边际扩张"],
      ["海外环境", "5/16", "边际恶化", "-1", "0", "共识偏向边际恶化"],
      ["市场整体观点", "7/17", "中性", "0", "1", "共识偏向中性"],
      ["流动性（策略）", "11/17", "边际改善", "0", "2", "分歧较高，众数为边际改善"],
    ],
    [18, 10, 12, 10, 8, 32]
  ));

  children.push(h2("1.2 数据质量提示"));
  children.push(bullet("本周全文率 87%，官方来源占比 89%，达到 production profile 标准。"));
  children.push(bullet("历史趋势模块尚未启用：当前为单周数据，需累计至少 4 个真实周度扫描后才会激活时序分析。"));
  children.push(bullet("零信号文档：无（所有抽取样本均含有效信号）。"));
  children.push(bullet("非官方来源样本：4 个（中信证券:strategy、中国银河证券:macro、中国银河证券:strategy、国联民生证券:strategy），建议补采官方渠道全文。"));

  // ===== 宏观观点 =====
  children.push(h1("二、宏观观点详解"));

  children.push(h2("2.1 增长：分歧较高，众数为边际改善"));
  children.push(body("16 家宏观团队全部表态，分歧度为 2，是本周分歧最大的宏观维度。众数指向边际改善，中位数 0.5。多数团队认为房地产改善的持续性、政策落地力度以及外部不确定性是关键变量。东吴证券、中信建投等明确表达边际改善判断；中泰证券则提示 M2 增速虽回落但规模拐点未现。"));

  children.push(h2("2.2 通胀：分歧较高，众数为边际上行"));
  children.push(body("12 家团队表态（样本覆盖 75%），分歧度 2。众数指向边际上行。中信建投指出高油价冲击下中国成品油、肥料出口呈现价增量减特征；中信证券强调万得全 A 的 EPS 与 PPI 走势高度同步，企业盈利显著改善通常需要 PPI 回升至 5% 以上。东吴证券则持不同意见，认为中长期仍需警惕产能释放后的价格回落。"));

  children.push(h2("2.3 货币政策：共识偏向边际宽松"));
  children.push(body("16 家团队全部表态且分歧度为 0，是本周最强烈的共识。东吴证券、中信建投、中金公司、中信证券、中泰证券一致指向边际宽松。核心逻辑包括：美国就业反弹的可持续性存疑、美联储降息路径长期仍延续、央行被动投放已带来充足流动性、债市对基本面偏弱已有定价等。"));

  children.push(h2("2.4 财政政策：共识偏向边际扩张"));
  children.push(body("9 家团队表态（样本覆盖 56%），分歧度 0，众数为边际扩张。中信证券指出 5 月政府债净融资 1.22 万亿元，财政发力仍有空间；广发证券提示今年的 8000 亿新型政策性金融工具尚未进入释放落地期；兴业证券、华创证券、国信证券均指向财政支出进一步加速。"));

  children.push(h2("2.5 海外环境：共识偏向边际恶化"));
  children.push(body("5 家团队表态（样本覆盖 31%），分歧度 0，众数为边际恶化。东吴证券提示海外流动性紧张可能持续，叠加 SpaceX 上市的抽水效应，6 月海外风险资产面临流动性考验；中信证券强调中美贸易摩擦、内外需求复苏不及预期、地缘政治风险三大变量；广发证券、申万宏源同样指向外部环境的不确定性。"));

  // ===== 策略观点 =====
  children.push(h1("三、策略观点详解"));

  children.push(h2("3.1 市场整体观点：共识偏向中性"));
  children.push(body("7 家策略团队表态（样本覆盖 41%），中位数 0，众数为中性。中金公司认为下半年中美宏观流动性均有望保持适度充裕；广发证券指出一级市场 IPO 融资已升至高分位，风险偏好正从少数龙头向更广泛的 AI 资产外溢，但 VXN 波动率仍处中性区间，市场尚未进入全面亢奋状态。国金证券相对谨慎，提示个人投资者（两融等）已转向净流出。"));

  children.push(h2("3.2 板块配置：通信、电子、计算机获正向推荐"));
  children.push(tableCaption("表 2：本周板块配置标签汇总"));
  children.push(buildTable(
    ["方向", "板块", "正向/负向/中性"],
    [
      ["正向", "通信", "3 / 0 / 13"],
      ["正向", "电子", "2 / 0 / 12"],
      ["正向", "计算机", "2 / 0 / 9"],
      ["正向", "公用事业", "1 / 0 / 6"],
      ["正向", "有色", "1 / 0 / 13"],
      ["负向", "医药", "0 / 1 / 11"],
      ["负向", "电新", "0 / 1 / 2"],
      ["负向", "石油石化", "0 / 1 / 7"],
    ],
    [15, 30, 55]
  ));
  children.push(body("通信板块获 3 家团队正向推荐，居所有板块之首，核心驱动力来自头部云厂商资本开支向算力、光通信、服务器等多环节传导。电子板块 2 家正向，基础化工、有色金属、建筑材料换手率上升显示周期与顺周期方向交易热度回升。医药、电新、石油石化各获 1 家负向推荐。"));

  children.push(h2("3.3 风格判断与主题机会"));
  children.push(tableCaption("表 3：风格判断与主题标签"));
  children.push(buildTable(
    ["类型", "方向", "标的", "正/负/中性"],
    [
      ["风格", "正向", "中证500", "1 / 0 / 3"],
      ["风格", "正向", "红利", "1 / 0 / 9"],
      ["风格", "负向", "沪深300", "0 / 2 / 7"],
      ["风格", "负向", "中证A500", "0 / 1 / 0"],
      ["主题", "正向", "两融", "2 / 0 / 2"],
      ["主题", "正向", "公募基金", "1 / 0 / 3"],
      ["主题", "负向", "股票ETF", "0 / 1 / 0"],
    ],
    [15, 12, 28, 45]
  ));

  children.push(h2("3.4 流动性：分歧较高，众数为边际改善"));
  children.push(body("11 家策略团队表态（样本覆盖 65%），分歧度 2，众数为边际改善。中信建投指出本周前 4 个交易日出现超过 300 亿元资金净流出，但长周期看 2025 年以来两融资金净流入超 1 万亿元，余额接近 3 万亿元；华泰证券观察到流出速度边际放缓；国信证券则从历史杠杆牛周期视角进行对比分析。中金公司、兴业证券持中性观点。"));

  // ===== 数据质量与覆盖 =====
  children.push(h1("四、数据质量与覆盖情况"));

  children.push(h2("4.1 覆盖统计"));
  children.push(tableCaption("表 4：本周覆盖质量指标"));
  children.push(buildTable(
    ["指标", "数值"],
    [
      ["覆盖团队总数", "38"],
      ["已覆盖（covered）", "33"],
      ["部分覆盖（partial）", "1"],
      ["来源丢失（source_lost）", "4"],
      ["覆盖率（covered + partial）", "89%"],
      ["全文率", "87%"],
      ["官方公众号来源", "34"],
      ["未知来源", "4"],
      ["零信号文档数", "0"],
      ["Mock / 占位样本数", "0"],
    ],
    [55, 45]
  ));

  children.push(h2("4.2 SQLite 数据入库情况"));
  children.push(tableCaption("表 5：数据库各表行数"));
  children.push(buildTable(
    ["表名", "行数", "说明"],
    [
      ["scan", "1", "本周扫描批次"],
      ["stance", "165", "立场记录"],
      ["stance_selection", "139", "维度选择记录"],
      ["source", "190", "来源链接"],
      ["intra_window_change", "0", "窗口内变化（本周无）"],
    ],
    [25, 15, 60]
  ));

  children.push(h2("4.3 待补采清单（P0/P1 优先级）"));
  children.push(body("以下 5 家团队来源为非官方或仅获取摘要，建议在下一轮扫描中优先补采官方渠道全文，以提升整体数据质量。"));
  children.push(tableCaption("表 6：优先补采清单"));
  children.push(buildTable(
    ["优先级", "团队", "当前来源类型", "问题", "建议操作"],
    [
      ["P0", "中信证券:strategy", "unknown", "失败、非官方、非全文", "补官方公众号或券商官方研究平台全文"],
      ["P0", "中国银河证券:macro", "unknown", "失败、非官方、非全文", "补官方公众号或券商官方研究平台全文"],
      ["P0", "中国银河证券:strategy", "unknown", "失败、非官方、非全文", "补官方公众号或券商官方研究平台全文"],
      ["P0", "国联民生证券:strategy", "unknown", "失败、非官方、非全文", "补官方公众号或券商官方研究平台全文"],
      ["P1", "华西证券:strategy", "official_wechat", "仅摘要、非全文", "补 full_article 正文并标注完整性"],
    ],
    [8, 22, 18, 27, 25]
  ));

  // ===== 实体关注度 =====
  children.push(h1("五、实体关注度排行"));
  children.push(body("基于本周 38 家团队的策略观点，对被提及的板块、风格、指数、主题进行统计，按正向关注度排序。"));
  children.push(tableCaption("表 7：实体关注度 Top 10"));
  children.push(buildTable(
    ["实体", "正向", "负向", "中性", "提及团队数"],
    [
      ["通信（行业）", "3", "0", "13", "16"],
      ["有色（行业）", "1", "0", "13", "14"],
      ["电子（行业）", "2", "0", "12", "13"],
      ["计算机（行业）", "2", "0", "9", "11"],
      ["红利（风格）", "1", "0", "9", "10"],
      ["医药（行业）", "0", "1", "11", "12"],
      ["沪深300（指数）", "0", "2", "7", "9"],
      ["食品饮料（行业）", "0", "0", "8", "8"],
      ["公用事业（行业）", "1", "0", "6", "7"],
      ["军工（行业）", "0", "0", "7", "7"],
    ],
    [35, 13, 13, 14, 25]
  ));
  children.push(body("通信板块以 16 家团队提及、3 家正向推荐居首，成为本周最受关注的行业方向。电子、有色、计算机紧随其后。负向方面，沪深300 指数获 2 家负向，反映大盘宽基在当前环境下相对承压。"));

  // ===== 证据摘录 =====
  children.push(h1("六、关键证据摘录"));
  children.push(body("以下摘录本周各维度最具代表性的原文片段，完整证据链与原始链接详见每周简报（weekly_brief.md）。"));

  children.push(h2("6.1 宏观维度关键证据"));
  children.push(tableCaption("表 8：宏观维度证据摘录"));
  children.push(buildTable(
    ["维度", "团队", "观点", "原文摘录"],
    [
      ["增长", "东吴证券", "边际改善", "风险提示：美国关税政策仍有不确定性；政策出台力度低于市场预期；房地产改善的持续性待观察。"],
      ["增长", "中信建投", "边际改善", "周五债市资金面边际改善，中长端品种走强，但短端品种卖盘较重，曲线走平。"],
      ["通胀", "中信建投", "边际上行", "在高油价冲击下，中国成品油、肥料等产品出口呈现价增量减特征，但在价格抬升带动下，出口金额仍实现较快增长。"],
      ["通胀", "中信证券", "边际上行", "历史数据显示，万得全A的EPS与PPI走势高度同步，企业盈利的显著改善通常需要PPI回升至5%以上。"],
      ["货币政策", "中金公司", "边际宽松", "5月中下旬以来，债市对基本面偏弱已有一定程度定价，利率衍生品隐含的未来利率预期指数也低至去年央行宣布降准降息前的水平附近。"],
      ["货币政策", "中泰证券", "边际宽松", "今年央行降准的必要性不大，因为被动投放的基础货币已经给金融市场带来了不低的流动性。"],
      ["财政政策", "中信证券", "边际扩张", "政府债隐含财政发力仍有空间，5月政府债净融资1.22万亿元，同比少增2385亿元。"],
      ["财政政策", "广发证券", "边际扩张", "从政金债+PSL和5月社融数据委托贷款分项来看，今年的8000亿新型政策性金融工具还未进入释放落地期。"],
      ["海外环境", "东吴证券", "边际恶化", "海外因美联储紧货币预期而来的流动性紧张状况可能持续，叠加SpaceX上市带来的抽水效应，6月海外风险资产或将面临流动性考验。"],
    ],
    [12, 14, 12, 62]
  ));

  children.push(h2("6.2 策略维度关键证据"));
  children.push(tableCaption("表 9：策略维度证据摘录"));
  children.push(buildTable(
    ["维度", "团队", "观点/标签", "原文摘录"],
    [
      ["市场整体", "中金公司", "中性", "美国货币政策有望维持中性偏松，中国仍存进一步宽松空间，下半年中美宏观流动性均有望保持适度充裕。"],
      ["市场整体", "广发证券", "中性", "一级市场IPO融资已经升至高分位，说明风险偏好正在从少数龙头向更广泛的AI资产外溢；但VXN波动率仍处中性区间。"],
      ["板块配置", "东吴证券", "通信", "头部云厂商掌握着产业链最核心的需求入口，其资本开支变化会逐层传导至算力、光通信、服务器等多个环节。"],
      ["板块配置", "中泰证券", "电子", "基础化工、有色金属、建筑材料换手率上升幅度居前，显示周期与部分顺周期方向交易热度边际回升。"],
      ["风格判断", "东吴证券", "红利", "如果AI的经济价值迟迟无法得到充分验证，真正值得重视的可能并非估值泡沫，而是融资循环能否持续运转。"],
      ["流动性", "中信建投", "边际改善", "2025年以来两融资金净流入超过1万亿元，截至6月11日两融资金余额接近3万亿元，占A股流通市值比例达2.8%。"],
    ],
    [12, 14, 14, 60]
  ));

  // ===== 结论 =====
  children.push(h1("七、综合结论与展望"));

  children.push(h2("7.1 本周核心判断"));
  children.push(body("综合 38 家券商团队的本周观点，可提炼出以下核心判断：第一，国内货币政策宽松预期高度一致（16/16 共识），叠加财政发力空间仍存（9/9 共识），构成对国内流动性与需求侧的积极支撑；第二，海外环境恶化预期同样高度一致（5/5 共识），主要风险点集中在美联储紧货币预期、地缘政治与中美贸易摩擦。"));
  children.push(body("第三，增长与通胀两个核心宏观维度分歧较大，反映市场对经济复苏力度与价格传导路径尚无定论；第四，策略层面市场整体观点偏中性，通信、电子、计算机等科技成长方向获较多正向推荐，而沪深300 等大盘宽基相对承压，两融资金短期净流出但长周期仍处高位。"));

  children.push(h2("7.2 数据工程状态"));
  children.push(bullet("MVP 验收：通过（acceptance_passed = True）。"));
  children.push(bullet("工程就绪：是（engineering_ready = True）。"));
  children.push(bullet("生产就绪：是（production_ready = True）。"));
  children.push(bullet("Agent 交接：就绪（agent_handoff_status = ready）。"));
  children.push(bullet("历史趋势：暂不充分（需累计至少 4 个真实周度扫描后启用）。"));

  children.push(h2("7.3 后续建议"));
  children.push(body("一是优先补采中信证券:strategy、中国银河证券、国联民生证券:strategy 等团队的官方公众号全文，消除当前 4 个非官方来源样本；二是持续积累周度扫描数据，待累计达到 4 周后激活时序趋势分析模块；三是针对通信、电子等高关注度板块建立专项跟踪，观察观点一致性的演变。"));

  return children;
}

// ─────────── 文档组装 ───────────
const doc = new Document({
  creator: "macro-strategy-analyst",
  title: "2026-W24 分析师观点周报",
  styles: {
    default: {
      document: {
        run: {
          font: { ascii: "Times New Roman", eastAsia: "SimSun" },
          size: 24, color: "000000",
        },
        paragraph: { spacing: { line: 312 } },
      },
      heading1: {
        run: { font: { ascii: "Calibri", eastAsia: "SimHei" }, size: 32, bold: true, color: "0F2027" },
        paragraph: { spacing: { before: 360, after: 160, line: 312 } },
      },
      heading2: {
        run: { font: { ascii: "Calibri", eastAsia: "SimHei" }, size: 28, bold: true, color: "0F2027" },
        paragraph: { spacing: { before: 240, after: 120, line: 312 } },
      },
      heading3: {
        run: { font: { ascii: "Calibri", eastAsia: "SimHei" }, size: 24, bold: true, color: "203A43" },
        paragraph: { spacing: { before: 200, after: 100, line: 312 } },
      },
    },
  },
  sections: [
    // 封面
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838, orientation: PageOrientation.PORTRAIT },
          margin: { top: 0, bottom: 0, left: 0, right: 0 },
        },
      },
      children: buildCover(),
    },
    // 正文
    {
      properties: {
        type: SectionType.NEXT_PAGE,
        page: {
          size: { width: 11906, height: 16838, orientation: PageOrientation.PORTRAIT },
          margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 },
          pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: "2026-W24 分析师观点周报", size: 18, color: "808080",
              font: { ascii: "Calibri", eastAsia: "Microsoft YaHei" } })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "808080" })],
          })],
        }),
      },
      children: buildBody(),
    },
  ],
});

const outPath = "/Users/chen/Documents/macro-strategy-analyst/2026-W24-分析师观点周报.docx";
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("✅ 文档已生成: " + outPath);
  console.log("   文件大小: " + (buf.length / 1024).toFixed(1) + " KB");
}).catch(err => {
  console.error("❌ 生成失败:", err);
  process.exit(1);
});
