(function (root, factory) {
  const value = factory();
  if (typeof module === 'object' && module.exports) module.exports = value;
  else root.IRCompanyIndustries = value;
})(globalThis, () => {
  // A股行业分组：申万一级行业（标准名）。分组为 IR System 自有，行业名与代码对齐申万一级。
  // stocks 取自 akshare index_component_sw 按最新权重前 3 的成分（2026-09 拉取），
  // 仅作行业示意，不代表实时推荐或完整成分。矩阵单元格为占位，不代表已接入能力。
  const MATRIX_COLUMNS = Object.freeze(['公告', '新闻', '研报', '电话会', '作文']);

  const groups = Object.freeze([
    group('tmt', 'TMT', [
      industry('电子', '801080', ['寒武纪', '长鑫科技', '北方华创']),
      industry('通信', '801770', ['中际旭创', '新易盛', '天孚通信']),
      industry('计算机', '801750', ['海康威视', '中科曙光', '科大讯飞']),
      industry('传媒', '801760', ['世纪华通', '蓝色光标', '分众传媒']),
    ]),
    group('resources', '资源', [
      industry('有色金属', '801050', ['紫金矿业', '洛阳钼业', '中国铝业']),
      industry('煤炭', '801950', ['中国神华', '陕西煤业', '电投能源']),
      industry('石油石化', '801960', ['中国石油', '中国石化', '中国海油']),
      industry('钢铁', '801040', ['包钢股份', '宝钢股份', '方大炭素']),
    ]),
    group('manufacturing', '制造', [
      industry('电力设备', '801730', ['宁德时代', '阳光电源', '国电南瑞']),
      industry('机械设备', '801890', ['汇川技术', '三一重工', '华工科技']),
      industry('汽车', '801880', ['比亚迪', '潍柴动力', '福耀玻璃']),
      industry('国防军工', '801740', ['中国船舶', '松发股份', '航发动力']),
      industry('轻工制造', '801140', ['太阳纸业', '裕同科技', '公牛集团']),
    ]),
    group('cyclical', '周期', [
      industry('基础化工', '801030', ['万华化学', '盐湖股份', '藏格矿业']),
      industry('公用事业', '801160', ['长江电力', '中国核电', '三峡能源']),
      industry('交通运输', '801170', ['顺丰控股', '中远海控', '招商轮船']),
      industry('建筑装饰', '801720', ['中国建筑', '中国中铁', '中国电建']),
      industry('建筑材料', '801710', ['中国巨石', '中材科技', '海螺水泥']),
      industry('环保', '801970', ['高能环境', '紫金龙净', '浙富控股']),
    ]),
    group('consumption', '消费', [
      industry('食品饮料', '801120', ['贵州茅台', '伊利股份', '五粮液']),
      industry('家用电器', '801110', ['美的集团', '格力电器', '三花智控']),
      industry('农林牧渔', '801010', ['牧原股份', '温氏股份', '海大集团']),
      industry('商贸零售', '801200', ['中国中免', '小商品城', '供销大集']),
      industry('社会服务', '801210', ['华测检测', '中公教育', 'ST豆神']),
      industry('纺织服饰', '801130', ['雅戈尔', '海澜之家', '伟星股份']),
      industry('美容护理', '801980', ['爱美客', '珀莱雅', '华熙生物']),
    ]),
    group('healthcare', '医药', [
      industry('医药生物', '801150', ['药明康德', '恒瑞医药', '迈瑞医疗']),
    ]),
    group('financials', '金融', [
      industry('银行', '801780', ['招商银行', '兴业银行', '农业银行']),
      industry('非银金融', '801790', ['中国平安', '中信证券', '东方财富']),
      industry('房地产', '801180', ['保利发展', '万科A', '张江高科']),
    ]),
    group('conglomerate', '综合', [
      industry('综合', '801230', ['东阳光', '粤桂股份', '时代新材']),
    ]),
  ]);

  function group(id, label, industries) {
    return Object.freeze({ id, label, industries: Object.freeze(industries) });
  }
  function industry(name, code, stocks) {
    return Object.freeze({ name, code, stocks: Object.freeze(stocks) });
  }

  return Object.freeze({ groups, MATRIX_COLUMNS });
});
