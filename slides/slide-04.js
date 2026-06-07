// slide-04.js — 基础 PING 连通性验证
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 4,
  title: '基础 PING 连通性验证'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("基础连通性验证 — PING 测试", {
    x: 0.5, y: 0.1, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // Description box
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.45, y: 1.05, w: 4.3, h: 1.8,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("测试说明", {
    x: 0.7, y: 1.15, w: 3.8, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  const descItems = [
    "验证所有业务区域间的基础 IP 层连通性",
    "测试跨子网路由转发是否正常工作",
    "验证三层交换机 + 核心路由器转发路径",
    "确认双服务器可达性 (ICMP Echo/Reply)",
  ];

  descItems.forEach((item, i) => {
    slide.addText([
      { text: "  ▪ ", options: { color: theme.accent } },
      { text: item, options: {} },
    ], {
      x: 0.7, y: 1.55 + i * 0.32, w: 3.9, h: 0.3,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: "444444", align: "left",
      margin: 0
    });
  });

  // Key test pairs
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.45, y: 3.1, w: 4.3, h: 1.6,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("测试路径", {
    x: 0.7, y: 3.2, w: 3.8, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  const paths = [
    "dorm1 → teach1  (宿舍 ↔ 教学)",
    "office1 → finance1 (办公 → 财务)",
    "dorm1 → server1  (终端 → 服务器)",
    "lib1 → hr1 (图书馆 → 人事)",
  ];

  paths.forEach((p, i) => {
    // Path indicator
    slide.addShape(pres.shapes.OVAL, {
      x: 0.7, y: 3.6 + i * 0.28, w: 0.14, h: 0.14,
      fill: { color: "4CAF50" }
    });
    slide.addText(p, {
      x: 0.95, y: 3.55 + i * 0.28, w: 3.5, h: 0.25,
      fontSize: 10, fontFace: "Consolas",
      color: "444444", align: "left", valign: "middle",
      margin: 0
    });
  });

  // Screenshot placeholder - right side
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.1, y: 1.05, w: 4.45, h: 3.65,
    fill: { color: "F5F5F5" },
    rectRadius: 0.08,
    line: { color: "DDDDDD", width: 1.5, dashType: "dash" }
  });

  // Placeholder icon
  slide.addShape(pres.shapes.OVAL, {
    x: 6.65, y: 2.05, w: 1.3, h: 1.3,
    fill: { color: theme.light, transparency: 50 },
    line: { color: theme.accent, width: 2, dashType: "dash" }
  });

  slide.addText("PING 截图", {
    x: 5.5, y: 2.75, w: 3.6, h: 0.4,
    fontSize: 22, fontFace: "Microsoft YaHei",
    color: "AAAAAA", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  slide.addText("（待补充 Mininet PING 测试截图）", {
    x: 5.5, y: 3.65, w: 3.6, h: 0.3,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "BBBBBB", align: "center",
    margin: 0
  });

  // Bottom note
  slide.addText("测试环境: Mininet 虚拟网络 · 标准 ICMP Echo/Reply (ping -c 4)", {
    x: 0.5, y: 4.95, w: 9, h: 0.35,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "808080", italic: true, align: "left",
    margin: 0
  });

  // Page number badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("4", {
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
  pres.writeFile({ fileName: "slide-04-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
