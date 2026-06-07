// slide-05.js — QoS 消融实验
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 5,
  title: 'QoS 消融实验'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("QoS 消融实验 — HTB 两级优先级流量整形", {
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

  // Priority table in left panel
  const prioData = [
    ["区域", "优先级", "保障带宽", "上限"],
    ["财务 (finance)", "prio=0", "12 Mbps", "20 Mbps"],
    ["办公/教学/图书馆/宿舍/人事", "prio=7", "2 Mbps", "20 Mbps"],
  ];

  let ty = 1.6;
  const colWs = [1.9, 0.8, 0.9, 0.8];
  const colXs = [0.7, 2.7, 3.55, 4.5];

  // Header row
  slide.addShape(pres.shapes.RECTANGLE, {
    x: colXs[0], y: ty, w: 4.3, h: 0.35,
    fill: { color: theme.primary }
  });
  prioData[0].forEach((h, ci) => {
    slide.addText(h, {
      x: colXs[ci], y: ty, w: colWs[ci], h: 0.35,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "FFFFFF", bold: true, align: "center", valign: "middle",
      margin: 0
    });
  });

  // Finance row
  ty += 0.38;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: colXs[0], y: ty, w: 4.3, h: 0.35,
    fill: { color: "E8F5E9" }
  });
  prioData[1].forEach((h, ci) => {
    slide.addText(h, {
      x: colXs[ci], y: ty, w: colWs[ci], h: 0.35,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "333333", bold: ci === 0, align: "center", valign: "middle",
      margin: 0
    });
  });

  // Others row
  ty += 0.38;
  slide.addShape(pres.shapes.RECTANGLE, {
    x: colXs[0], y: ty, w: 4.3, h: 0.45,
    fill: { color: "F5F5F5" }
  });
  slide.addText(prioData[2][0], {
    x: colXs[0], y: ty, w: colWs[0], h: 0.45,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "333333", bold: true, align: "center", valign: "middle",
    margin: 0
  });
  [1, 2, 3].forEach((ci) => {
    slide.addText(prioData[2][ci], {
      x: colXs[ci], y: ty, w: colWs[ci], h: 0.45,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "333333", align: "center", valign: "middle",
      margin: 0
    });
  });

  // Key points
  const keyPoints = [
    "HTB (Hierarchy Token Bucket) 两级优先级队列",
    "财务区域 prio=0 独享最高优先级",
    "tc class 添加 prio 参数实现优先级调度",
    "低优先级区域仅在财务处下限满足后获得剩余带宽",
  ];

  ty += 0.6;
  keyPoints.forEach((pt, i) => {
    slide.addText([
      { text: "  ▸ ", options: { color: theme.accent, bold: true } },
      { text: pt, options: {} },
    ], {
      x: 0.7, y: ty + i * 0.33, w: 4.3, h: 0.3,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "444444", align: "left", valign: "middle",
      margin: 0
    });
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
    ["指标", "Final-HTB", "Final"],
    ["finance 带宽", "竞争均分", "12 Mbps"],
    ["dorm 带宽", "竞争均分", "2 Mbps"],
    ["teach 带宽", "竞争均分", "2 Mbps"],
    ["lib 带宽", "竞争均分", "2 Mbps"],
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
        slide.addShape(pres.shapes.RECTANGLE, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fill: { color: ri % 2 === 0 ? "FFFFFF" : "F5F5F5" }
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
  slide.addText("核心结论: 财务区域获得 60% 带宽保障，\n低优先级区域仅 10% 保活带宽", {
    x: 5.85, y: ry + 0.05, w: 3.1, h: 0.45,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: "2A7D2F", bold: true, align: "left", valign: "middle",
    margin: 0
  });

  // Bottom note
  slide.addText("实验方法: Final-HTB (无 QoS) vs Final (HTB 两级优先级) · iperf3 TCP 测试 · c1=12Mbps · c2=2Mbps · ceil=20Mbps", {
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
  slide.addText("5", {
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
  pres.writeFile({ fileName: "slide-05-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
