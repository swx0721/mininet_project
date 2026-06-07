// compile.js — Combine all slides into final presentation
const pptxgen = require("pptxgenjs");
const path = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Campus Network Project";
pres.title = "校园网络仿真项目汇报";

// Pure Tech Blue palette
const theme = {
  primary: "03045e",
  secondary: "0077b6",
  accent: "00b4d8",
  light: "90e0ef",
  bg: "F0F7FF"
};

const totalSlides = 9;

for (let i = 1; i <= totalSlides; i++) {
  const num = String(i).padStart(2, "0");
  const slideModule = require(`./slide-${num}.js`);
  slideModule.createSlide(pres, theme);
  console.log(`  [OK] Slide ${num} added`);
}

const outputPath = path.join(__dirname, "output", "校园网络仿真项目汇报.pptx");
pres.writeFile({ fileName: outputPath }).then(() => {
  console.log(`\n  Done! Output: ${outputPath}`);
}).catch(err => {
  console.error("Error:", err.message);
});
