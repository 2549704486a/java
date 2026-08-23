import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import OperatorApp from "./components/OperatorApp";
import "./operator.css";
import "./styles.css";

const isOperatorWorkbench = window.location.pathname.startsWith("/operator");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isOperatorWorkbench ? <OperatorApp /> : <App />}
  </React.StrictMode>
);
