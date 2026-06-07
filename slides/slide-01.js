// slide-01.js — Cover Page: 校园网络仿真项目
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'cover',
  index: 1,
  title: '校园网络仿真项目'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  // Decorative top bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: theme.accent }
  });

  // Decorative left accent block
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.2, w: 0.06, h: 2.0,
    fill: { color: theme.accent }
  });

  // Main Title
  slide.addText("校园网络仿真项目", {
    x: 1.0, y: 1.3, w: 8.0, h: 1.0,
    fontSize: 48, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // English Subtitle
  slide.addText("Campus Network Simulation based on Mininet", {
    x: 1.0, y: 2.3, w: 8.0, h: 0.5,
    fontSize: 18, fontFace: "Georgia",
    color: theme.light, italic: true, align: "left",
    margin: 0
  });

  // Subtitle line
  slide.addText("虚拟校园网拓扑设计 · QoS 流量整形 · 负载均衡 · 安全策略验证", {
    x: 1.0, y: 2.8, w: 8.0, h: 0.4,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.accent, align: "left",
    margin: 0
  });

  // Decorative bottom bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.0, w: 10, h: 0.625,
    fill: { color: theme.secondary },
    transparency: 40
  });

  // Bottom info
  slide.addText("计算机网络课程项目  ·  2026 年 6 月", {
    x: 1.0, y: 5.05, w: 8.0, h: 0.5,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: theme.light, align: "left",
    margin: 0
  });

  // Circle decoration top-right
  slide.addShape(pres.shapes.OVAL, {
    x: 8.5, y: 0.8, w: 1.2, h: 1.2,
    fill: { color: theme.accent, transparency: 70 }
  });
  slide.addShape(pres.shapes.OVAL, {
    x: 8.9, y: 1.5, w: 0.8, h: 0.8,
    fill: { color: theme.light, transparency: 60 }
  });

  return slide;
}

if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = { primary: "03045e", secondary: "0077b6", accent: "00b4d8", light: "90e0ef", bg: "F0F7FF" };
  createSlide(pres, theme);
  pres.writeFile({ fileName: "slide-01-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
