const { NAVIGATION } = require("../navigation");

const NOW = () => new Date().toISOString();

const MODULE_STATUS = {
  overview: "demo",
  macro: "demo",
  sector: "planned",
  eq: "demo",
  fi: "planned",
  fx: "planned",
  comdty: "demo",
  companies: "demo",
  research: "demo",
  calendar: "planned",
  watchlists: "local",
  data: "ready",
};

class DemoProvider {
  constructor() {
    this.id = "demo";
    this.label = "Demo Provider";
  }

  async probe() {
    return {
      protocol: "ir-system-provider/v1",
      provider: this.id,
      label: this.label,
      status: "ready",
      mode: "demo",
      fetchedAt: NOW(),
      modules: NAVIGATION.map((item) => ({ id: item.id, status: MODULE_STATUS[item.id] || "planned" })),
      diagnostics: ["Illustrative local fixtures only. No value is a live market observation."],
    };
  }

  async bootstrap() {
    return {
      schemaVersion: 1,
      generatedAt: NOW(),
      dataMode: "demo",
      asOf: "DEMO / NOT LIVE",
      headline: "Cross-asset workspace ready for local data providers",
      markets: [
        { market: "CN", name: "CSI 300", value: "4,128.36", changePct: 0.62, status: "demo" },
        { market: "HK", name: "Hang Seng", value: "21,742.18", changePct: -0.31, status: "demo" },
        { market: "US", name: "S&P 500", value: "5,896.42", changePct: 0.44, status: "demo" },
        { market: "RATES", name: "US 10Y", value: "4.214%", changeBp: 2.8, status: "demo" },
      ],
      pulse: [
        { label: "Risk appetite", score: 72, detail: "Equities / rates / USD", status: "demo" },
        { label: "China growth", score: 58, detail: "A/H equity breadth", status: "demo" },
        { label: "Rate pressure", score: 64, detail: "DM sovereign curves", status: "demo" },
        { label: "Commodity impulse", score: 43, detail: "Energy / metals / agriculture", status: "demo" },
      ],
      research: [
        { type: "MACRO", title: "政策与流动性观察", subtitle: "示例研究条目", time: "09:42" },
        { type: "COMPANY", title: "公司公告与预期变化", subtitle: "示例披露条目", time: "08:15" },
        { type: "RATES", title: "收益率曲线日度变化", subtitle: "示例数据条目", time: "07:30" },
      ],
    };
  }

  async moduleData(moduleId) {
    const module = NAVIGATION.find((item) => item.id === moduleId);
    return {
      schemaVersion: 1,
      moduleId,
      title: module?.label || moduleId,
      status: MODULE_STATUS[moduleId] || "planned",
      dataMode: "demo",
      asOf: "DEMO / NOT LIVE",
      summary: demoSummary(moduleId),
      sections: module?.children || [],
      diagnostics: ["This page is using illustrative fixtures until a real provider supplies the required capability."],
    };
  }
}

function demoSummary(moduleId) {
  const summaries = {
    macro: "增长、通胀、政策、流动性与宏观到行业的传导工作区。",
    sector: "申万行业维度的工作区，结构与成分待接入。",
    eq: "A股、港股、美股及其股票、ETF与权益衍生品。",
    fi: "利率、曲线、信用、债券基金与利率衍生品。",
    fx: "即期、远期、掉期、期权及宏观利差映射。",
    comdty: "能源、金属、农产品、期限结构与商品衍生品。",
    companies: "公司实体、财务、披露、事件与相关研究。",
    research: "日报、宏观、行业、公司、纪要、政策与图表的统一资料库。",
    calendar: "宏观数据、财报、政策会议和合约到期日历。",
    watchlists: "本机保存的资产、公司、主题与研究关注列表。",
    data: "数据提供方、能力范围、更新时间与诊断。",
  };
  return summaries[moduleId] || "Local-first investment research workspace.";
}

module.exports = { DemoProvider };
