// slide-08.js — VPN + 双重 ACL 安全策略
const pptxgen = require("pptxgenjs");

const slideConfig = {
  type: 'content',
  index: 8,
  title: 'VPN + 双重 ACL'
};

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.8,
    fill: { color: theme.primary }
  });
  slide.addText("VPN + 双重 ACL 安全策略", {
    x: 0.5, y: 0.1, w: 9, h: 0.6,
    fontSize: 26, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "left",
    margin: 0
  });

  // LEFT: Video placeholder
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.45, y: 1.05, w: 5.0, h: 3.55,
    fill: { color: "1A1A2E" },
    rectRadius: 0.08
  });

  // Play button overlay
  slide.addShape(pres.shapes.OVAL, {
    x: 2.25, y: 2.1, w: 1.4, h: 1.4,
    fill: { color: "FFFFFF", transparency: 85 },
    line: { color: "FFFFFF", width: 3 }
  });

  // Play triangle
  slide.addText("▶", {
    x: 2.25, y: 2.1, w: 1.4, h: 1.4,
    fontSize: 40, color: "FFFFFF",
    align: "center", valign: "middle",
    margin: 0
  });

  slide.addText("VPN + 双重 ACL 演示视频", {
    x: 0.45, y: 3.85, w: 5.0, h: 0.3,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center", valign: "middle",
    margin: 0
  });

  slide.addText("（待插入录屏视频，届时对着视频讲解）", {
    x: 0.45, y: 4.15, w: 5.0, h: 0.25,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: "AAAAAA", align: "center",
    margin: 0
  });

  // RIGHT: Key points
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.7, y: 1.05, w: 3.85, h: 3.55,
    fill: { color: theme.bg },
    rectRadius: 0.08
  });

  slide.addText("机制说明", {
    x: 5.95, y: 1.15, w: 3.2, h: 0.3,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  // Two-layer ACL visual
  // Layer 1
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.95, y: 1.6, w: 3.4, h: 0.45,
    fill: { color: "E76F51" },
    rectRadius: 0.05
  });
  slide.addText("Layer 1  外部隔离 DROP", {
    x: 5.95, y: 1.6, w: 3.4, h: 0.45,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // Arrow down
  slide.addText("VPN 认证解除", {
    x: 5.95, y: 2.08, w: 3.4, h: 0.22,
    fontSize: 9, fontFace: "Microsoft YaHei",
    color: theme.accent, bold: true, align: "center",
    margin: 0
  });

  // Layer 2
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.95, y: 2.32, w: 3.4, h: 0.45,
    fill: { color: theme.secondary },
    rectRadius: 0.05
  });
  slide.addText("Layer 2  校内精细化 ACL", {
    x: 5.95, y: 2.32, w: 3.4, h: 0.45,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center", valign: "middle",
    margin: 0
  });

  // VPN 3-stage process
  slide.addText("VPN 三阶段接入", {
    x: 5.95, y: 2.95, w: 3.2, h: 0.25,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true, align: "left",
    margin: 0
  });

  const steps = [
    "① 身份认证 — 验证校外用户凭据",
    "② 身份切换 — 切换到校内身份",
    "③ 权限授权 — 精细化 ACL 策略",
  ];

  steps.forEach((s, i) => {
    slide.addText(s, {
      x: 6.15, y: 3.25 + i * 0.3, w: 3.2, h: 0.28,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: "444444", align: "left", valign: "middle",
      margin: 0
    });
  });

  // key insight box
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.95, y: 4.22, w: 3.4, h: 0.28,
    fill: { color: "FFF8E1" },
    rectRadius: 0.03
  });
  slide.addText("拓扑: home_pc → s_home → r1 (20Mbps/10ms)", {
    x: 5.95, y: 4.22, w: 3.4, h: 0.28,
    fontSize: 8, fontFace: "Microsoft YaHei",
    color: "BF8C00", align: "center", valign: "middle",
    margin: 0
  });

  // Bottom note
  slide.addText("演示命令: enable_vpn(\"home_pc\") · show_identity() · access_resource() · 双重 ACL 规则顺序验证", {
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
  slide.addText("8", {
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
  pres.writeFile({ fileName: "slide-08-preview.pptx" });
}

module.exports = { createSlide, slideConfig };
