// slide-09.js — Summary / Closing
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'summary',
  index: 9,
  title: '总结'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  // Title
  slide.addText("总  结", {
    x: 0.6, y: 0.35, w: 3, h: 0.7,
    fontSize: 34, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // Accent line
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.05, w: 1.4, h: 0.04,
    fill: { color: theme.accent }
  });

  // Takeaway cards - 2x2 grid
  const takeaways = [
    {
      num: "01", title: "完整仿真拓扑",
      desc: "6 区域 + 双服务器\n接入-汇聚-核心三层架构\n独立 VLSM 子网划分"
    },
    {
      num: "02", title: "HTB QoS 流量整形",
      desc: "两级优先级队列\n财务最高优先 60% 带宽\n低优先级保活 10%"
    },
    {
      num: "03", title: "Round Robin 负载均衡",
      desc: "双服务器对称端口\nJain 公平指数 0.50 → 1.00\n互斥锁保护共享索引"
    },
    {
      num: "04", title: "三重安全防护",
      desc: "ACL 白/黑名单 + IDS 检测\nICMP Flood 限速 (5/40)\nSQLite 审计 3 条事件"
    },
    {
      num: "05", title: "VPN + 双重 ACL",
      desc: "外部隔离 DROP + 校内精细化\n三阶段接入: 认证→切换→授权\n校外低带宽安全互通"
    },
  ];

  const startX = 0.45;
  const startY = 1.35;
  const cardW = 2.85;
  const cardH = 1.5;
  const gapX = 0.25;
  const gapY = 0.2;

  takeaways.forEach((t, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const cx = startX + col * (cardW + gapX);
    const cy = startY + row * (cardH + gapY);

    // Card background
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: cx, y: cy, w: cardW, h: cardH,
      fill: { color: theme.secondary, transparency: 60 },
      rectRadius: 0.08
    });

    // Number
    slide.addText(t.num, {
      x: cx + 0.15, y: cy + 0.1, w: 0.35, h: 0.3,
      fontSize: 16, fontFace: "Georgia",
      color: theme.accent, bold: true, align: "left",
      margin: 0
    });

    // Title
    slide.addText(t.title, {
      x: cx + 0.55, y: cy + 0.1, w: cardW - 0.8, h: 0.3,
      fontSize: 14, fontFace: "Microsoft YaHei",
      color: "FFFFFF", bold: true, align: "left",
      margin: 0
    });

    // Description
    slide.addText(t.desc, {
      x: cx + 0.2, y: cy + 0.5, w: cardW - 0.5, h: cardH - 0.65,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: theme.light, align: "left",
      margin: 0
    });
  });

  // Thank you
  slide.addText("感谢聆听", {
    x: 0, y: 4.65, w: 10, h: 0.55,
    fontSize: 24, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // Page number badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("9", {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fontSize: 12, fontFace: "Georgia",
    color: "FFFFFF", bold: true, align: "center", valign: "middle"
  });

  return slide;
}

if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = { primary: "03045e", secondary: "0077b6", accent: "00b4d8", light: "90e0ef", bg: "F0F7FF" };
  createSlide(pres, theme);
  pres.writeFile({ fileName: "slide-09-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
