import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import App from "./App";
import { applyTheme, savedTheme } from "./features/profile/theme";

// Тема ставится до первой отрисовки, а не в оболочке. Выбранную в компоненте
// её видно через кадр после белого экрана — и этот кадр бьёт по глазам ровно
// тому, кто тёмную и выбрал.
applyTheme(savedTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
