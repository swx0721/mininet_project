// slide-02.js — Table of Contents
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'toc',
  index: 2,
  title: '目录'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Left accent column
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.45, h: 5.625,
    fill: { color: theme.primary }
  });

  // Title
  slide.addText("目  录", {
    x: 1.0, y: 0.45, w: 4, h: 0.7,
    fontSize: 32, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  // Thin accent line under title
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 1.0, y: 1.15, w: 1.6, h: 0.04,
    fill: { color: theme.accent }
  });

  const sections = [
    { num: "01", title: "网络拓扑设计", desc: "六区域 · 双服务器 · 三层架构" },
    { num: "02", title: "基础连通性验证", desc: "跨区域 PING 互通测试" },
    { num: "03", title: "QoS 消融实验", desc: "HTB 两级优先级 · 流量整形" },
    { num: "04", title: "负载均衡消融实验", desc: "Round Robin · Jain 公平指数" },
    { num: "05", title: "安全策略消融实验", desc: "ACL + IDS + SQLite 审计" },
    { num: "06", title: "VPN + 双重 ACL", desc: "校外安全接入 · 两层访问控制" },
  ];

  const startY = 1.5;
  const rowH = 0.62;

  sections.forEach((s, i) => {
    const y = startY + i * rowH;

    // Number circle
    slide.addShape(pres.shapes.OVAL, {
      x: 1.0, y: y + 0.08, w: 0.42, h: 0.42,
      fill: { color: i === 0 ? theme.accent : theme.secondary }
    });
    slide.addText(s.num, {
      x: 1.0, y: y + 0.08, w: 0.42, h: 0.42,
      fontSize: 14, fontFace: "Georgia",
      color: "FFFFFF", bold: true, align: "center", valign: "middle",
      margin: 0
    });

    // Section title
    slide.addText(s.title, {
      x: 1.65, y: y + 0.02, w: 5.0, h: 0.3,
      fontSize: 18, fontFace: "Microsoft YaHei",
      color: theme.primary, bold: true, align: "left",
      margin: 0
    });

    // Section desc
    slide.addText(s.desc, {
      x: 1.65, y: y + 0.32, w: 5.0, h: 0.22,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: "808080", align: "left",
      margin: 0
    });
  });

  // Page number badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("2", {
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
  pres.writeFile({ fileName: "slide-02-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
