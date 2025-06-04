import React from "react";

export default function Features() {
  return (
    <section id="features">
      <div className="container">
        <div className="text-center">
          <h2 className="section-title">Powerful Features</h2>
          <p className="section-subtitle">
            Our AI-powered platform transforms messy receipts into structured, actionable data
          </p>
        </div>
        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-robot"></i></div>
            <h3>AI-Powered OCR</h3>
            <p>Advanced optical character recognition extracts text from any receipt with 99% accuracy.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-cogs"></i></div>
            <h3>Smart Data Extraction</h3>
            <p>Automatically identifies merchants, dates, line items, taxes, and totals.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-file-excel"></i></div>
            <h3>Export to Excel</h3>
            <p>One-click export to Excel, CSV, or Google Sheets for further analysis.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-mobile-alt"></i></div>
            <h3>Mobile App</h3>
            <p>Capture receipts on the go with our iOS and Android apps.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-cloud"></i></div>
            <h3>Cloud Sync</h3>
            <p>Access your receipt data anywhere with secure cloud storage.</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon"><i className="fas fa-chart-pie"></i></div>
            <h3>Expense Analytics</h3>
            <p>Visualize spending patterns and generate expense reports automatically.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
