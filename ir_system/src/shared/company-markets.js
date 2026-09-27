(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;else root.IRCompanyMarkets=value;})(globalThis,()=>{
  // Market facts are static reference text owned by IR System. Coverage and
  // status always come from the active provider's per-market mapping.
  const markets=Object.freeze([
    Object.freeze({id:'A_SHARE',child:'companies-a-share',label:'A股',title:'A股上市公司',
      facts:Object.freeze([['交易所','上交所 · 深交所 · 北交所'],['代码格式','600519.SH · 000001.SZ · 北交所 .BJ'],['官方披露','巨潮资讯网 · 交易所网站']])}),
    Object.freeze({id:'HK',child:'companies-hk',label:'港股',title:'港股上市公司',
      facts:Object.freeze([['交易所','港交所主板 · GEM'],['代码格式','00700.HK（5 位代码）'],['官方披露','披露易 HKEXnews']])}),
    Object.freeze({id:'US',child:'companies-us',label:'美股',title:'美股上市公司',
      facts:Object.freeze([['交易所','NYSE · Nasdaq'],['代码格式','AAPL（ticker）'],['官方披露','SEC EDGAR']])}),
  ]);
  const sections=Object.freeze([
    Object.freeze({id:'search',label:'Company Search',copy:'按代码或简称定位公司与证券主数据。'}),
    Object.freeze({id:'financials',label:'Financials',copy:'财务报表与标准化财务数据。'}),
    Object.freeze({id:'filings',label:'Filings',copy:'法定公告、监管披露与公司 IR 文件。'}),
    Object.freeze({id:'events',label:'Events',copy:'业绩发布、分红、股东大会等公司事件。'}),
    Object.freeze({id:'research',label:'Related Research',copy:'与该公司相关的研究资料。'}),
  ]);

  function marketFor(childId,remembered){
    return (markets.find(m=>m.child===childId)||markets.find(m=>m.id===remembered)||markets[0]).id;
  }

  function view(data={},marketId){
    const market=markets.find(m=>m.id===marketId)||markets[0];
    const mapping=Array.isArray(data.providerDetails?.markets)?data.providerDetails.markets:null;
    const entry=mapping?.find(m=>m&&m.id===market.id);
    // Without a per-market mapping, a module-level "partial" says nothing
    // about a specific market, so only demo/unavailable are carried over.
    const fallback=['demo','unavailable'].includes(data.status)?data.status:'planned';
    return {
      market,
      mapped:Boolean(mapping),
      status:mapping?(entry?.status||'unavailable'):fallback,
      sections:sections.map(section=>{
        const provided=entry?.sections?.find(s=>s&&s.id===section.id);
        const sources=Array.isArray(provided?.sources)?provided.sources.filter(s=>s&&s.provider):[];
        return {...section,status:mapping?(provided?.status||'unavailable'):fallback,sources};
      }),
    };
  }

  return Object.freeze({markets,sections,marketFor,view});
});
