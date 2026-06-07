// slide-03.js — 网络拓扑设计
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 3,
  title: '网络拓扑设计'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("网络拓扑设计", {
    x: 0.5, y: 0.1, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // LEFT: Description panel
  const leftX = 0.45;
  const leftW = 4.8;

  // Topology specs
  const specs = [
    { label: "区域规划", value: "6 个业务区域 (宿舍/教学/图书馆/办公/财务/人事)" },
    { label: "双服务器", value: "Server1 (10.0.60.0/28) + Server2 (10.0.60.16/28)" },
    { label: "架构层次", value: "接入-汇聚-核心三层交换架构" },
    { label: "子网划分", value: "独立 VLSM 子网 (/20 /23 /24 /26)" },
  ];

  let yPos = 1.15;

  specs.forEach((spec) => {
    // Label badge
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: leftX, y: yPos, w: 1.3, h: 0.3,
      fill: { color: theme.accent },
      rectRadius: 0.05
    });
    slide.addText(spec.label, {
      x: leftX, y: yPos, w: 1.3, h: 0.3,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "FFFFFF", bold: true, align: "center", valign: "middle",
      margin: 0
    });

    // Value text
    slide.addText(spec.value, {
      x: leftX + 1.45, y: yPos, w: leftW - 1.45, h: 0.3,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: "333333", align: "left", valign: "middle",
      margin: 0
    });

    yPos += 0.5;
  });

  // RIGHT: Topology diagram (simplified shapes)
  const rx = 5.6;
  const ry = 1.15;

  // Core router (center)
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: rx + 1.5, y: ry + 2.0, w: 1.5, h: 0.5,
    fill: { color: theme.primary },
    rectRadius: 0.08
  });
  slide.addText("核心路由器 r1", {
    x: rx + 1.5, y: ry + 2.0, w: 1.5, h: 0.5,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // Zone labels (6 zones as small boxes)
  const zones = [
    { name: "宿舍", subnet: "/20", color: theme.secondary },
    { name: "教学", subnet: "/20", color: theme.secondary },
    { name: "图书馆", subnet: "/23", color: theme.secondary },
    { name: "办公", subnet: "/24", color: theme.accent },
    { name: "财务", subnet: "/26", color: "E76F51" },
    { name: "人事", subnet: "/26", color: "E76F51" },
  ];

  zones.forEach((z, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const zx = rx + col * 1.45;
    const zy = ry + row * 1.0;

    // Zone box (aggregation switch)
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: zx, y: zy, w: 1.2, h: 0.45,
      fill: { color: z.color },
      rectRadius: 0.05
    });
    slide.addText(`${z.name} (10.0.${[0, 16, 32, 34, 35, 35][i]}.0${z.subnet})`, {
      x: zx, y: zy, w: 1.2, h: 0.45,
      fontSize: 7, fontFace: "Microsoft YaHei",
      color: "FFFFFF", bold: true, align: "center", valign: "middle",
      margin: 0
    });

    // Connection line (simple)
    if (i === 0) {
      slide.addShape(pres.shapes.LINE, {
        x: zx + 0.6, y: zy + 0.45, w: 0.01, h: 0.3,
        line: { color: theme.accent, width: 1.5, dashType: "solid" }
      });
    }
  });

  // Servers box
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: rx + 0.3, y: ry + 3.2, w: 3.9, h: 0.55,
    fill: { color: theme.light },
    rectRadius: 0.05,
    line: { color: theme.accent, width: 1 }
  });
  slide.addText("Server1 + Server2   (10.0.60.0/28, 10.0.60.16/28)", {
    x: rx + 0.3, y: ry + 3.2, w: 3.9, h: 0.55,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // Connection lines from router to servers (vertical line)
  slide.addShape(pres.shapes.LINE, {
    x: rx + 2.25, y: ry + 2.5, w: 0.01, h: 0.7,
    line: { color: theme.accent, width: 1.5, dashType: "solid" }
  });

  // Bottom note
  slide.addText("接入-汇聚二层: 每区域 3 台接入交换机 → 1 台汇聚交换机 → r1", {
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
  slide.addText("3", {
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
  pres.writeFile({ fileName: "slide-03-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
