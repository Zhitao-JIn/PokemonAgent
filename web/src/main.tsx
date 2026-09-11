import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

// index.html 引的就是这个文件（/src/main.tsx），名字动它就白屏。
// StrictMode 在 dev 下会把 effect 跑两遍——这不是 bug，是故意暴露
// "清理函数没写对"的组件。useRunStream 的 cleanup 必须经得起这个考验。
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
