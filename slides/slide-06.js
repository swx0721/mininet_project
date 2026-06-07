// slide-06.js — 负载均衡消融实验
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 6,
  title: '负载均衡消融实验'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("负载均衡消融实验 — Round Robin 调度", {
    x: 0.5, y: 0.1, w: 9, h: 0.6,
    fontSize: 26, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // LEFT: Setup description
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.45, y: 1.05, w: 4.7, h: 3.55,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("实验设置", {
    x: 0.7, y: 1.15, w: 4, h: 0.3,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  // Architecture: Server visual
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.9, y: 1.65, w: 3.7, h: 0.4,
    fill: { color: theme.primary },
    rectRadius: 0.05
  });
  slide.addText("请求", {
    x: 0.9, y: 1.65, w: 1.2, h: 0.4,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });
  slide.addText("Round Robin 调度器 →", {
    x: 2.1, y: 1.65, w: 2.5, h: 0.4,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: theme.accent, bold: true, align: "left", valign: "middle",
    margin: 0
  });

  // Arrows and servers
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 1.4, y: 2.3, w: 1.5, h: 0.5,
    fill: { color: theme.secondary },
    rectRadius: 0.05
  });
  slide.addText("Server 1\n10.0.60.2", {
    x: 1.4, y: 2.3, w: 1.5, h: 0.5,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 3.5, y: 2.3, w: 1.5, h: 0.5,
    fill: { color: theme.secondary },
    rectRadius: 0.05
  });
  slide.addText("Server 2\n10.0.60.18", {
    x: 3.5, y: 2.3, w: 1.5, h: 0.5,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // Key config points
  const keyPoints = [
    "双服务器对称端口 (iperf3 5201-5207)",
    "互斥锁保护共享 Round Robin 索引",
    "Jain 公平指数评估负载分布均匀性",
    "支持 static / round_robin / random 三种算法",
  ];

  keyPoints.forEach((pt, i) => {
    slide.addText([
      { text: "  ▸ ", options: { color: theme.accent, bold: true } },
      { text: pt, options: {} },
    ], {
      x: 0.7, y: 3.05 + i * 0.33, w: 4.3, h: 0.3,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "444444", align: "left", valign: "middle",
      margin: 0
    });
  });

  // Jain fairness formula
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.9, y: 4.2, w: 3.7, h: 0.28,
    fill: { color: "FFF8E1" },
    rectRadius: 0.03
  });
  slide.addText("J = (Σx_i)² / (n · Σx_i²)", {
    x: 0.9, y: 4.2, w: 3.7, h: 0.28,
    fontSize: 11, fontFace: "Georgia",
    color: "BF8C00", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // RIGHT: Results
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.4, y: 1.05, w: 4.15, h: 3.55,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("实验结果", {
    x: 5.65, y: 1.15, w: 3.5, h: 0.3,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  // Results table
  const resData = [
    ["指标", "Final-LB", "Final"],
    ["S1 负载 (Mbps)", "~17", "~8.5"],
    ["S2 负载 (Mbps)", "~0", "~8.5"],
    ["Jain 公平指数", "0.50", "1.00"],
    ["均衡效果", "单点承载", "均分负载"],
  ];

  let ry = 1.65;
  const rColWs = [1.3, 1.3, 1.3];
  const rColXs = [5.65, 6.95, 8.25];

  resData.forEach((row, ri) => {
    const isHeader = ri === 0;
    const rowH = isHeader ? 0.35 : 0.32;

    if (isHeader) {
      slide.addShape(pres.shapes.RECTANGLE, {
        x: rColXs[0], y: ry, w: 3.9, h: rowH,
        fill: { color: theme.primary }
      });
    }

    row.forEach((cell, ci) => {
      if (!isHeader) {
        const isEven = ri % 2 === 0;
        slide.addShape(pres.shapes.RECTANGLE, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fill: { color: isEven ? "FFFFFF" : "F5F5F5" }
        });
        slide.addText(cell, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fontSize: 10, fontFace: "Microsoft YaHei",
          color: ci === 0 ? theme.primary : (ci === 2 ? "2A7D2F" : "999999"),
          bold: ci === 0 || ci === 2,
          align: "center", valign: "middle",
          margin: 0
        });
      } else {
        slide.addText(cell, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fontSize: 10, fontFace: "Microsoft YaHei",
          color: "FFFFFF", bold: true,
          align: "center", valign: "middle",
          margin: 0
        });
      }
    });
    ry += rowH + 0.05;
  });

  // Key insight
  ry += 0.25;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.65, y: ry, w: 3.5, h: 0.55,
    fill: { color: "E8F5E9" },
    rectRadius: 0.05
  });
  slide.addText("核心结论: Round Robin 使 Jain 指数\n从 0.50 → 1.00，双服务器负载完全均衡", {
    x: 5.85, y: ry + 0.05, w: 3.1, h: 0.45,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "2A7D2F", bold: true, align: "left", valign: "middle",
    margin: 0
  });

  // Bottom note
  slide.addText("实验方法: Final-LB (无负载均衡) vs Final (Round Robin) · 泊松流量模型 λ=0.05 · iperf3 多客户端请求", {
    x: 0.5, y: 4.95, w: 9, h: 0.35,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "808080", italic: true, align: "left",
    margin: 0
  });

  // Page number badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("6", {
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
  pres.writeFile({ fileName: "slide-06-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
