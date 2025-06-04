import React from "react";
import { useNavigate } from "react-router-dom";

export default function Hero() {
  const navigate = useNavigate();

  const handleTryNow = (e) => {
    e.preventDefault();
    navigate("/file");
  };

  return (
    <section className="hero">
      <div className="container">
        <div className="hero-content">
          <h1>Transform Your Receipts into Actionable Data</h1>
          <p>
            SlickReceipts.com uses advanced AI to extract, organize, and analyze your receipt data. Say goodbye to manual data entry forever.
          </p>
          <div className="hero-buttons">
            <a
              href="/file"
              onClick={handleTryNow}
              className="btn btn-primary"
            >
              Try It Free
            </a>
            <a href="#" className="btn btn-secondary">View Demo</a>
          </div>
        </div>
      </div>
    </section>
  );
}