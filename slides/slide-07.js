// slide-07.js — 安全策略消融实验
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 7,
  title: '安全策略消融实验'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("安全策略消融实验 — Flood + IDS + 审计", {
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

  // Three security modules
  const modules = [
    {
      icon: "🌀", title: "ICMP Flood 防护",
      desc: "iptables limit 1/s burst=5\n插入 ESTABLISHED 之前，\n强制所有 ICMP 先经限速检查"
    },
    {
      icon: "🔍", title: "端口扫描检测",
      desc: "10s 滑动窗口 · 阈值 20 端口\n触发自动封禁 300s\n双向 iptables DROP"
    },
    {
      icon: "📊", title: "SQLite 安全审计",
      desc: "记录 FLOOD / PORT_SCAN / BAN\n事件类型分布统计\n完整审计溯源"
    },
  ];

  modules.forEach((m, i) => {
    const my = 1.65 + i * 1.0;

    // Module card
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.8, y: my, w: 4.1, h: 0.85,
      fill: { color: "FFFFFF" },
      rectRadius: 0.06,
      line: { color: theme.light, width: 1 }
    });

    // Icon placeholder
    slide.addText(m.icon, {
      x: 0.95, y: my + 0.15, w: 0.5, h: 0.5,
      fontSize: 22, align: "center", valign: "middle",
      margin: 0
    });

    // Title
    slide.addText(m.title, {
      x: 1.55, y: my + 0.08, w: 3.1, h: 0.28,
      fontSize: 13, fontFace: "Microsoft YaHei",
      color: theme.primary, bold: true, align: "left",
      margin: 0
    });

    // Description
    slide.addText(m.desc, {
      x: 1.55, y: my + 0.35, w: 3.1, h: 0.45,
      fontSize: 9, fontFace: "Microsoft YaHei",
      color: "666666", align: "left", valign: "top",
      margin: 0
    });
  });

  // RIGHT: Results
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.4, y: 1.05, w: 4.15, h: 3.55,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("实验结果 (对照组 → 实验组)", {
    x: 5.65, y: 1.15, w: 3.5, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  // Results table
  const resData = [
    ["指标", "无安全", "有安全"],
    ["ICMP Flood", "40/40", "5/40"],
    ["端口扫描", "30/30", "20/30"],
    ["扫描检测", "❌", "✅"],
    ["自动封禁", "❌", "✅ 第20端口"],
    ["SQLite 事件", "0", "3"],
  ];

  let ry = 1.65;
  const rColWs = [1.5, 1.2, 1.2];
  const rColXs = [5.65, 7.15, 8.35];

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
        const isImproved = ci === 2 && (ri === 1 || ri === 2 || ri === 5);
        slide.addShape(pres.shapes.RECTANGLE, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fill: { color: isEven ? "FFFFFF" : "F5F5F5" }
        });
        slide.addText(cell, {
          x: rColXs[ci], y: ry, w: rColWs[ci], h: rowH,
          fontSize: 10, fontFace: "Microsoft YaHei",
          color: isImproved ? "2A7D2F" : (ci === 1 ? "999999" : "333333"),
          bold: isImproved || ci === 0,
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

  // Audit DB detail
  ry += 0.15;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.65, y: ry, w: 3.5, h: 0.9,
    fill: { color: "E8F5E9" },
    rectRadius: 0.05
  });
  slide.addText("SQLite 审计记录:", {
    x: 5.8, y: ry + 0.05, w: 3.2, h: 0.22,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "2A7D2F", bold: true, align: "left",
    margin: 0
  });
  slide.addText("FLOOD (DROP 35包) → PORT_SCAN (20端口)\n→ BAN (封禁 300s)", {
    x: 5.8, y: ry + 0.28, w: 3.2, h: 0.55,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "444444", align: "left", valign: "top",
    margin: 0
  });

  // Bottom note
  slide.addText("实验方法: Final-Security (仅 HTB QoS) vs Final (ACL+Flood防护+端口扫描+SQLite审计)", {
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
  slide.addText("7", {
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
  pres.writeFile({ fileName: "slide-07-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
